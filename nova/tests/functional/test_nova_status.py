#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from __future__ import absolute_import

import copy
import fixtures
from six.moves import StringIO

from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import placement.db_api

from nova.cmd import status
import nova.conf
from nova import context
# NOTE(mriedem): We only use objects as a convenience to populate the database
# in the tests, we don't use them in the actual CLI.
from nova import objects
from nova import rc_fields as fields
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures

CONF = nova.conf.CONF

# This is what the ResourceTracker sets up in the nova-compute service.
FAKE_VCPU_INVENTORY = {
    'resource_class': fields.ResourceClass.VCPU,
    'total': 32,
    'reserved': 4,
    'min_unit': 1,
    'max_unit': 1,
    'step_size': 1,
    'allocation_ratio': 1.0,
}

# This is the kind of thing that Neutron will setup externally for routed
# networks.
FAKE_IP_POOL_INVENTORY = {
    'resource_class': fields.ResourceClass.IPV4_ADDRESS,
    'total': 256,
    'reserved': 10,
    'min_unit': 1,
    'max_unit': 1,
    'step_size': 1,
    'allocation_ratio': 1.0,
}


class TestUpgradeCheckResourceProviders(test.NoDBTestCase):
    """Tests for the nova-status upgrade check on resource providers."""

    # We'll setup the database ourselves because we need to use cells fixtures
    # for multiple cell mappings.
    USES_DB_SELF = True

    def setUp(self):
        super(TestUpgradeCheckResourceProviders, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        # We always need the API DB to be setup.
        self.useFixture(nova_fixtures.Database(database='api'))
        # Setting up the placement fixtures is complex because we need
        # the status command (which access the placement tables directly)
        # to have access to the right database engine. So first we create
        # a config, then the PlacementFixtur and then monkey patch the
        # old placement get_placement_engine code.
        config = cfg.ConfigOpts()
        conf_fixture = self.useFixture(config_fixture.Config(config))
        placement_fixture = self.useFixture(func_fixtures.PlacementFixture(
            conf_fixture=conf_fixture, db=True))
        self.placement_api = placement_fixture.api
        # We need the code in status to be using the database we've set up.
        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.api.openstack.placement.db_api.get_placement_engine',
                placement.db_api.get_placement_engine))
        self.cmd = status.UpgradeCommands()

    def test_check_resource_providers_fresh_install_no_mappings(self):
        """Tests the scenario where we don't have any cell mappings (no cells
        v2 setup yet) and no compute nodes in the single main database.
        """
        # We don't have a cell mapping, just the regular old main database
        # because let's assume they haven't run simple_cell_setup yet.
        self.useFixture(nova_fixtures.Database())
        result = self.cmd._check_resource_providers()
        # this is assumed to be base install so it's OK but with details
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIn('There are no compute resource providers in the '
                      'Placement service nor are there compute nodes in the '
                      'database',
                      result.details)

    def test_check_resource_providers_no_rps_no_computes_in_cell1(self):
        """Tests the scenario where we have a cell mapping with no computes in
        it and no resource providers (because of no computes).
        """
        # this will setup two cell mappings, one for cell0 and a single cell1
        self._setup_cells()
        # there are no compute nodes in the cell1 database so we have 0
        # resource providers and 0 compute nodes, so it's assumed to be a fresh
        # install and not a failure.
        result = self.cmd._check_resource_providers()
        # this is assumed to be base install so it's OK but with details
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIn('There are no compute resource providers in the '
                      'Placement service nor are there compute nodes in the '
                      'database',
                      result.details)

    def test_check_resource_providers_no_rps_one_compute(self):
        """Tests the scenario where we have compute nodes in the cell but no
        resource providers yet - VCPU or otherwise. This is a warning because
        the compute isn't reporting into placement.
        """
        self._setup_cells()
        # create a compute node which will be in cell1 by default
        cn = objects.ComputeNode(
            context=context.get_admin_context(),
            host='fake-host',
            vcpus=4,
            memory_mb=8 * 1024,
            local_gb=40,
            vcpus_used=2,
            memory_mb_used=2 * 1024,
            local_gb_used=10,
            hypervisor_type='fake',
            hypervisor_version=1,
            cpu_info='{"arch": "x86_64"}')
        cn.create()
        result = self.cmd._check_resource_providers()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        self.assertIn('There are no compute resource providers in the '
                      'Placement service but there are 1 compute nodes in the '
                      'deployment.', result.details)

    def _create_resource_provider(self, inventory):
        """Helper method to create a resource provider with inventory over
        the placement HTTP API.
        """
        # We must copy the incoming inventory because it will be used in
        # other tests in this module, and we pop from it, below.
        inventory = copy.copy(inventory)
        rp_uuid = uuidutils.generate_uuid()
        rp = {'name': rp_uuid, 'uuid': rp_uuid}
        url = '/resource_providers'
        resp = self.placement_api.post(url, body=rp)
        self.assertTrue(resp.status < 400, resp.body)
        res_class = inventory.pop('resource_class')
        data = {'inventories': {res_class: inventory}}
        data['resource_provider_generation'] = 0
        url = '/resource_providers/%s/inventories' % rp_uuid
        resp = self.placement_api.put(url, body=data)
        self.assertTrue(resp.status < 400, resp.body)

    def test_check_resource_providers_no_compute_rps_one_compute(self):
        """Tests the scenario where we have compute nodes in the cell but no
        compute (VCPU) resource providers yet. This is a failure warning the
        compute isn't reporting into placement.
        """
        self._setup_cells()
        # create a compute node which will be in cell1 by default
        cn = objects.ComputeNode(
            context=context.get_admin_context(),
            host='fake-host',
            vcpus=4,
            memory_mb=8 * 1024,
            local_gb=40,
            vcpus_used=2,
            memory_mb_used=2 * 1024,
            local_gb_used=10,
            hypervisor_type='fake',
            hypervisor_version=1,
            cpu_info='{"arch": "x86_64"}')
        cn.create()

        # create a single resource provider that represents an external shared
        # IP allocation pool - this tests our filtering when counting resource
        # providers
        self._create_resource_provider(FAKE_IP_POOL_INVENTORY)

        result = self.cmd._check_resource_providers()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        self.assertIn('There are no compute resource providers in the '
                      'Placement service but there are 1 compute nodes in the '
                      'deployment.', result.details)

    def test_check_resource_providers_fewer_rps_than_computes(self):
        """Tests the scenario that we have fewer resource providers than
        compute nodes which is a warning because we're underutilized.
        """
        # setup the cell0 and cell1 mappings
        self._setup_cells()

        # create two compute nodes (by default in cell1)
        ctxt = context.get_admin_context()
        for x in range(2):
            cn = objects.ComputeNode(
                context=ctxt,
                host=getattr(uuids, str(x)),
                vcpus=4,
                memory_mb=8 * 1024,
                local_gb=40,
                vcpus_used=2,
                memory_mb_used=2 * 1024,
                local_gb_used=10,
                hypervisor_type='fake',
                hypervisor_version=1,
                cpu_info='{"arch": "x86_64"}')
            cn.create()

        # create a single resource provider with some VCPU inventory
        self._create_resource_provider(FAKE_VCPU_INVENTORY)

        result = self.cmd._check_resource_providers()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        self.assertIn('There are 1 compute resource providers and 2 compute '
                      'nodes in the deployment.', result.details)

    def test_check_resource_providers_equal_rps_to_computes(self):
        """This tests the happy path scenario where we have an equal number
        of compute resource providers to compute nodes.
        """
        # setup the cell0 and cell1 mappings
        self._setup_cells()

        # create a single compute node
        ctxt = context.get_admin_context()
        cn = objects.ComputeNode(
            context=ctxt,
            host=uuids.host,
            vcpus=4,
            memory_mb=8 * 1024,
            local_gb=40,
            vcpus_used=2,
            memory_mb_used=2 * 1024,
            local_gb_used=10,
            hypervisor_type='fake',
            hypervisor_version=1,
            cpu_info='{"arch": "x86_64"}')
        cn.create()

        # create a deleted compute node record (shouldn't count)
        cn2 = objects.ComputeNode(
            context=ctxt,
            host='fakehost',
            vcpus=4,
            memory_mb=8 * 1024,
            local_gb=40,
            vcpus_used=2,
            memory_mb_used=2 * 1024,
            local_gb_used=10,
            hypervisor_type='fake',
            hypervisor_version=1,
            cpu_info='{"arch": "x86_64"}')
        cn2.create()
        cn2.destroy()

        # create a single resource provider with some VCPU inventory
        self._create_resource_provider(FAKE_VCPU_INVENTORY)
        # create an externally shared IP allocation pool resource provider
        self._create_resource_provider(FAKE_IP_POOL_INVENTORY)

        # Stub out _count_compute_nodes to make sure we never call it without
        # a cell-targeted context.
        original_count_compute_nodes = (
            status.UpgradeCommands._count_compute_nodes)

        def stub_count_compute_nodes(_self, context=None):
            self.assertIsNotNone(context.db_connection)
            return original_count_compute_nodes(_self, context=context)
        self.stub_out('nova.cmd.status.UpgradeCommands._count_compute_nodes',
                      stub_count_compute_nodes)

        result = self.cmd._check_resource_providers()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIsNone(result.details)

# Copyright 2016 IBM Corp.
#
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

"""
Unit tests for the nova-status CLI interfaces.
"""

import fixtures
import mock
from six.moves import StringIO

from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as keystone
from keystoneauth1 import session
from oslo_utils import uuidutils

from nova.cmd import status
import nova.conf
from nova import context
# NOTE(mriedem): We only use objects as a convenience to populate the database
# in the tests, we don't use them in the actual CLI.
from nova import objects
from nova.objects import fields
from nova.objects import resource_provider as rp_obj
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests import uuidsentinel as uuids

CONF = nova.conf.CONF


class TestNovaStatusMain(test.NoDBTestCase):
    """Tests for the basic nova-status command infrastructure."""

    def setUp(self):
        super(TestNovaStatusMain, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))

    @mock.patch.object(status.config, 'parse_args')
    @mock.patch.object(status, 'CONF')
    def _check_main(self, mock_CONF, mock_parse_args,
                    category_name='check', expected_return_value=0):
        mock_CONF.category.name = category_name
        return_value = status.main()

        self.assertEqual(expected_return_value, return_value)
        mock_CONF.register_cli_opt.assert_called_once_with(
            status.category_opt)

    @mock.patch.object(status.version, 'version_string_with_package',
                       return_value="x.x.x")
    def test_main_version(self, mock_version_string):
        self._check_main(category_name='version')
        self.assertEqual("x.x.x\n", self.output.getvalue())

    @mock.patch.object(status.cmd_common, 'print_bash_completion')
    def test_main_bash_completion(self, mock_print_bash):
        self._check_main(category_name='bash-completion')
        mock_print_bash.assert_called_once_with(status.CATEGORIES)

    @mock.patch.object(status.cmd_common, 'get_action_fn')
    def test_main(self, mock_get_action_fn):
        mock_fn = mock.Mock()
        mock_fn_args = [mock.sentinel.arg]
        mock_fn_kwargs = {'key': mock.sentinel.value}
        mock_get_action_fn.return_value = (mock_fn, mock_fn_args,
                                           mock_fn_kwargs)

        self._check_main(expected_return_value=mock_fn.return_value)
        mock_fn.assert_called_once_with(mock.sentinel.arg,
                                        key=mock.sentinel.value)

    @mock.patch.object(status.cmd_common, 'get_action_fn')
    def test_main_error(self, mock_get_action_fn):
        mock_fn = mock.Mock(side_effect=Exception('wut'))
        mock_get_action_fn.return_value = (mock_fn, [], {})

        self._check_main(expected_return_value=255)
        output = self.output.getvalue()
        self.assertIn('Error:', output)
        # assert the traceback is in the output
        self.assertIn('wut', output)


class TestPlacementCheck(test.NoDBTestCase):
    """Tests the nova-status placement checks.

    These are done with mock as the ability to replicate all failure
    domains otherwise is quite complicated. Using a devstack
    environment you can validate each of these tests are matching
    reality.
    """

    def setUp(self):
        super(TestPlacementCheck, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.cmd = status.UpgradeCommands()

    @mock.patch.object(keystone, "load_auth_from_conf_options")
    def test_no_auth(self, auth):
        """Test failure when no credentials are specified.

        Replicate in devstack: start devstack with or without
        placement engine, remove the auth section from the [placement]
        block in nova.conf.
        """
        auth.side_effect = ks_exc.MissingAuthPlugin()
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('No credentials specified', res.details)

    @mock.patch.object(keystone, "load_auth_from_conf_options")
    @mock.patch.object(session.Session, 'request')
    def _test_placement_get_interface(
            self, expected_interface, mock_get, mock_auth):

        def fake_request(path, method, *a, **kw):
            self.assertEqual(mock.sentinel.path, path)
            self.assertEqual('GET', method)
            self.assertIn('endpoint_filter', kw)
            self.assertEqual(expected_interface,
                             kw['endpoint_filter']['interface'])
            return mock.Mock(autospec='requests.models.Response')

        mock_get.side_effect = fake_request
        self.cmd._placement_get(mock.sentinel.path)
        mock_auth.assert_called_once_with(status.CONF, 'placement')
        self.assertTrue(mock_get.called)

    def test_placement_get_interface_default(self):
        """Tests that we try internal, then public interface by default."""
        self._test_placement_get_interface(['internal', 'public'])

    def test_placement_get_interface_internal(self):
        """Tests that "internal" is specified for interface when configured."""
        # TODO(efried): Test that the deprecated opts (e.g. os_interface) still
        #               work once bug #1709728 is resolved.
        self.flags(valid_interfaces='internal', group='placement')
        self._test_placement_get_interface(['internal'])

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_auth(self, get):
        """Test failure when wrong credentials are specified or service user
        doesn't exist.

        Replicate in devstack: start devstack with or without
        placement engine, specify random credentials in auth section
        from the [placement] block in nova.conf.

        """
        get.side_effect = ks_exc.Unauthorized()
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('Placement service credentials do not work', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_endpoint(self, get):
        """Test failure when no endpoint exists.

        Replicate in devstack: start devstack without placement
        engine, but create valid placement service user and specify it
        in auth section of [placement] in nova.conf.
        """
        get.side_effect = ks_exc.EndpointNotFound()
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('Placement API endpoint not found', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_discovery_failure(self, get):
        """Test failure when discovery for placement URL failed.

        Replicate in devstack: start devstack with placement
        engine, create valid placement service user and specify it
        in auth section of [placement] in nova.conf. Stop keystone service.
        """
        get.side_effect = ks_exc.DiscoveryFailure()
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('Discovery for placement API URI failed.', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_down_endpoint(self, get):
        """Test failure when endpoint is down.

        Replicate in devstack: start devstack with placement
        engine, disable placement engine apache config.
        """
        get.side_effect = ks_exc.NotFound()
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('Placement API does not seem to be running', res.details)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_valid_version(self, get):
        get.return_value = {
            "versions": [
                {
                    "min_version": "1.0",
                    "max_version": "1.17",
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, res.code)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_version_comparison_does_not_use_floats(self, get):
        # NOTE(rpodolyaka): previously _check_placement() coerced the version
        # numbers to floats prior to comparison, that would lead to failures
        # in cases like float('1.10') < float('1.4'). As we require 1.4+ now,
        # the _check_placement() call below will assert that version comparison
        # continues to work correctly when Placement API versions 1.10
        # (or newer) is released
        get.return_value = {
             "versions": [
                {
                    "min_version": "1.0",
                    "max_version": "1.17",
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, res.code)

    @mock.patch.object(status.UpgradeCommands, "_placement_get")
    def test_invalid_version(self, get):
        get.return_value = {
            "versions": [
                {
                    "min_version": "0.9",
                    "max_version": "0.9",
                    "id": "v1.0"
                }
            ]
        }
        res = self.cmd._check_placement()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, res.code)
        self.assertIn('Placement API version 1.17 needed, you have 0.9',
                      res.details)


class TestUpgradeCheckBasic(test.NoDBTestCase):
    """Tests for the nova-status upgrade check command.

    The tests in this class should just test basic logic and use mock. Real
    checks which require more elaborate fixtures or the database should be done
    in separate test classes as they are more or less specific to a particular
    release and may be removed in a later release after they are no longer
    needed.
    """

    def setUp(self):
        super(TestUpgradeCheckBasic, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.cmd = status.UpgradeCommands()

    def test_check_success(self):
        fake_checks = (
            ('good', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            ))),
        )
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.SUCCESS, self.cmd.check())
        expected = """\
+-----------------------+
| Upgrade Check Results |
+-----------------------+
| Check: good           |
| Result: Success       |
| Details: None         |
+-----------------------+
"""
        self.assertEqual(expected, self.output.getvalue())

    def test_check_warning(self):
        fake_checks = (
            ('good', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            ))),
            ('warn', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.WARNING, 'there might be a problem'
            ))),
        )
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.WARNING, self.cmd.check())
        expected = """\
+-----------------------------------+
| Upgrade Check Results             |
+-----------------------------------+
| Check: good                       |
| Result: Success                   |
| Details: None                     |
+-----------------------------------+
| Check: warn                       |
| Result: Warning                   |
| Details: there might be a problem |
+-----------------------------------+
"""
        self.assertEqual(expected, self.output.getvalue())

    def test_check_failure(self):
        # make the error details over 60 characters so we test the wrapping
        error_details = 'go back to bed' + '!' * 60
        fake_checks = (
            ('good', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.SUCCESS
            ))),
            ('warn', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.WARNING, 'there might be a problem'
            ))),
            ('fail', mock.Mock(return_value=status.UpgradeCheckResult(
                status.UpgradeCheckCode.FAILURE, error_details
            ))),
        )
        with mock.patch.object(self.cmd, '_upgrade_checks', fake_checks):
            self.assertEqual(status.UpgradeCheckCode.FAILURE, self.cmd.check())
        expected = """\
+-----------------------------------------------------------------------+
| Upgrade Check Results                                                 |
+-----------------------------------------------------------------------+
| Check: good                                                           |
| Result: Success                                                       |
| Details: None                                                         |
+-----------------------------------------------------------------------+
| Check: warn                                                           |
| Result: Warning                                                       |
| Details: there might be a problem                                     |
+-----------------------------------------------------------------------+
| Check: fail                                                           |
| Result: Failure                                                       |
| Details: go back to bed!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! |
|   !!!!!!!!!!!!!!                                                      |
+-----------------------------------------------------------------------+
"""
        self.assertEqual(expected, self.output.getvalue())


class TestUpgradeCheckCellsV2(test.NoDBTestCase):
    """Tests for the nova-status upgrade cells v2 specific check."""

    # We'll setup the API DB fixture ourselves and slowly build up the
    # contents until the check passes.
    USES_DB_SELF = True

    def setUp(self):
        super(TestUpgradeCheckCellsV2, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.useFixture(nova_fixtures.Database(database='api'))
        self.cmd = status.UpgradeCommands()

    def test_check_no_cell_mappings(self):
        """The cells v2 check should fail because there are no cell mappings.
        """
        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('There needs to be at least two cell mappings',
                      result.details)

    def _create_cell_mapping(self, uuid):
        cm = objects.CellMapping(
            context=context.get_admin_context(),
            uuid=uuid,
            name=uuid,
            transport_url='fake://%s/' % uuid,
            database_connection=uuid)
        cm.create()
        return cm

    def test_check_no_cell0_mapping(self):
        """We'll create two cell mappings but not have cell0 mapped yet."""
        for i in range(2):
            uuid = getattr(uuids, str(i))
            self._create_cell_mapping(uuid)

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('No cell0 mapping found', result.details)

    def test_check_no_host_mappings_with_computes(self):
        """Creates a cell0 and cell1 mapping but no host mappings and there are
        compute nodes in the cell database.
        """
        self._setup_cells()
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

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        self.assertIn('No host mappings found but there are compute nodes',
                      result.details)

    def test_check_no_host_mappings_no_computes(self):
        """Creates the cell0 and cell1 mappings but no host mappings and no
        compute nodes so it's assumed to be an initial install.
        """
        self._setup_cells()

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIn('No host mappings or compute nodes were found',
                      result.details)

    def test_check_success(self):
        """Tests a successful cells v2 upgrade check."""
        # create the cell0 and first cell mappings
        self._setup_cells()
        # Start a compute service and create a hostmapping for it
        svc = self.start_service('compute')
        cell = self.cell_mappings[test.CELL1_NAME]
        hm = objects.HostMapping(context=context.get_admin_context(),
                                 host=svc.host,
                                 cell_mapping=cell)
        hm.create()

        result = self.cmd._check_cellsv2()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)
        self.assertIsNone(result.details)


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
        """Helper method to create a resource provider with inventory"""
        ctxt = context.get_admin_context()
        rp_uuid = uuidutils.generate_uuid()
        rp = rp_obj.ResourceProvider(
            context=ctxt,
            name=rp_uuid,
            uuid=rp_uuid)
        rp.create()
        inv = rp_obj.Inventory(
            context=ctxt,
            resource_provider=rp,
            **inventory)
        inv_list = rp_obj.InventoryList(objects=[inv])
        rp.set_inventory(inv_list)
        return rp

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
            deleted=1,
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


class TestUpgradeCheckIronicFlavorMigration(test.NoDBTestCase):
    """Tests for the nova-status upgrade check on ironic flavor migration."""

    # We'll setup the database ourselves because we need to use cells fixtures
    # for multiple cell mappings.
    USES_DB_SELF = True

    # This will create three cell mappings: cell0, cell1 (default) and cell2
    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(TestUpgradeCheckIronicFlavorMigration, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        # We always need the API DB to be setup.
        self.useFixture(nova_fixtures.Database(database='api'))
        self.cmd = status.UpgradeCommands()

    @staticmethod
    def _create_node_in_cell(ctxt, cell, hypervisor_type, nodename):
        with context.target_cell(ctxt, cell) as cctxt:
            cn = objects.ComputeNode(
                context=cctxt,
                hypervisor_type=hypervisor_type,
                hypervisor_hostname=nodename,
                # The rest of these values are fakes.
                host=uuids.host,
                vcpus=4,
                memory_mb=8 * 1024,
                local_gb=40,
                vcpus_used=2,
                memory_mb_used=2 * 1024,
                local_gb_used=10,
                hypervisor_version=1,
                cpu_info='{"arch": "x86_64"}')
            cn.create()
            return cn

    @staticmethod
    def _create_instance_in_cell(ctxt, cell, node, is_deleted=False,
                                 flavor_migrated=False):
        with context.target_cell(ctxt, cell) as cctxt:
            inst = objects.Instance(
                context=cctxt,
                host=node.host,
                node=node.hypervisor_hostname,
                uuid=uuidutils.generate_uuid())
            inst.create()

            if is_deleted:
                inst.destroy()
            else:
                # Create an embedded flavor for the instance. We don't create
                # this because we're in a cell context and flavors are global,
                # but we don't actually care about global flavors in this
                # check.
                extra_specs = {}
                if flavor_migrated:
                    extra_specs['resources:CUSTOM_BAREMETAL_GOLD'] = '1'
                inst.flavor = objects.Flavor(cctxt, extra_specs=extra_specs)
                inst.old_flavor = None
                inst.new_flavor = None
                inst.save()

            return inst

    def test_fresh_install_no_cell_mappings(self):
        """Tests the scenario where we don't have any cell mappings (no cells
        v2 setup yet) so we don't know what state we're in and we return a
        warning.
        """
        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        self.assertIn('Unable to determine ironic flavor migration without '
                      'cell mappings', result.details)

    def test_fresh_install_no_computes(self):
        """Tests a fresh install scenario where we have two non-cell0 cells
        but no compute nodes in either cell yet, so there is nothing to do
        and we return success.
        """
        self._setup_cells()
        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)

    def test_mixed_computes_deleted_ironic_instance(self):
        """Tests the scenario where we have a kvm compute node in one cell
        and an ironic compute node in another cell. The kvm compute node does
        not have any instances. The ironic compute node has an instance with
        the same hypervisor_hostname match but the instance is (soft) deleted
        so it's ignored.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()
        # Create the ironic compute node in cell1
        ironic_node = self._create_node_in_cell(
            ctxt, self.cell_mappings['cell1'], 'ironic', uuids.node_uuid)
        # Create the kvm compute node in cell2
        self._create_node_in_cell(
            ctxt, self.cell_mappings['cell2'], 'kvm', 'fake-kvm-host')

        # Now create an instance in cell1 which is on the ironic node but is
        # soft deleted (instance.deleted == instance.id).
        self._create_instance_in_cell(
            ctxt, self.cell_mappings['cell1'], ironic_node, is_deleted=True)

        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)

    def test_unmigrated_ironic_instances(self):
        """Tests a scenario where we have two cells with only ironic compute
        nodes. The first cell has one migrated and one unmigrated instance.
        The second cell has two unmigrated instances. The result is the check
        returns failure.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()

        # Create the ironic compute nodes in cell1
        for x in range(2):
            cell = self.cell_mappings['cell1']
            ironic_node = self._create_node_in_cell(
                ctxt, cell, 'ironic', getattr(uuids, 'cell1-node-%d' % x))
            # Create an instance for this node. In cell1, we have one
            # migrated and one unmigrated instance.
            flavor_migrated = True if x % 2 else False
            self._create_instance_in_cell(
                ctxt, cell, ironic_node, flavor_migrated=flavor_migrated)

        # Create the ironic compute nodes in cell2
        for x in range(2):
            cell = self.cell_mappings['cell2']
            ironic_node = self._create_node_in_cell(
                ctxt, cell, 'ironic', getattr(uuids, 'cell2-node-%d' % x))
            # Create an instance for this node. In cell2, all instances are
            # unmigrated.
            self._create_instance_in_cell(
                ctxt, cell, ironic_node, flavor_migrated=False)

        result = self.cmd._check_ironic_flavor_migration()
        self.assertEqual(status.UpgradeCheckCode.FAILURE, result.code)
        # Check the message - it should point out cell1 has one unmigrated
        # instance and cell2 has two unmigrated instances.
        unmigrated_instance_count_by_cell = {
            self.cell_mappings['cell1'].uuid: 1,
            self.cell_mappings['cell2'].uuid: 2
        }
        self.assertIn(
            'There are (cell=x) number of unmigrated instances in each '
            'cell: %s.' % ' '.join('(%s=%s)' % (
                cell_id, unmigrated_instance_count_by_cell[cell_id])
                    for cell_id in
                    sorted(unmigrated_instance_count_by_cell.keys())),
            result.details)


class TestUpgradeCheckAPIServiceVersion(test.NoDBTestCase):
    """Tests for the nova-status upgrade API service version specific check."""

    # We'll setup the database ourselves because we need to use cells fixtures
    # for multiple cell mappings.
    USES_DB_SELF = True

    # This will create three cell mappings: cell0, cell1 (default) and cell2
    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(TestUpgradeCheckAPIServiceVersion, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.useFixture(nova_fixtures.Database(database='api'))
        self.cmd = status.UpgradeCommands()

    def test_check_cells_v1_enabled(self):
        """This is a 'success' case since the API service version check is
        ignored when running cells v1.
        """
        self.flags(enable=True, group='cells')
        result = self.cmd._check_api_service_version()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)

    def test_check_no_cell_mappings_warning(self):
        """Warn when there are no cell mappings."""
        result = self.cmd._check_api_service_version()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        self.assertEqual('Unable to determine API service versions without '
                         'cell mappings.', result.details)

    @staticmethod
    def _create_service(ctxt, host, binary, version):
        svc = objects.Service(ctxt, host=host, binary=binary)
        svc.version = version
        svc.create()
        return svc

    def test_check_warning(self):
        """This is a failure scenario where we have the following setup:

        Three cells where:

        1. The first cell has two API services, one with version < 15 and one
           with version >= 15.
        2. The second cell has two services, one with version < 15 but it's
           deleted so it gets filtered out, and one with version >= 15.
        3. The third cell doesn't have any API services, just old compute
           services which should be filtered out.

        In this scenario, the first cell should be reported with a warning.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()
        cell0 = self.cell_mappings['cell0']
        with context.target_cell(ctxt, cell0) as cctxt:
            self._create_service(cctxt, host='cell0host1',
                                 binary='nova-osapi_compute', version=14)
            self._create_service(cctxt, host='cell0host2',
                                 binary='nova-osapi_compute', version=15)

        cell1 = self.cell_mappings['cell1']
        with context.target_cell(ctxt, cell1) as cctxt:
            svc = self._create_service(
                cctxt, host='cell1host1', binary='nova-osapi_compute',
                version=14)
            # This deleted record with the old version should get filtered out.
            svc.destroy()
            self._create_service(cctxt, host='cell1host2',
                                 binary='nova-osapi_compute', version=16)

        cell2 = self.cell_mappings['cell2']
        with context.target_cell(ctxt, cell2) as cctxt:
            self._create_service(cctxt, host='cell2host1',
                                 binary='nova-compute', version=14)

        result = self.cmd._check_api_service_version()
        self.assertEqual(status.UpgradeCheckCode.WARNING, result.code)
        # The only cell in the message should be cell0.
        self.assertIn(cell0.uuid, result.details)
        self.assertNotIn(cell1.uuid, result.details)
        self.assertNotIn(cell2.uuid, result.details)

    def test_check_success(self):
        """Tests the success scenario where we have cell0 with a current API
        service, cell1 with no API services, and an empty cell2.
        """
        self._setup_cells()
        ctxt = context.get_admin_context()
        cell0 = self.cell_mappings['cell0']
        with context.target_cell(ctxt, cell0) as cctxt:
            self._create_service(cctxt, host='cell0host1',
                                 binary='nova-osapi_compute', version=15)

        cell1 = self.cell_mappings['cell1']
        with context.target_cell(ctxt, cell1) as cctxt:
            self._create_service(cctxt, host='cell1host1',
                                 binary='nova-compute', version=15)

        result = self.cmd._check_api_service_version()
        self.assertEqual(status.UpgradeCheckCode.SUCCESS, result.code)

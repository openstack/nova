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

import mock
import os_resource_classes as orc
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conf
from nova import context
from nova import objects
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.functional import test_report_client as test_base
from nova.virt import driver as virt_driver


CONF = conf.CONF
VCPU = orc.VCPU
MEMORY_MB = orc.MEMORY_MB
DISK_GB = orc.DISK_GB
COMPUTE_HOST = 'compute-host'


class IronicResourceTrackerTest(test_base.SchedulerReportClientTestBase):
    """Tests the behaviour of the resource tracker with regards to the
    transitional period between adding support for custom resource classes in
    the placement API and integrating inventory and allocation records for
    Ironic baremetal nodes with those custom resource classes.
    """

    FLAVOR_FIXTURES = {
        'CUSTOM_SMALL_IRON': objects.Flavor(
            name='CUSTOM_SMALL_IRON',
            flavorid=42,
            vcpus=4,
            memory_mb=4096,
            root_gb=1024,
            swap=0,
            ephemeral_gb=0,
            extra_specs={},
    ),
        'CUSTOM_BIG_IRON': objects.Flavor(
            name='CUSTOM_BIG_IRON',
            flavorid=43,
            vcpus=16,
            memory_mb=65536,
            root_gb=1024,
            swap=0,
            ephemeral_gb=0,
            extra_specs={},
        ),
    }

    COMPUTE_NODE_FIXTURES = {
        uuids.cn1: objects.ComputeNode(
            uuid=uuids.cn1,
            hypervisor_hostname='cn1',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=4,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=4096,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=1024,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
        uuids.cn2: objects.ComputeNode(
            uuid=uuids.cn2,
            hypervisor_hostname='cn2',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=4,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=4096,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=1024,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
        uuids.cn3: objects.ComputeNode(
            uuid=uuids.cn3,
            hypervisor_hostname='cn3',
            hypervisor_type='ironic',
            hypervisor_version=0,
            cpu_info="",
            host=COMPUTE_HOST,
            vcpus=16,
            vcpus_used=0,
            cpu_allocation_ratio=1.0,
            memory_mb=65536,
            memory_mb_used=0,
            ram_allocation_ratio=1.0,
            local_gb=2048,
            local_gb_used=0,
            disk_allocation_ratio=1.0,
        ),
    }

    INSTANCE_FIXTURES = {
        uuids.instance1: objects.Instance(
            uuid=uuids.instance1,
            flavor=FLAVOR_FIXTURES['CUSTOM_SMALL_IRON'],
            vm_state=vm_states.BUILDING,
            task_state=task_states.SPAWNING,
            power_state=power_state.RUNNING,
            project_id='project',
            user_id=uuids.user,
        ),
    }

    def _set_client(self, client):
        """Set up embedded report clients to use the direct one from the
        interceptor.
        """
        self.report_client = client
        self.rt.reportclient = client

    def setUp(self):
        super(IronicResourceTrackerTest, self).setUp()
        self.flags(
            reserved_host_memory_mb=0,
            cpu_allocation_ratio=1.0,
            ram_allocation_ratio=1.0,
            disk_allocation_ratio=1.0,
        )

        self.ctx = context.RequestContext('user', 'project')

        driver = mock.MagicMock(autospec=virt_driver.ComputeDriver)
        driver.node_is_available.return_value = True
        driver.update_provider_tree.side_effect = NotImplementedError
        self.driver_mock = driver
        self.rt = resource_tracker.ResourceTracker(COMPUTE_HOST, driver)
        self.instances = self.create_fixtures()

    def create_fixtures(self):
        for flavor in self.FLAVOR_FIXTURES.values():
            # Clone the object so the class variable isn't
            # modified by reference.
            flavor = flavor.obj_clone()
            flavor._context = self.ctx
            flavor.obj_set_defaults()
            flavor.create()

        # We create some compute node records in the Nova cell DB to simulate
        # data before adding integration for Ironic baremetal nodes with the
        # placement API...
        for cn in self.COMPUTE_NODE_FIXTURES.values():
            # Clone the object so the class variable isn't
            # modified by reference.
            cn = cn.obj_clone()
            cn._context = self.ctx
            cn.obj_set_defaults()
            cn.create()

        instances = {}
        for instance in self.INSTANCE_FIXTURES.values():
            # Clone the object so the class variable isn't
            # modified by reference.
            instance = instance.obj_clone()
            instance._context = self.ctx
            instance.obj_set_defaults()
            instance.create()
            instances[instance.uuid] = instance
        return instances

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                new=mock.Mock(return_value=False))
    @mock.patch('nova.objects.compute_node.ComputeNode.save', new=mock.Mock())
    def test_node_stats_isolation(self):
        """Regression test for bug 1784705 introduced in Ocata.

        The ResourceTracker.stats field is meant to track per-node stats
        so this test registers three compute nodes with a single RT where
        each node has unique stats, and then makes sure that after updating
        usage for an instance, the nodes still have their unique stats and
        nothing is leaked from node to node.
        """
        self.useFixture(func_fixtures.PlacementFixture())
        # Before the resource tracker is "initialized", we shouldn't have
        # any compute nodes or stats in the RT's cache...
        self.assertEqual(0, len(self.rt.compute_nodes))
        self.assertEqual(0, len(self.rt.stats))

        # Now "initialize" the resource tracker. This is what
        # nova.compute.manager.ComputeManager does when "initializing" the
        # nova-compute service. Do this in a predictable order so cn1 is
        # first and cn3 is last.
        for cn in sorted(self.COMPUTE_NODE_FIXTURES.values(),
                         key=lambda _cn: _cn.hypervisor_hostname):
            nodename = cn.hypervisor_hostname
            # Fake that each compute node has unique extra specs stats and
            # the RT makes sure those are unique per node.
            stats = {'node:%s' % nodename: nodename}
            self.driver_mock.get_available_resource.return_value = {
                'hypervisor_hostname': nodename,
                'hypervisor_type': 'ironic',
                'hypervisor_version': 0,
                'vcpus': cn.vcpus,
                'vcpus_used': cn.vcpus_used,
                'memory_mb': cn.memory_mb,
                'memory_mb_used': cn.memory_mb_used,
                'local_gb': cn.local_gb,
                'local_gb_used': cn.local_gb_used,
                'numa_topology': None,
                'resource_class': None,  # Act like admin hasn't set yet...
                'stats': stats,
            }
            self.driver_mock.get_inventory.return_value = {
                'CUSTOM_SMALL_IRON': {
                    'total': 1,
                    'reserved': 0,
                    'min_unit': 1,
                    'max_unit': 1,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                },
            }
            self.rt.update_available_resource(self.ctx, nodename)

        self.assertEqual(3, len(self.rt.compute_nodes))
        self.assertEqual(3, len(self.rt.stats))

        def _assert_stats():
            # Make sure each compute node has a unique set of stats and
            # they don't accumulate across nodes.
            for _cn in self.rt.compute_nodes.values():
                node_stats_key = 'node:%s' % _cn.hypervisor_hostname
                self.assertIn(node_stats_key, _cn.stats)
                node_stat_count = 0
                for stat in _cn.stats:
                    if stat.startswith('node:'):
                        node_stat_count += 1
                self.assertEqual(1, node_stat_count, _cn.stats)
        _assert_stats()

        # Now "spawn" an instance to the first compute node by calling the
        # RT's instance_claim().
        cn1_obj = self.COMPUTE_NODE_FIXTURES[uuids.cn1]
        cn1_nodename = cn1_obj.hypervisor_hostname
        inst = self.instances[uuids.instance1]
        with self.rt.instance_claim(self.ctx, inst, cn1_nodename, {}):
            _assert_stats()


class TestUpdateComputeNodeReservedAndAllocationRatio(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests reflecting reserved and allocation ratio inventory from
    nova-compute to placement
    """

    compute_driver = 'fake.FakeDriver'

    @staticmethod
    def _get_reserved_host_values_from_config():
        return {
            'VCPU': CONF.reserved_host_cpus,
            'MEMORY_MB': CONF.reserved_host_memory_mb,
            'DISK_GB': compute_utils.convert_mb_to_ceil_gb(
                CONF.reserved_host_disk_mb)
        }

    def _assert_reserved_inventory(self, inventories):
        reserved = self._get_reserved_host_values_from_config()
        for rc, res in reserved.items():
            self.assertIn('reserved', inventories[rc])
            self.assertEqual(res, inventories[rc]['reserved'],
                             'Unexpected resource provider inventory '
                             'reserved value for %s' % rc)

    def test_update_inventory_reserved_and_allocation_ratio_from_conf(self):
        # Start a compute service which should create a corresponding resource
        # provider in the placement service.
        compute_service = self._start_compute('fake-host')
        # Assert the compute node resource provider exists in placement with
        # the default reserved and allocation ratio values from config.
        rp_uuid = self._get_provider_uuid_by_host('fake-host')
        inventories = self._get_provider_inventory(rp_uuid)
        # The default allocation ratio config values are all 0.0 and get
        # defaulted to real values in the ComputeNode object, so we need to
        # check our defaults against what is in the ComputeNode object.
        ctxt = context.get_admin_context()
        # Note that the CellDatabases fixture usage means we don't need to
        # target the context to cell1 even though the compute_nodes table is
        # in the cell1 database.
        cn = objects.ComputeNode.get_by_uuid(ctxt, rp_uuid)
        ratios = {
            'VCPU': cn.cpu_allocation_ratio,
            'MEMORY_MB': cn.ram_allocation_ratio,
            'DISK_GB': cn.disk_allocation_ratio
        }
        for rc, ratio in ratios.items():
            self.assertIn(rc, inventories)
            self.assertIn('allocation_ratio', inventories[rc])
            self.assertEqual(ratio, inventories[rc]['allocation_ratio'],
                             'Unexpected allocation ratio for %s' % rc)
        self._assert_reserved_inventory(inventories)

        # Now change the configuration values, restart the compute service,
        # and ensure the changes are reflected in the resource provider
        # inventory records. We use 2.0 since disk_allocation_ratio defaults
        # to 1.0.
        self.flags(cpu_allocation_ratio=2.0)
        self.flags(ram_allocation_ratio=2.0)
        self.flags(disk_allocation_ratio=2.0)
        self.flags(reserved_host_cpus=2)
        self.flags(reserved_host_memory_mb=1024)
        self.flags(reserved_host_disk_mb=8192)

        self.restart_compute_service(compute_service)

        # The ratios should now come from config overrides rather than the
        # defaults in the ComputeNode object.
        ratios = {
            'VCPU': CONF.cpu_allocation_ratio,
            'MEMORY_MB': CONF.ram_allocation_ratio,
            'DISK_GB': CONF.disk_allocation_ratio
        }
        attr_map = {
            'VCPU': 'cpu',
            'MEMORY_MB': 'ram',
            'DISK_GB': 'disk',
        }
        cn = objects.ComputeNode.get_by_uuid(ctxt, rp_uuid)
        inventories = self._get_provider_inventory(rp_uuid)
        for rc, ratio in ratios.items():
            # Make sure the config is what we expect.
            self.assertEqual(2.0, ratio,
                             'Unexpected config allocation ratio for %s' % rc)
            # Make sure the values in the DB are updated.
            self.assertEqual(
                ratio, getattr(cn, '%s_allocation_ratio' % attr_map[rc]),
                'Unexpected ComputeNode allocation ratio for %s' % rc)
            # Make sure the values in placement are updated.
            self.assertEqual(ratio, inventories[rc]['allocation_ratio'],
                             'Unexpected resource provider inventory '
                             'allocation ratio for %s' % rc)

        # The reserved host values should also come from config.
        self._assert_reserved_inventory(inventories)

    def test_allocation_ratio_create_with_initial_allocation_ratio(self):
        # The xxx_allocation_ratio is set to None by default, and we use
        # 16.1/1.6/1.1 since disk_allocation_ratio defaults to 16.0/1.5/1.0.
        self.flags(initial_cpu_allocation_ratio=16.1)
        self.flags(initial_ram_allocation_ratio=1.6)
        self.flags(initial_disk_allocation_ratio=1.1)
        # Start a compute service which should create a corresponding resource
        # provider in the placement service.
        self._start_compute('fake-host')
        # Assert the compute node resource provider exists in placement with
        # the default reserved and allocation ratio values from config.
        rp_uuid = self._get_provider_uuid_by_host('fake-host')
        inventories = self._get_provider_inventory(rp_uuid)
        ctxt = context.get_admin_context()
        # Note that the CellDatabases fixture usage means we don't need to
        # target the context to cell1 even though the compute_nodes table is
        # in the cell1 database.
        cn = objects.ComputeNode.get_by_uuid(ctxt, rp_uuid)
        ratios = {
            'VCPU': cn.cpu_allocation_ratio,
            'MEMORY_MB': cn.ram_allocation_ratio,
            'DISK_GB': cn.disk_allocation_ratio
        }
        initial_ratio_conf = {
            'VCPU': CONF.initial_cpu_allocation_ratio,
            'MEMORY_MB': CONF.initial_ram_allocation_ratio,
            'DISK_GB': CONF.initial_disk_allocation_ratio
        }
        for rc, ratio in ratios.items():
            self.assertIn(rc, inventories)
            self.assertIn('allocation_ratio', inventories[rc])
            # Check the allocation_ratio values come from the new
            # CONF.initial_xxx_allocation_ratio
            self.assertEqual(initial_ratio_conf[rc], ratio,
                             'Unexpected allocation ratio for %s' % rc)
            # Check the initial allocation ratio is updated to inventories
            self.assertEqual(ratio, inventories[rc]['allocation_ratio'],
                             'Unexpected allocation ratio for %s' % rc)

    def test_allocation_ratio_overwritten_from_config(self):
        # NOTE(yikun): This test case includes below step:
        # 1. Overwrite the allocation_ratio via the placement API directly -
        #    run the RT.update_available_resource periodic and assert the
        #    allocation ratios are not overwritten from config.
        #
        # 2. Set the CONF.*_allocation_ratio, run the periodic, and assert
        #    that the config overwrites what was set via the placement API.
        compute_service = self._start_compute('fake-host')
        rp_uuid = self._get_provider_uuid_by_host('fake-host')
        ctxt = context.get_admin_context()

        rt = compute_service.manager.rt

        inv = self.placement_api.get(
            '/resource_providers/%s/inventories' % rp_uuid).body
        ratios = {'VCPU': 16.1, 'MEMORY_MB': 1.6, 'DISK_GB': 1.1}

        for rc, ratio in ratios.items():
            inv['inventories'][rc]['allocation_ratio'] = ratio

        # Overwrite the allocation_ratio via the placement API directly
        self._update_inventory(rp_uuid, inv)
        inv = self._get_provider_inventory(rp_uuid)
        # Check inventories is updated to ratios
        for rc, ratio in ratios.items():
            self.assertIn(rc, inv)
            self.assertIn('allocation_ratio', inv[rc])
            self.assertEqual(ratio, inv[rc]['allocation_ratio'],
                             'Unexpected allocation ratio for %s' % rc)

        # Make sure xxx_allocation_ratio is None by default
        self.assertIsNone(CONF.cpu_allocation_ratio)
        self.assertIsNone(CONF.ram_allocation_ratio)
        self.assertIsNone(CONF.disk_allocation_ratio)
        # run the RT.update_available_resource periodic
        rt.update_available_resource(ctxt, 'fake-host')
        # assert the allocation ratios are not overwritten from config
        inv = self._get_provider_inventory(rp_uuid)
        for rc, ratio in ratios.items():
            self.assertIn(rc, inv)
            self.assertIn('allocation_ratio', inv[rc])
            self.assertEqual(ratio, inv[rc]['allocation_ratio'],
                             'Unexpected allocation ratio for %s' % rc)

        # set the CONF.*_allocation_ratio
        self.flags(cpu_allocation_ratio=15.9)
        self.flags(ram_allocation_ratio=1.4)
        self.flags(disk_allocation_ratio=0.9)

        # run the RT.update_available_resource periodic
        rt.update_available_resource(ctxt, 'fake-host')
        inv = self._get_provider_inventory(rp_uuid)
        ratios = {
            'VCPU': CONF.cpu_allocation_ratio,
            'MEMORY_MB': CONF.ram_allocation_ratio,
            'DISK_GB': CONF.disk_allocation_ratio
        }
        # assert that the config overwrites what was set via the placement API.
        for rc, ratio in ratios.items():
            self.assertIn(rc, inv)
            self.assertIn('allocation_ratio', inv[rc])
            self.assertEqual(ratio, inv[rc]['allocation_ratio'],
                             'Unexpected allocation ratio for %s' % rc)

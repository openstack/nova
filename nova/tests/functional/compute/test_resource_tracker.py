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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import power_state
from nova.compute import resource_tracker
from nova.compute import task_states
from nova.compute import vm_states
from nova import conf
from nova import context
from nova import objects
from nova import rc_fields as fields
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import test_report_client as test_base
from nova.virt import driver as virt_driver


CONF = conf.CONF
VCPU = fields.ResourceClass.VCPU
MEMORY_MB = fields.ResourceClass.MEMORY_MB
DISK_GB = fields.ResourceClass.DISK_GB
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
        self.rt.scheduler_client.reportclient = client
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
        self.useFixture(nova_fixtures.PlacementFixture())
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
        with self.rt.instance_claim(self.ctx, inst, cn1_nodename):
            _assert_stats()

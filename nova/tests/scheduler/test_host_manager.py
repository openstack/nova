# Copyright (c) 2011 OpenStack, LLC
# All Rights Reserved.
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
Tests For HostManager
"""


from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.openstack.common import timeutils
from nova.scheduler import host_manager
from nova import test
from nova.tests import matchers
from nova.tests.scheduler import fakes


class ComputeFilterClass1(object):
    def host_passes(self, *args, **kwargs):
        pass


class ComputeFilterClass2(object):
    def host_passes(self, *args, **kwargs):
        pass


class HostManagerTestCase(test.TestCase):
    """Test case for HostManager class"""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()

    def tearDown(self):
        timeutils.clear_time_override()
        super(HostManagerTestCase, self).tearDown()

    def test_choose_host_filters_not_found(self):
        self.flags(scheduler_default_filters='ComputeFilterClass3')
        self.host_manager.filter_classes = [ComputeFilterClass1,
                ComputeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(scheduler_default_filters=['ComputeFilterClass2'])
        self.host_manager.filter_classes = [ComputeFilterClass1,
                ComputeFilterClass2]

        # Test we returns 1 correct function
        filter_classes = self.host_manager._choose_host_filters(None)
        self.assertEqual(len(filter_classes), 1)
        self.assertEqual(filter_classes[0].__name__, 'ComputeFilterClass2')

    def test_get_filtered_hosts(self):
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1']
        fake_classes = 'fake_classes'
        fake_properties = {'moo': 1, 'cow': 2}
        expected_hosts = set(fake_hosts)
        fake_result = 'fake_result'

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')

        self.host_manager._choose_host_filters(None).AndReturn(fake_classes)
        self.host_manager.filter_handler.get_filtered_objects(fake_classes,
                expected_hosts, fake_properties).AndReturn(fake_result)

        self.mox.ReplayAll()

        result = self.host_manager. get_filtered_hosts(fake_hosts,
                fake_properties)
        self.assertEqual(result, fake_result)

    def test_get_filtered_hosts_with_specificed_filters(self):
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1']
        fake_classes = 'fake_classes'
        fake_properties = {'moo': 1, 'cow': 2}
        fake_filters = 'fake_filters'
        expected_hosts = set(fake_hosts)
        fake_result = 'fake_result'

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')

        self.host_manager._choose_host_filters(fake_filters).AndReturn(
                fake_classes)
        self.host_manager.filter_handler.get_filtered_objects(fake_classes,
                expected_hosts, fake_properties).AndReturn(fake_result)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(fake_hosts,
                fake_properties, filter_class_names=fake_filters)
        self.assertEqual(result, fake_result)

    def test_get_filtered_hosts_with_ignore(self):
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1', 'fake_host3', 'fake_host4']
        fake_classes = 'fake_classes'
        fake_properties = {'ignore_hosts': ['fake_host1', 'fake_host3',
            'fake_host5']}
        expected_hosts = set(['fake_host2', 'fake_host4'])
        fake_result = 'fake_result'

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')

        self.host_manager._choose_host_filters(None).AndReturn(fake_classes)
        self.host_manager.filter_handler.get_filtered_objects(fake_classes,
                expected_hosts, fake_properties).AndReturn(fake_result)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(fake_hosts,
                fake_properties)
        self.assertEqual(result, fake_result)

    def test_get_filtered_hosts_with_force_hosts(self):
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1', 'fake_host3', 'fake_host4']
        fake_classes = 'fake_classes'
        fake_properties = {'force_hosts': ['fake_host1', 'fake_host3',
            'fake_host5']}
        expected_hosts = set(['fake_host1', 'fake_host3'])
        fake_result = 'fake_result'

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')

        self.host_manager._choose_host_filters(None).AndReturn(fake_classes)
        self.host_manager.filter_handler.get_filtered_objects(fake_classes,
                expected_hosts, fake_properties).AndReturn(fake_result)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(fake_hosts,
                fake_properties)
        self.assertEqual(result, fake_result)

    def test_get_filtered_hosts_with_no_matching_force_hosts(self):
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1', 'fake_host3', 'fake_host4']
        fake_classes = 'fake_classes'
        fake_properties = {'force_hosts': ['fake_host5', 'fake_host6']}
        expected_result = []

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        # Make sure this is not called.
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')

        self.host_manager._choose_host_filters(None).AndReturn(fake_classes)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(fake_hosts,
                fake_properties)
        self.assertEqual(result, expected_result)

    def test_get_filtered_hosts_with_ignore_and_force(self):
        """Ensure ignore_hosts processed before force_hosts in host filters"""
        fake_hosts = ['fake_host1', 'fake_host2', 'fake_host1',
                'fake_host1', 'fake_host3', 'fake_host4']
        fake_classes = 'fake_classes'
        fake_properties = {'force_hosts': ['fake_host3', 'fake_host1'],
                           'ignore_hosts': ['fake_host1']}
        expected_hosts = set(['fake_host3'])
        fake_result = 'fake_result'

        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')
        # Make sure this is not called.
        self.mox.StubOutWithMock(self.host_manager.filter_handler,
                'get_filtered_objects')
        self.host_manager.filter_handler.get_filtered_objects(fake_classes,
                expected_hosts, fake_properties).AndReturn(fake_result)

        self.host_manager._choose_host_filters(None).AndReturn(fake_classes)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(fake_hosts,
                fake_properties)
        self.assertEqual(result, fake_result)

    def test_update_service_capabilities(self):
        service_states = self.host_manager.service_states
        self.assertEqual(len(service_states.keys()), 0)
        self.mox.StubOutWithMock(timeutils, 'utcnow')
        timeutils.utcnow().AndReturn(31337)
        timeutils.utcnow().AndReturn(31339)

        host1_compute_capabs = dict(free_memory=1234, host_memory=5678,
                timestamp=1, hypervisor_hostname='node1')
        host2_compute_capabs = dict(free_memory=8756, timestamp=1,
                hypervisor_hostname='node2')

        self.mox.ReplayAll()
        self.host_manager.update_service_capabilities('compute', 'host1',
                host1_compute_capabs)
        self.host_manager.update_service_capabilities('compute', 'host2',
                host2_compute_capabs)

        # Make sure original dictionary wasn't copied
        self.assertEqual(host1_compute_capabs['timestamp'], 1)

        host1_compute_capabs['timestamp'] = 31337
        host2_compute_capabs['timestamp'] = 31339

        expected = {('host1', 'node1'): host1_compute_capabs,
                    ('host2', 'node2'): host2_compute_capabs}
        self.assertThat(service_states, matchers.DictMatches(expected))

    def test_update_service_capabilities_node_key(self):
        service_states = self.host_manager.service_states
        self.assertThat(service_states, matchers.DictMatches({}))

        host1_cap = {'hypervisor_hostname': 'host1-hvhn'}
        host2_cap = {}

        timeutils.set_time_override(31337)
        self.host_manager.update_service_capabilities('compute', 'host1',
                host1_cap)
        timeutils.set_time_override(31338)
        self.host_manager.update_service_capabilities('compute', 'host2',
                host2_cap)
        host1_cap['timestamp'] = 31337
        host2_cap['timestamp'] = 31338
        expected = {('host1', 'host1-hvhn'): host1_cap,
                    ('host2', None): host2_cap}
        self.assertThat(service_states, matchers.DictMatches(expected))

    def test_get_all_host_states(self):

        context = 'fake_context'

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        self.mox.StubOutWithMock(host_manager.LOG, 'warn')

        db.compute_node_get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # Invalid service
        host_manager.LOG.warn("No service for compute ID 5")

        self.mox.ReplayAll()
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map

        self.assertEqual(len(host_states_map), 4)
        # Check that .service is set properly
        for i in xrange(4):
            compute_node = fakes.COMPUTE_NODES[i]
            host = compute_node['service']['host']
            node = compute_node['hypervisor_hostname']
            state_key = (host, node)
            self.assertEqual(host_states_map[state_key].service,
                    compute_node['service'])
        self.assertEqual(host_states_map[('host1', 'node1')].free_ram_mb,
                         512)
        # 511GB
        self.assertEqual(host_states_map[('host1', 'node1')].free_disk_mb,
                         524288)
        self.assertEqual(host_states_map[('host2', 'node2')].free_ram_mb,
                         1024)
        # 1023GB
        self.assertEqual(host_states_map[('host2', 'node2')].free_disk_mb,
                         1048576)
        self.assertEqual(host_states_map[('host3', 'node3')].free_ram_mb,
                         3072)
        # 3071GB
        self.assertEqual(host_states_map[('host3', 'node3')].free_disk_mb,
                         3145728)
        self.assertEqual(host_states_map[('host4', 'node4')].free_ram_mb,
                         8192)
        # 8191GB
        self.assertEqual(host_states_map[('host4', 'node4')].free_disk_mb,
                         8388608)


class HostStateTestCase(test.TestCase):
    """Test case for HostState class"""

    # update_from_compute_node() and consume_from_instance() are tested
    # in HostManagerTestCase.test_get_all_host_states()

    def test_stat_consumption_from_compute_node(self):
        stats = [
            dict(key='num_instances', value='5'),
            dict(key='num_proj_12345', value='3'),
            dict(key='num_proj_23456', value='1'),
            dict(key='num_vm_%s' % vm_states.BUILDING, value='2'),
            dict(key='num_vm_%s' % vm_states.SUSPENDED, value='1'),
            dict(key='num_task_%s' % task_states.RESIZE_MIGRATING, value='1'),
            dict(key='num_task_%s' % task_states.MIGRATING, value='2'),
            dict(key='num_os_type_linux', value='4'),
            dict(key='num_os_type_windoze', value='1'),
            dict(key='io_workload', value='42'),
        ]
        compute = dict(stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
                       local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
                       updated_at=None)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)

        self.assertEqual(5, host.num_instances)
        self.assertEqual(3, host.num_instances_by_project['12345'])
        self.assertEqual(1, host.num_instances_by_project['23456'])
        self.assertEqual(2, host.vm_states[vm_states.BUILDING])
        self.assertEqual(1, host.vm_states[vm_states.SUSPENDED])
        self.assertEqual(1, host.task_states[task_states.RESIZE_MIGRATING])
        self.assertEqual(2, host.task_states[task_states.MIGRATING])
        self.assertEqual(4, host.num_instances_by_os_type['linux'])
        self.assertEqual(1, host.num_instances_by_os_type['windoze'])
        self.assertEqual(42, host.num_io_ops)

    def test_stat_consumption_from_instance(self):
        host = host_manager.HostState("fakehost", "fakenode")

        instance = dict(root_gb=0, ephemeral_gb=0, memory_mb=0, vcpus=0,
                        project_id='12345', vm_state=vm_states.BUILDING,
                        task_state=task_states.SCHEDULING, os_type='Linux')
        host.consume_from_instance(instance)

        instance = dict(root_gb=0, ephemeral_gb=0, memory_mb=0, vcpus=0,
                        project_id='12345', vm_state=vm_states.PAUSED,
                        task_state=None, os_type='Linux')
        host.consume_from_instance(instance)

        self.assertEqual(2, host.num_instances)
        self.assertEqual(2, host.num_instances_by_project['12345'])
        self.assertEqual(1, host.vm_states[vm_states.BUILDING])
        self.assertEqual(1, host.vm_states[vm_states.PAUSED])
        self.assertEqual(1, host.task_states[task_states.SCHEDULING])
        self.assertEqual(1, host.task_states[None])
        self.assertEqual(2, host.num_instances_by_os_type['Linux'])
        self.assertEqual(1, host.num_io_ops)

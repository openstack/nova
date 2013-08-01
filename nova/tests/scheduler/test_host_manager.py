# Copyright (c) 2011 OpenStack Foundation
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
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova import test
from nova.tests import matchers
from nova.tests.scheduler import fakes


class FakeFilterClass1(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class HostManagerTestCase(test.NoDBTestCase):
    """Test case for HostManager class."""

    def setUp(self):
        super(HostManagerTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x,
                'fake-node') for x in xrange(1, 5)]
        self.fake_hosts += [host_manager.HostState('fake_multihost',
                'fake-node%s' % x) for x in xrange(1, 5)]
        self.addCleanup(timeutils.clear_time_override)

    def test_choose_host_filters_not_found(self):
        self.flags(scheduler_default_filters='FakeFilterClass3')
        self.host_manager.filter_classes = [FakeFilterClass1,
                FakeFilterClass2]
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(scheduler_default_filters=['FakeFilterClass2'])
        self.host_manager.filter_classes = [FakeFilterClass1,
                FakeFilterClass2]

        # Test we returns 1 correct function
        filter_classes = self.host_manager._choose_host_filters(None)
        self.assertEqual(len(filter_classes), 1)
        self.assertEqual(filter_classes[0].__name__, 'FakeFilterClass2')

    def _mock_get_filtered_hosts(self, info, specified_filters=None):
        self.mox.StubOutWithMock(self.host_manager, '_choose_host_filters')

        info['got_objs'] = []
        info['got_fprops'] = []

        def fake_filter_one(_self, obj, filter_props):
            info['got_objs'].append(obj)
            info['got_fprops'].append(filter_props)
            return True

        self.stubs.Set(FakeFilterClass1, '_filter_one', fake_filter_one)
        self.host_manager._choose_host_filters(specified_filters).AndReturn(
                [FakeFilterClass1])

    def _verify_result(self, info, result, filters=True):
        for x in info['got_fprops']:
            self.assertEqual(x, info['expected_fprops'])
        if filters:
            self.assertEqual(set(info['expected_objs']), set(info['got_objs']))
        self.assertEqual(set(info['expected_objs']), set(result))

    def test_get_filtered_hosts(self):
        fake_properties = {'moo': 1, 'cow': 2}

        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()
        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_specificed_filters(self):
        fake_properties = {'moo': 1, 'cow': 2}

        specified_filters = ['FakeFilterClass1', 'FakeFilterClass2']
        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info, specified_filters)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties, filter_class_names=specified_filters)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_ignore(self):
        fake_properties = {'ignore_hosts': ['fake_host1', 'fake_host3',
            'fake_host5', 'fake_multihost']}

        # [1] and [3] are host2 and host4
        info = {'expected_objs': [self.fake_hosts[1], self.fake_hosts[3]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_force_hosts(self):
        fake_properties = {'force_hosts': ['fake_host1', 'fake_host3',
            'fake_host5']}

        # [0] and [2] are host1 and host3
        info = {'expected_objs': [self.fake_hosts[0], self.fake_hosts[2]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_no_matching_force_hosts(self):
        fake_properties = {'force_hosts': ['fake_host5', 'fake_host6']}

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_and_force_hosts(self):
        # Ensure ignore_hosts processed before force_hosts in host filters.
        fake_properties = {'force_hosts': ['fake_host3', 'fake_host1'],
                           'ignore_hosts': ['fake_host1']}

        # only fake_host3 should be left.
        info = {'expected_objs': [self.fake_hosts[2]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_host_and_many_nodes(self):
        # Ensure all nodes returned for a host with many nodes
        fake_properties = {'force_hosts': ['fake_multihost']}

        info = {'expected_objs': [self.fake_hosts[4], self.fake_hosts[5],
                                  self.fake_hosts[6], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_nodes(self):
        fake_properties = {'force_nodes': ['fake-node2', 'fake-node4',
                                           'fake-node9']}

        # [5] is fake-node2, [7] is fake-node4
        info = {'expected_objs': [self.fake_hosts[5], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_hosts_and_nodes(self):
        # Ensure only overlapping results if both force host and node
        fake_properties = {'force_hosts': ['fake_host1', 'fake_multihost'],
                           'force_nodes': ['fake-node2', 'fake-node9']}

        # [5] is fake-node2
        info = {'expected_objs': [self.fake_hosts[5]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_hosts_and_wrong_nodes(self):
        # Ensure non-overlapping force_node and force_host yield no result
        fake_properties = {'force_hosts': ['fake_multihost'],
                           'force_nodes': ['fake-node']}

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_hosts_and_force_nodes(self):
        # Ensure ignore_hosts can coexist with force_nodes
        fake_properties = {'force_nodes': ['fake-node4', 'fake-node2'],
                           'ignore_hosts': ['fake_host1', 'fake_host2']}

        info = {'expected_objs': [self.fake_hosts[5], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_hosts_and_force_same_nodes(self):
        # Ensure ignore_hosts is processed before force_nodes
        fake_properties = {'force_nodes': ['fake_node4', 'fake_node2'],
                           'ignore_hosts': ['fake_multihost']}

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        self.mox.ReplayAll()

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

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


class HostManagerChangedNodesTestCase(test.NoDBTestCase):
    """Test case for HostManager class."""

    def setUp(self):
        super(HostManagerChangedNodesTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [
              host_manager.HostState('host1', 'node1'),
              host_manager.HostState('host2', 'node2'),
              host_manager.HostState('host3', 'node3'),
              host_manager.HostState('host4', 'node4')
            ]
        self.addCleanup(timeutils.clear_time_override)

    def test_get_all_host_states(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        db.compute_node_get_all(context).AndReturn(fakes.COMPUTE_NODES)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 4)

    def test_get_all_host_states_after_delete_one(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        # all nodes active for first call
        db.compute_node_get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove node4 for second call
        running_nodes = [n for n in fakes.COMPUTE_NODES
                         if n.get('hypervisor_hostname') != 'node4']
        db.compute_node_get_all(context).AndReturn(running_nodes)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 3)

    def test_get_all_host_states_after_delete_all(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(db, 'compute_node_get_all')
        # all nodes active for first call
        db.compute_node_get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove all nodes for second call
        db.compute_node_get_all(context).AndReturn([])
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 0)


class HostStateTestCase(test.NoDBTestCase):
    """Test case for HostState class."""

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
        compute = dict(stats=stats, memory_mb=1, free_disk_gb=0, local_gb=0,
                       local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
                       updated_at=None, host_ip='127.0.0.1',
                       hypervisor_type='htype', hypervisor_version='1.1',
                       hypervisor_hostname='hostname', cpu_info='cpu_info',
                       supported_instances='{}')

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
        self.assertEqual(10, len(host.stats))

        self.assertEqual('127.0.0.1', host.host_ip)
        self.assertEqual('htype', host.hypervisor_type)
        self.assertEqual('1.1', host.hypervisor_version)
        self.assertEqual('hostname', host.hypervisor_hostname)
        self.assertEqual('cpu_info', host.cpu_info)
        self.assertEqual({}, host.supported_instances)

    def test_stat_consumption_from_compute_node_non_pci(self):
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
                       updated_at=None, host_ip='127.0.0.1')

        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)
        self.assertEqual(None, host.pci_stats)

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

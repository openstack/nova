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

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import six

from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit.scheduler import fakes
from nova import utils

CONF = cfg.CONF
CONF.import_opt('compute_topic', 'nova.compute.rpcapi')


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
        self.flags(scheduler_available_filters=['%s.%s' % (__name__, cls) for
                                                cls in ['FakeFilterClass1',
                                                        'FakeFilterClass2']])
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x,
                'fake-node') for x in xrange(1, 5)]
        self.fake_hosts += [host_manager.HostState('fake_multihost',
                'fake-node%s' % x) for x in xrange(1, 5)]

    def test_choose_host_filters_not_found(self):
        self.flags(scheduler_default_filters='FakeFilterClass3')
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                self.host_manager._choose_host_filters, None)

    def test_choose_host_filters(self):
        self.flags(scheduler_default_filters=['FakeFilterClass2'])
        # Test we returns 1 correct function
        host_filters = self.host_manager._choose_host_filters(None)
        self.assertEqual(len(host_filters), 1)
        self.assertEqual(host_filters[0].__class__.__name__,
                         'FakeFilterClass2')

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
                [FakeFilterClass1()])

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

    def test_get_filtered_hosts_with_specified_filters(self):
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

    def test_get_all_host_states(self):

        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_topic')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        self.mox.StubOutWithMock(host_manager.LOG, 'warning')

        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # node 3 host physical disk space is greater than database
        host_manager.LOG.warning("Host %(hostname)s has more disk space "
                                 "than database expected (%(physical)sgb >"
                                 " %(database)sgb)",
                                 {'physical': 3333, 'database': 3072,
                                  'hostname': 'node3'})
        # Invalid service
        host_manager.LOG.warning("No service record found for host %(host)s "
                                 "on %(topic)s topic",
                                 {'host': 'fake', 'topic': CONF.compute_topic})
        self.mox.ReplayAll()
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map

        self.assertEqual(len(host_states_map), 4)
        # Check that .service is set properly
        for i in xrange(4):
            compute_node = fakes.COMPUTE_NODES[i]
            host = compute_node['host']
            node = compute_node['hypervisor_hostname']
            state_key = (host, node)
            self.assertEqual(host_states_map[state_key].service,
                    obj_base.obj_to_primitive(fakes.get_service_by_host(host)))
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
        self.assertThat(
                objects.NUMATopology.obj_from_db_obj(
                        host_states_map[('host3', 'node3')].numa_topology
                    )._to_dict(),
                matchers.DictMatches(fakes.NUMA_TOPOLOGY._to_dict()))
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

    def test_get_all_host_states(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_topic')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 4)

    def test_get_all_host_states_after_delete_one(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_topic')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        # all nodes active for first call
        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove node4 for second call
        running_nodes = [n for n in fakes.COMPUTE_NODES
                         if n.get('hypervisor_hostname') != 'node4']
        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(running_nodes)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 3)

    def test_get_all_host_states_after_delete_all(self):
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_topic')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        # all nodes active for first call
        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove all nodes for second call
        objects.ServiceList.get_by_topic(
            context, CONF.compute_topic).AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn([])
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
        stats = {
            'num_instances': '5',
            'num_proj_12345': '3',
            'num_proj_23456': '1',
            'num_vm_%s' % vm_states.BUILDING: '2',
            'num_vm_%s' % vm_states.SUSPENDED: '1',
            'num_task_%s' % task_states.RESIZE_MIGRATING: '1',
            'num_task_%s' % task_states.MIGRATING: '2',
            'num_os_type_linux': '4',
            'num_os_type_windoze': '1',
            'io_workload': '42',
        }

        hyper_ver_int = utils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=1, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)

        self.assertEqual(5, host.num_instances)
        self.assertEqual(42, host.num_io_ops)
        self.assertEqual(10, len(host.stats))

        self.assertEqual('127.0.0.1', str(host.host_ip))
        self.assertEqual('htype', host.hypervisor_type)
        self.assertEqual('hostname', host.hypervisor_hostname)
        self.assertEqual('cpu_info', host.cpu_info)
        self.assertEqual([], host.supported_instances)
        self.assertEqual(hyper_ver_int, host.hypervisor_version)

    def test_stat_consumption_from_compute_node_non_pci(self):
        stats = {
            'num_instances': '5',
            'num_proj_12345': '3',
            'num_proj_23456': '1',
            'num_vm_%s' % vm_states.BUILDING: '2',
            'num_vm_%s' % vm_states.SUSPENDED: '1',
            'num_task_%s' % task_states.RESIZE_MIGRATING: '1',
            'num_task_%s' % task_states.MIGRATING: '2',
            'num_os_type_linux': '4',
            'num_os_type_windoze': '1',
            'io_workload': '42',
        }

        hyper_ver_int = utils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)
        self.assertIsNone(host.pci_stats)
        self.assertEqual(hyper_ver_int, host.hypervisor_version)

    def test_stat_consumption_from_compute_node_rescue_unshelving(self):
        stats = {
            'num_instances': '5',
            'num_proj_12345': '3',
            'num_proj_23456': '1',
            'num_vm_%s' % vm_states.BUILDING: '2',
            'num_vm_%s' % vm_states.SUSPENDED: '1',
            'num_task_%s' % task_states.UNSHELVING: '1',
            'num_task_%s' % task_states.RESCUING: '2',
            'num_os_type_linux': '4',
            'num_os_type_windoze': '1',
            'io_workload': '42',
        }

        hyper_ver_int = utils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)

        self.assertEqual(5, host.num_instances)
        self.assertEqual(42, host.num_io_ops)
        self.assertEqual(10, len(host.stats))

        self.assertIsNone(host.pci_stats)
        self.assertEqual(hyper_ver_int, host.hypervisor_version)

    @mock.patch('nova.virt.hardware.get_host_numa_usage_from_instance')
    def test_stat_consumption_from_instance(self, numa_usage_mock):
        numa_usage_mock.return_value = 'fake-consumed-once'
        host = host_manager.HostState("fakehost", "fakenode")

        instance = dict(root_gb=0, ephemeral_gb=0, memory_mb=0, vcpus=0,
                        project_id='12345', vm_state=vm_states.BUILDING,
                        task_state=task_states.SCHEDULING, os_type='Linux',
                        uuid='fake-uuid', numa_topology=None)
        host.consume_from_instance(instance)
        numa_usage_mock.assert_called_once_with(host, instance)
        self.assertEqual('fake-consumed-once', host.numa_topology)

        numa_usage_mock.return_value = 'fake-consumed-twice'
        instance = dict(root_gb=0, ephemeral_gb=0, memory_mb=0, vcpus=0,
                        project_id='12345', vm_state=vm_states.PAUSED,
                        task_state=None, os_type='Linux',
                        uuid='fake-uuid', numa_topology=None)
        host.consume_from_instance(instance)

        self.assertEqual(2, host.num_instances)
        self.assertEqual(1, host.num_io_ops)
        self.assertEqual(2, numa_usage_mock.call_count)
        self.assertEqual(((host, instance),), numa_usage_mock.call_args)
        self.assertEqual('fake-consumed-twice', host.numa_topology)

    def test_resources_consumption_from_compute_node(self):
        metrics = [
            dict(name='res1',
                 value=1.0,
                 source='source1',
                 timestamp=None),
            dict(name='res2',
                 value="string2",
                 source='source2',
                 timestamp=None),
        ]
        hyper_ver_int = utils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            metrics=jsonutils.dumps(metrics),
            memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int,
            numa_topology=fakes.NUMA_TOPOLOGY._to_json(),
            stats=None, pci_device_pools=None)
        host = host_manager.HostState("fakehost", "fakenode")
        host.update_from_compute_node(compute)

        self.assertEqual(len(host.metrics), 2)
        self.assertEqual(set(['res1', 'res2']), set(host.metrics.keys()))
        self.assertEqual(1.0, host.metrics['res1'].value)
        self.assertEqual('source1', host.metrics['res1'].source)
        self.assertEqual('string2', host.metrics['res2'].value)
        self.assertEqual('source2', host.metrics['res2'].source)
        self.assertIsInstance(host.numa_topology, six.string_types)

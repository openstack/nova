# Copyright (c) 2014 OpenStack Foundation
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
Tests For IronicHostManager
"""

import mock

from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova.scheduler import ironic_host_manager
from nova import test
from nova.tests.unit.scheduler import ironic_fakes


class FakeFilterClass1(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class IronicHostManagerTestCase(test.NoDBTestCase):
    """Test case for IronicHostManager class."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(IronicHostManagerTestCase, self).setUp()
        self.host_manager = ironic_host_manager.IronicHostManager()

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_manager_public_api_signatures(self, mock_init_aggs,
                                           mock_init_inst):
        self.assertPublicAPISignatures(host_manager.HostManager(),
                                       self.host_manager)

    def test_state_public_api_signatures(self):
        self.assertPublicAPISignatures(
            host_manager.HostState("dummy",
                                   "dummy"),
            ironic_host_manager.IronicNodeState("dummy",
                                                "dummy")
        )

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states(self, mock_get_by_host, mock_get_all,
                                 mock_get_by_binary):
        mock_get_all.return_value = ironic_fakes.COMPUTE_NODES
        mock_get_by_binary.return_value = ironic_fakes.SERVICES
        context = 'fake_context'

        self.host_manager.get_all_host_states(context)
        self.assertEqual(0, mock_get_by_host.call_count)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 4)

        for i in range(4):
            compute_node = ironic_fakes.COMPUTE_NODES[i]
            host = compute_node.host
            node = compute_node.hypervisor_hostname
            state_key = (host, node)
            self.assertEqual(host_states_map[state_key].service,
                             obj_base.obj_to_primitive(
                                 ironic_fakes.get_service_by_host(host)))
            self.assertEqual(compute_node.stats,
                             host_states_map[state_key].stats)
            self.assertEqual(compute_node.free_ram_mb,
                             host_states_map[state_key].free_ram_mb)
            self.assertEqual(compute_node.free_disk_gb * 1024,
                             host_states_map[state_key].free_disk_mb)


class IronicHostManagerChangedNodesTestCase(test.NoDBTestCase):
    """Test case for IronicHostManager class."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(IronicHostManagerChangedNodesTestCase, self).setUp()
        self.host_manager = ironic_host_manager.IronicHostManager()
        ironic_driver = "nova.virt.ironic.driver.IronicDriver"
        supported_instances = [
            objects.HVSpec.from_list(["i386", "baremetal", "baremetal"])]
        self.compute_node = objects.ComputeNode(
            id=1, local_gb=10, memory_mb=1024, vcpus=1,
            vcpus_used=0, local_gb_used=0, memory_mb_used=0,
            updated_at=None, cpu_info='baremetal cpu',
            stats=dict(
                ironic_driver=ironic_driver,
                cpu_arch='i386'),
            supported_hv_specs=supported_instances,
            free_disk_gb=10, free_ram_mb=1024,
            hypervisor_type='ironic',
            hypervisor_version=1,
            hypervisor_hostname='fake_host',
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0)

    @mock.patch.object(ironic_host_manager.IronicNodeState, '__init__')
    def test_create_ironic_node_state(self, init_mock):
        init_mock.return_value = None
        compute = objects.ComputeNode(**{'hypervisor_type': 'ironic'})
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute=compute)
        self.assertIs(ironic_host_manager.IronicNodeState, type(host_state))

    @mock.patch.object(host_manager.HostState, '__init__')
    def test_create_non_ironic_host_state(self, init_mock):
        init_mock.return_value = None
        compute = objects.ComputeNode(**{'cpu_info': 'other cpu'})
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node',
                                                      compute=compute)
        self.assertIs(host_manager.HostState, type(host_state))

    @mock.patch.object(host_manager.HostState, '__init__')
    def test_create_host_state_null_compute(self, init_mock):
        init_mock.return_value = None
        host_state = self.host_manager.host_state_cls('fake-host', 'fake-node')
        self.assertIs(host_manager.HostState, type(host_state))

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    def test_get_all_host_states_after_delete_one(self, mock_get_all,
                                                  mock_get_by_binary):
        getter = (lambda n: n.hypervisor_hostname
                  if 'hypervisor_hostname' in n else None)
        running_nodes = [n for n in ironic_fakes.COMPUTE_NODES
                         if getter(n) != 'node4uuid']

        mock_get_all.side_effect = [
            ironic_fakes.COMPUTE_NODES, running_nodes]
        mock_get_by_binary.side_effect = [
            ironic_fakes.SERVICES, ironic_fakes.SERVICES]
        context = 'fake_context'

        # first call: all nodes
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(4, len(host_states_map))

        # second call: just running nodes
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(3, len(host_states_map))

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    def test_get_all_host_states_after_delete_all(self, mock_get_all,
                                                  mock_get_by_binary):
        mock_get_all.side_effect = [
            ironic_fakes.COMPUTE_NODES, []]
        mock_get_by_binary.side_effect = [
            ironic_fakes.SERVICES, ironic_fakes.SERVICES]
        context = 'fake_context'

        # first call: all nodes
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 4)

        # second call: no nodes
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 0)

    def test_update_from_compute_node(self):
        host = ironic_host_manager.IronicNodeState("fakehost", "fakenode")
        host.update(compute=self.compute_node)

        self.assertEqual(1024, host.free_ram_mb)
        self.assertEqual(1024, host.total_usable_ram_mb)
        self.assertEqual(10240, host.free_disk_mb)
        self.assertEqual(1, host.vcpus_total)
        self.assertEqual(0, host.vcpus_used)
        self.assertEqual(self.compute_node.stats, host.stats)
        self.assertEqual('ironic', host.hypervisor_type)
        self.assertEqual(1, host.hypervisor_version)
        self.assertEqual('fake_host', host.hypervisor_hostname)

    def test_consume_identical_instance_from_compute(self):
        host = ironic_host_manager.IronicNodeState("fakehost", "fakenode")
        host.update(compute=self.compute_node)

        self.assertIsNone(host.updated)
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=10, ephemeral_gb=0, memory_mb=1024,
                                  vcpus=1),
            uuid='fake-uuid')
        host.consume_from_request(spec_obj)

        self.assertEqual(1, host.vcpus_used)
        self.assertEqual(0, host.free_ram_mb)
        self.assertEqual(0, host.free_disk_mb)
        self.assertIsNotNone(host.updated)

    def test_consume_larger_instance_from_compute(self):
        host = ironic_host_manager.IronicNodeState("fakehost", "fakenode")
        host.update(compute=self.compute_node)

        self.assertIsNone(host.updated)
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=20, ephemeral_gb=0, memory_mb=2048,
                                  vcpus=2))
        host.consume_from_request(spec_obj)

        self.assertEqual(1, host.vcpus_used)
        self.assertEqual(0, host.free_ram_mb)
        self.assertEqual(0, host.free_disk_mb)
        self.assertIsNotNone(host.updated)

    def test_consume_smaller_instance_from_compute(self):
        host = ironic_host_manager.IronicNodeState("fakehost", "fakenode")
        host.update(compute=self.compute_node)

        self.assertIsNone(host.updated)
        spec_obj = objects.RequestSpec(
            flavor=objects.Flavor(root_gb=5, ephemeral_gb=0, memory_mb=512,
                                  vcpus=1))
        host.consume_from_request(spec_obj)

        self.assertEqual(1, host.vcpus_used)
        self.assertEqual(0, host.free_ram_mb)
        self.assertEqual(0, host.free_disk_mb)
        self.assertIsNotNone(host.updated)


class IronicHostManagerTestFilters(test.NoDBTestCase):
    """Test filters work for IronicHostManager."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(IronicHostManagerTestFilters, self).setUp()
        self.flags(scheduler_available_filters=['%s.%s' % (__name__, cls) for
                                                cls in ['FakeFilterClass1',
                                                        'FakeFilterClass2']])
        self.flags(scheduler_default_filters=['FakeFilterClass1'])
        self.flags(baremetal_scheduler_default_filters=['FakeFilterClass2'])
        self.host_manager = ironic_host_manager.IronicHostManager()
        self.fake_hosts = [ironic_host_manager.IronicNodeState(
                'fake_host%s' % x, 'fake-node') for x in range(1, 5)]
        self.fake_hosts += [ironic_host_manager.IronicNodeState(
                'fake_multihost', 'fake-node%s' % x) for x in range(1, 5)]

    def test_default_filters(self):
        default_filters = self.host_manager.default_filters
        self.assertEqual(1, len(default_filters))
        self.assertIsInstance(default_filters[0], FakeFilterClass1)

    def test_choose_host_filters_not_found(self):
        self.assertRaises(exception.SchedulerHostFilterNotFound,
                          self.host_manager._choose_host_filters,
                          'FakeFilterClass3')

    def test_choose_host_filters(self):
        # Test we return 1 correct filter object
        host_filters = self.host_manager._choose_host_filters(
                ['FakeFilterClass2'])
        self.assertEqual(1, len(host_filters))
        self.assertIsInstance(host_filters[0], FakeFilterClass2)

    def test_host_manager_default_filters(self):
        default_filters = self.host_manager.default_filters
        self.assertEqual(1, len(default_filters))
        self.assertIsInstance(default_filters[0], FakeFilterClass1)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_host_manager_default_filters_uses_baremetal(self, mock_init_agg,
                                                         mock_init_inst):
        self.flags(scheduler_use_baremetal_filters=True)
        host_manager = ironic_host_manager.IronicHostManager()

        # ensure the defaults come from baremetal_scheduler_default_filters
        # and not scheduler_default_filters
        default_filters = host_manager.default_filters
        self.assertEqual(1, len(default_filters))
        self.assertIsInstance(default_filters[0], FakeFilterClass2)

    def test_load_filters(self):
        # without scheduler_use_baremetal_filters
        filters = self.host_manager._load_filters()
        self.assertEqual(['FakeFilterClass1'], filters)

    def test_load_filters_baremetal(self):
        # with scheduler_use_baremetal_filters
        self.flags(scheduler_use_baremetal_filters=True)
        filters = self.host_manager._load_filters()
        self.assertEqual(['FakeFilterClass2'], filters)

    def _mock_get_filtered_hosts(self, info):
        info['got_objs'] = []
        info['got_fprops'] = []

        def fake_filter_one(_self, obj, filter_props):
            info['got_objs'].append(obj)
            info['got_fprops'].append(filter_props)
            return True

        self.stub_out(__name__ + '.FakeFilterClass1._filter_one',
                      fake_filter_one)

    def _verify_result(self, info, result, filters=True):
        for x in info['got_fprops']:
            self.assertEqual(x, info['expected_fprops'])
        if filters:
            self.assertEqual(set(info['expected_objs']), set(info['got_objs']))
        self.assertEqual(set(info['expected_objs']), set(result))

    def test_get_filtered_hosts(self):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=[],
            force_nodes=[])

        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    @mock.patch.object(FakeFilterClass2, '_filter_one', return_value=True)
    def test_get_filtered_hosts_with_specified_filters(self, mock_filter_one):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=[],
            force_nodes=[])

        specified_filters = ['FakeFilterClass1', 'FakeFilterClass2']
        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties, filter_class_names=specified_filters)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_ignore(self):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=['fake_host1', 'fake_host3',
                          'fake_host5', 'fake_multihost'],
            force_hosts=[],
            force_nodes=[])

        # [1] and [3] are host2 and host4
        info = {'expected_objs': [self.fake_hosts[1], self.fake_hosts[3]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_force_hosts(self):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=['fake_host1', 'fake_host3', 'fake_host5'],
            force_nodes=[])

        # [0] and [2] are host1 and host3
        info = {'expected_objs': [self.fake_hosts[0], self.fake_hosts[2]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_no_matching_force_hosts(self):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=['fake_host5', 'fake_host6'],
            force_nodes=[])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_and_force_hosts(self):
        # Ensure ignore_hosts processed before force_hosts in host filters.
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=['fake_host1'],
            force_hosts=['fake_host3', 'fake_host1'],
            force_nodes=[])

        # only fake_host3 should be left.
        info = {'expected_objs': [self.fake_hosts[2]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_host_and_many_nodes(self):
        # Ensure all nodes returned for a host with many nodes
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=['fake_multihost'],
            force_nodes=[])

        info = {'expected_objs': [self.fake_hosts[4], self.fake_hosts[5],
                                  self.fake_hosts[6], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_nodes(self):
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=[],
            force_nodes=['fake-node2', 'fake-node4', 'fake-node9'])

        # [5] is fake-node2, [7] is fake-node4
        info = {'expected_objs': [self.fake_hosts[5], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_hosts_and_nodes(self):
        # Ensure only overlapping results if both force host and node
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=['fake_host1', 'fake_multihost'],
            force_nodes=['fake-node2', 'fake-node9'])

        # [5] is fake-node2
        info = {'expected_objs': [self.fake_hosts[5]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_force_hosts_and_wrong_nodes(self):
        # Ensure non-overlapping force_node and force_host yield no result
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=[],
            force_hosts=['fake_multihost'],
            force_nodes=['fake-node'])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_hosts_and_force_nodes(self):
        # Ensure ignore_hosts can coexist with force_nodes
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=['fake_host1', 'fake_host2'],
            force_hosts=[],
            force_nodes=['fake-node4', 'fake-node2'])

        info = {'expected_objs': [self.fake_hosts[5], self.fake_hosts[7]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_hosts_and_force_same_nodes(self):
        # Ensure ignore_hosts is processed before force_nodes
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid',
            ignore_hosts=['fake_multihost'],
            force_hosts=[],
            force_nodes=['fake_node4', 'fake_node2'])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

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

import collections
import datetime

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import versionutils
import six

import nova
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.pci import stats as pci_stats
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_instance
from nova.tests.unit import matchers
from nova.tests.unit.scheduler import fakes

CONF = cfg.CONF
CONF.import_opt('scheduler_tracks_instance_changes',
                'nova.scheduler.host_manager')


class FakeFilterClass1(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class FakeFilterClass2(filters.BaseHostFilter):
    def host_passes(self, host_state, filter_properties):
        pass


class HostManagerTestCase(test.NoDBTestCase):
    """Test case for HostManager class."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(HostManagerTestCase, self).setUp()
        self.flags(scheduler_available_filters=['%s.%s' % (__name__, cls) for
                                                cls in ['FakeFilterClass1',
                                                        'FakeFilterClass2']])
        self.flags(scheduler_default_filters=['FakeFilterClass1'])
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x,
                'fake-node') for x in range(1, 5)]
        self.fake_hosts += [host_manager.HostState('fake_multihost',
                'fake-node%s' % x) for x in range(1, 5)]

        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    def test_load_filters(self):
        filters = self.host_manager._load_filters()
        self.assertEqual(filters, ['FakeFilterClass1'])

    @mock.patch.object(nova.objects.InstanceList, 'get_by_filters')
    @mock.patch.object(nova.objects.ComputeNodeList, 'get_all')
    def test_init_instance_info_batches(self, mock_get_all,
                                        mock_get_by_filters):
        cn_list = objects.ComputeNodeList()
        for num in range(22):
            host_name = 'host_%s' % num
            cn_list.objects.append(objects.ComputeNode(host=host_name))
        mock_get_all.return_value = cn_list
        self.host_manager._init_instance_info()
        self.assertEqual(mock_get_by_filters.call_count, 3)

    @mock.patch.object(nova.objects.InstanceList, 'get_by_filters')
    @mock.patch.object(nova.objects.ComputeNodeList, 'get_all')
    def test_init_instance_info(self, mock_get_all,
                                mock_get_by_filters):
        cn1 = objects.ComputeNode(host='host1')
        cn2 = objects.ComputeNode(host='host2')
        inst1 = objects.Instance(host='host1', uuid='uuid1')
        inst2 = objects.Instance(host='host1', uuid='uuid2')
        inst3 = objects.Instance(host='host2', uuid='uuid3')
        mock_get_all.return_value = objects.ComputeNodeList(objects=[cn1, cn2])
        mock_get_by_filters.return_value = objects.InstanceList(
                objects=[inst1, inst2, inst3])
        hm = self.host_manager
        hm._instance_info = {}
        hm._init_instance_info()
        self.assertEqual(len(hm._instance_info), 2)
        fake_info = hm._instance_info['host1']
        self.assertIn('uuid1', fake_info['instances'])
        self.assertIn('uuid2', fake_info['instances'])
        self.assertNotIn('uuid3', fake_info['instances'])
        exp_filters = {'deleted': False, 'host': [u'host1', u'host2']}
        mock_get_by_filters.assert_called_once_with(mock.ANY, exp_filters)

    def test_default_filters(self):
        default_filters = self.host_manager.default_filters
        self.assertEqual(1, len(default_filters))
        self.assertIsInstance(default_filters[0], FakeFilterClass1)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(objects.AggregateList, 'get_all')
    def test_init_aggregates_no_aggs(self, agg_get_all, mock_init_info):
        agg_get_all.return_value = []
        self.host_manager = host_manager.HostManager()
        self.assertEqual({}, self.host_manager.aggs_by_id)
        self.assertEqual({}, self.host_manager.host_aggregates_map)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(objects.AggregateList, 'get_all')
    def test_init_aggregates_one_agg_no_hosts(self, agg_get_all,
                                              mock_init_info):
        fake_agg = objects.Aggregate(id=1, hosts=[])
        agg_get_all.return_value = [fake_agg]
        self.host_manager = host_manager.HostManager()
        self.assertEqual({1: fake_agg}, self.host_manager.aggs_by_id)
        self.assertEqual({}, self.host_manager.host_aggregates_map)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(objects.AggregateList, 'get_all')
    def test_init_aggregates_one_agg_with_hosts(self, agg_get_all,
                                                mock_init_info):
        fake_agg = objects.Aggregate(id=1, hosts=['fake-host'])
        agg_get_all.return_value = [fake_agg]
        self.host_manager = host_manager.HostManager()
        self.assertEqual({1: fake_agg}, self.host_manager.aggs_by_id)
        self.assertEqual({'fake-host': set([1])},
                         self.host_manager.host_aggregates_map)

    def test_update_aggregates(self):
        fake_agg = objects.Aggregate(id=1, hosts=['fake-host'])
        self.host_manager.update_aggregates([fake_agg])
        self.assertEqual({1: fake_agg}, self.host_manager.aggs_by_id)
        self.assertEqual({'fake-host': set([1])},
                         self.host_manager.host_aggregates_map)

    def test_update_aggregates_remove_hosts(self):
        fake_agg = objects.Aggregate(id=1, hosts=['fake-host'])
        self.host_manager.update_aggregates([fake_agg])
        self.assertEqual({1: fake_agg}, self.host_manager.aggs_by_id)
        self.assertEqual({'fake-host': set([1])},
                         self.host_manager.host_aggregates_map)
        # Let's remove the host from the aggregate and update again
        fake_agg.hosts = []
        self.host_manager.update_aggregates([fake_agg])
        self.assertEqual({1: fake_agg}, self.host_manager.aggs_by_id)
        self.assertEqual({'fake-host': set([])},
                         self.host_manager.host_aggregates_map)

    def test_delete_aggregate(self):
        fake_agg = objects.Aggregate(id=1, hosts=['fake-host'])
        self.host_manager.host_aggregates_map = collections.defaultdict(
            set, {'fake-host': set([1])})
        self.host_manager.aggs_by_id = {1: fake_agg}
        self.host_manager.delete_aggregate(fake_agg)
        self.assertEqual({}, self.host_manager.aggs_by_id)
        self.assertEqual({'fake-host': set([])},
                         self.host_manager.host_aggregates_map)

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

    def _mock_get_filtered_hosts(self, info):
        info['got_objs'] = []
        info['got_fprops'] = []

        def fake_filter_one(_self, obj, filter_props):
            info['got_objs'].append(obj)
            info['got_fprops'].append(filter_props)
            return True

        self.stubs.Set(FakeFilterClass1, '_filter_one', fake_filter_one)

    def _verify_result(self, info, result, filters=True):
        for x in info['got_fprops']:
            self.assertEqual(x, info['expected_fprops'])
        if filters:
            self.assertEqual(set(info['expected_objs']), set(info['got_objs']))
        self.assertEqual(set(info['expected_objs']), set(result))

    def test_get_filtered_hosts(self):
        fake_properties = objects.RequestSpec(ignore_hosts=[],
                                              instance_uuid='fake-uuid1',
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
        fake_properties = objects.RequestSpec(ignore_hosts=[],
                                              instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
            ignore_hosts=[],
            force_hosts=['fake_host5', 'fake_host6'],
            force_nodes=[])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        with mock.patch.object(self.host_manager.filter_handler,
                'get_filtered_objects') as fake_filter:
            result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                    fake_properties)
            self.assertFalse(fake_filter.called)

        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_ignore_and_force_hosts(self):
        # Ensure ignore_hosts processed before force_hosts in host filters.
        fake_properties = objects.RequestSpec(
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
            ignore_hosts=[],
            force_hosts=['fake-host1', 'fake_multihost'],
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
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
            instance_uuid='fake-uuid1',
            ignore_hosts=['fake_multihost'],
            force_hosts=[],
            force_nodes=['fake_node4', 'fake_node2'])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    @mock.patch.object(nova.objects.InstanceList, 'get_by_host')
    def test_get_all_host_states(self, mock_get_by_host):
        mock_get_by_host.return_value = objects.InstanceList()
        context = 'fake_context'
        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_binary')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        self.mox.StubOutWithMock(host_manager.LOG, 'warning')

        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # node 3 host physical disk space is greater than database
        host_manager.LOG.warning("Host %(hostname)s has more disk space "
                                 "than database expected (%(physical)s GB >"
                                 " %(database)s GB)",
                                 {'physical': 3333, 'database': 3072,
                                  'hostname': 'node3'})
        # Invalid service
        host_manager.LOG.warning("No compute service record found for "
                                 "host %(host)s",
                                 {'host': 'fake'})
        self.mox.ReplayAll()
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map

        self.assertEqual(len(host_states_map), 4)
        # Check that .service is set properly
        for i in range(4):
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

    @mock.patch.object(nova.objects.InstanceList, 'get_by_host')
    @mock.patch.object(host_manager.HostState, '_update_from_compute_node')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.ServiceList, 'get_by_binary')
    def test_get_all_host_states_with_no_aggs(self, svc_get_by_binary,
                                              cn_get_all, update_from_cn,
                                              mock_get_by_host):
        svc_get_by_binary.return_value = [objects.Service(host='fake')]
        cn_get_all.return_value = [
            objects.ComputeNode(host='fake', hypervisor_hostname='fake')]
        mock_get_by_host.return_value = objects.InstanceList()
        self.host_manager.host_aggregates_map = collections.defaultdict(set)

        self.host_manager.get_all_host_states('fake-context')
        host_state = self.host_manager.host_state_map[('fake', 'fake')]
        self.assertEqual([], host_state.aggregates)

    @mock.patch.object(nova.objects.InstanceList, 'get_by_host')
    @mock.patch.object(host_manager.HostState, '_update_from_compute_node')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.ServiceList, 'get_by_binary')
    def test_get_all_host_states_with_matching_aggs(self, svc_get_by_binary,
                                                    cn_get_all,
                                                    update_from_cn,
                                                    mock_get_by_host):
        svc_get_by_binary.return_value = [objects.Service(host='fake')]
        cn_get_all.return_value = [
            objects.ComputeNode(host='fake', hypervisor_hostname='fake')]
        mock_get_by_host.return_value = objects.InstanceList()
        fake_agg = objects.Aggregate(id=1)
        self.host_manager.host_aggregates_map = collections.defaultdict(
            set, {'fake': set([1])})
        self.host_manager.aggs_by_id = {1: fake_agg}

        self.host_manager.get_all_host_states('fake-context')
        host_state = self.host_manager.host_state_map[('fake', 'fake')]
        self.assertEqual([fake_agg], host_state.aggregates)

    @mock.patch.object(nova.objects.InstanceList, 'get_by_host')
    @mock.patch.object(host_manager.HostState, '_update_from_compute_node')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.ServiceList, 'get_by_binary')
    def test_get_all_host_states_with_not_matching_aggs(self,
                                                        svc_get_by_binary,
                                                        cn_get_all,
                                                        update_from_cn,
                                                        mock_get_by_host):
        svc_get_by_binary.return_value = [objects.Service(host='fake'),
                                          objects.Service(host='other')]
        cn_get_all.return_value = [
            objects.ComputeNode(host='fake', hypervisor_hostname='fake'),
            objects.ComputeNode(host='other', hypervisor_hostname='other')]
        mock_get_by_host.return_value = objects.InstanceList()
        fake_agg = objects.Aggregate(id=1)
        self.host_manager.host_aggregates_map = collections.defaultdict(
            set, {'other': set([1])})
        self.host_manager.aggs_by_id = {1: fake_agg}

        self.host_manager.get_all_host_states('fake-context')
        host_state = self.host_manager.host_state_map[('fake', 'fake')]
        self.assertEqual([], host_state.aggregates)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states_updated(self, mock_get_by_host,
                                         mock_get_all_comp,
                                         mock_get_svc_by_binary):
        mock_get_all_comp.return_value = fakes.COMPUTE_NODES
        mock_get_svc_by_binary.return_value = fakes.SERVICES
        context = 'fake_context'
        hm = self.host_manager
        inst1 = objects.Instance(uuid='uuid1')
        cn1 = objects.ComputeNode(host='host1')
        hm._instance_info = {'host1': {'instances': {'uuid1': inst1},
                                       'updated': True}}
        host_state = host_manager.HostState('host1', cn1)
        self.assertFalse(host_state.instances)
        mock_get_by_host.return_value = None
        host_state.update(
                inst_dict=hm._get_instance_info(context, cn1))
        self.assertFalse(mock_get_by_host.called)
        self.assertTrue(host_state.instances)
        self.assertEqual(host_state.instances['uuid1'], inst1)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states_not_updated(self, mock_get_by_host,
                                             mock_get_all_comp,
                                             mock_get_svc_by_binary):
        mock_get_all_comp.return_value = fakes.COMPUTE_NODES
        mock_get_svc_by_binary.return_value = fakes.SERVICES
        context = 'fake_context'
        hm = self.host_manager
        inst1 = objects.Instance(uuid='uuid1')
        cn1 = objects.ComputeNode(host='host1')
        hm._instance_info = {'host1': {'instances': {'uuid1': inst1},
                                       'updated': False}}
        host_state = host_manager.HostState('host1', cn1)
        self.assertFalse(host_state.instances)
        mock_get_by_host.return_value = objects.InstanceList(objects=[inst1])
        host_state.update(
                inst_dict=hm._get_instance_info(context, cn1))
        mock_get_by_host.assert_called_once_with(context, cn1.host)
        self.assertTrue(host_state.instances)
        self.assertEqual(host_state.instances['uuid1'], inst1)

    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_recreate_instance_info(self, mock_get_by_host):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        new_inst_list = objects.InstanceList(objects=[inst1, inst2])
        mock_get_by_host.return_value = new_inst_list
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': True,
                }}
        self.host_manager._recreate_instance_info('fake_context', host_name)
        new_info = self.host_manager._instance_info[host_name]
        self.assertEqual(len(new_info['instances']), len(new_inst_list))
        self.assertFalse(new_info['updated'])

    def test_update_instance_info(self):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        inst3 = fake_instance.fake_instance_obj('fake_context', uuid='ccc',
                                                host=host_name)
        inst4 = fake_instance.fake_instance_obj('fake_context', uuid='ddd',
                                                host=host_name)
        update = objects.InstanceList(objects=[inst3, inst4])
        self.host_manager.update_instance_info('fake_context', host_name,
                                               update)
        new_info = self.host_manager._instance_info[host_name]
        self.assertEqual(len(new_info['instances']), 4)
        self.assertTrue(new_info['updated'])

    def test_update_instance_info_unknown_host(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        bad_host = 'bad_host'
        inst3 = fake_instance.fake_instance_obj('fake_context', uuid='ccc',
                                                host=bad_host)
        inst_list3 = objects.InstanceList(objects=[inst3])
        self.host_manager.update_instance_info('fake_context', bad_host,
                                               inst_list3)
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', bad_host)
        self.assertEqual(len(new_info['instances']), len(orig_inst_dict))
        self.assertFalse(new_info['updated'])

    def test_delete_instance_info(self):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        self.host_manager.delete_instance_info('fake_context', host_name,
                                               inst1.uuid)
        new_info = self.host_manager._instance_info[host_name]
        self.assertEqual(len(new_info['instances']), 1)
        self.assertTrue(new_info['updated'])

    def test_delete_instance_info_unknown_host(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        bad_host = 'bad_host'
        self.host_manager.delete_instance_info('fake_context', bad_host, 'aaa')
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', bad_host)
        self.assertEqual(len(new_info['instances']), len(orig_inst_dict))
        self.assertFalse(new_info['updated'])

    def test_sync_instance_info(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        self.host_manager.sync_instance_info('fake_context', host_name,
                                             ['bbb', 'aaa'])
        new_info = self.host_manager._instance_info[host_name]
        self.assertFalse(self.host_manager._recreate_instance_info.called)
        self.assertTrue(new_info['updated'])

    def test_sync_instance_info_fail(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context', uuid='aaa',
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context', uuid='bbb',
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        self.host_manager.sync_instance_info('fake_context', host_name,
                                             ['bbb', 'aaa', 'new'])
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', host_name)
        self.assertFalse(new_info['updated'])


class HostManagerChangedNodesTestCase(test.NoDBTestCase):
    """Test case for HostManager class."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(HostManagerChangedNodesTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [
              host_manager.HostState('host1', 'node1'),
              host_manager.HostState('host2', 'node2'),
              host_manager.HostState('host3', 'node3'),
              host_manager.HostState('host4', 'node4')
            ]

    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states(self, mock_get_by_host):
        mock_get_by_host.return_value = objects.InstanceList()
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_binary')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 4)

    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states_after_delete_one(self, mock_get_by_host):
        mock_get_by_host.return_value = objects.InstanceList()
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_binary')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        # all nodes active for first call
        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove node4 for second call
        running_nodes = [n for n in fakes.COMPUTE_NODES
                         if n.get('hypervisor_hostname') != 'node4']
        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(running_nodes)
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 3)

    @mock.patch('nova.objects.InstanceList.get_by_host')
    def test_get_all_host_states_after_delete_all(self, mock_get_by_host):
        mock_get_by_host.return_value = objects.InstanceList()
        context = 'fake_context'

        self.mox.StubOutWithMock(objects.ServiceList, 'get_by_binary')
        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')
        # all nodes active for first call
        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn(fakes.COMPUTE_NODES)
        # remove all nodes for second call
        objects.ServiceList.get_by_binary(
            context, 'nova-compute').AndReturn(fakes.SERVICES)
        objects.ComputeNodeList.get_all(context).AndReturn([])
        self.mox.ReplayAll()

        self.host_manager.get_all_host_states(context)
        self.host_manager.get_all_host_states(context)
        host_states_map = self.host_manager.host_state_map
        self.assertEqual(len(host_states_map), 0)


class HostStateTestCase(test.NoDBTestCase):
    """Test case for HostState class."""

    # update_from_compute_node() and consume_from_request() are tested
    # in HostManagerTestCase.test_get_all_host_states()

    @mock.patch('nova.utils.synchronized',
                side_effect=lambda a: lambda f: lambda *args: f(*args))
    def test_stat_consumption_from_compute_node(self, sync_mock):
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

        hyper_ver_int = versionutils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=1, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update(compute=compute)

        sync_mock.assert_called_once_with(("fakehost", "fakenode"))
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

        hyper_ver_int = versionutils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update(compute=compute)
        self.assertEqual([], host.pci_stats.pools)
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

        hyper_ver_int = versionutils.convert_version_to_int('6.0.0')
        compute = objects.ComputeNode(
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=None, host_ip='127.0.0.1',
            hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5)

        host = host_manager.HostState("fakehost", "fakenode")
        host.update(compute=compute)

        self.assertEqual(5, host.num_instances)
        self.assertEqual(42, host.num_io_ops)
        self.assertEqual(10, len(host.stats))

        self.assertEqual([], host.pci_stats.pools)
        self.assertEqual(hyper_ver_int, host.hypervisor_version)

    @mock.patch('nova.utils.synchronized',
                side_effect=lambda a: lambda f: lambda *args: f(*args))
    @mock.patch('nova.virt.hardware.get_host_numa_usage_from_instance')
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.virt.hardware.numa_fit_instance_to_host')
    @mock.patch('nova.virt.hardware.host_topology_and_format_from_host')
    def test_stat_consumption_from_instance(self, host_topo_mock,
                                            numa_fit_mock,
                                            instance_init_mock,
                                            numa_usage_mock,
                                            sync_mock):
        fake_numa_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell()])
        fake_host_numa_topology = mock.Mock()
        fake_instance = objects.Instance(numa_topology=fake_numa_topology)
        host_topo_mock.return_value = (fake_host_numa_topology, True)
        numa_usage_mock.return_value = fake_host_numa_topology
        numa_fit_mock.return_value = fake_numa_topology
        instance_init_mock.return_value = fake_instance
        spec_obj = objects.RequestSpec(
            instance_uuid='fake-uuid',
            flavor=objects.Flavor(root_gb=0, ephemeral_gb=0, memory_mb=0,
                                  vcpus=0),
            numa_topology=fake_numa_topology,
            pci_requests=objects.InstancePCIRequests(requests=[]))
        host = host_manager.HostState("fakehost", "fakenode")

        self.assertIsNone(host.updated)
        host.consume_from_request(spec_obj)
        numa_fit_mock.assert_called_once_with(fake_host_numa_topology,
                                              fake_numa_topology,
                                              limits=None, pci_requests=None,
                                              pci_stats=None)
        numa_usage_mock.assert_called_once_with(host, fake_instance)
        sync_mock.assert_called_once_with(("fakehost", "fakenode"))
        self.assertEqual(fake_host_numa_topology, host.numa_topology)
        self.assertIsNotNone(host.updated)

        second_numa_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell()])
        spec_obj = objects.RequestSpec(
            instance_uuid='fake-uuid',
            flavor=objects.Flavor(root_gb=0, ephemeral_gb=0, memory_mb=0,
                                  vcpus=0),
            numa_topology=second_numa_topology,
            pci_requests=objects.InstancePCIRequests(requests=[]))
        second_host_numa_topology = mock.Mock()
        numa_usage_mock.return_value = second_host_numa_topology
        numa_fit_mock.return_value = second_numa_topology

        host.consume_from_request(spec_obj)
        self.assertEqual(2, host.num_instances)
        self.assertEqual(2, host.num_io_ops)
        self.assertEqual(2, numa_usage_mock.call_count)
        self.assertEqual(((host, fake_instance),), numa_usage_mock.call_args)
        self.assertEqual(second_host_numa_topology, host.numa_topology)
        self.assertIsNotNone(host.updated)

    def test_stat_consumption_from_instance_pci(self):

        inst_topology = objects.InstanceNUMATopology(
                            cells = [objects.InstanceNUMACell(
                                                      cpuset=set([0]),
                                                      memory=512, id=0)])

        fake_requests = [{'request_id': 'fake_request1', 'count': 1,
                          'spec': [{'vendor_id': '8086'}]}]
        fake_requests_obj = objects.InstancePCIRequests(
                                requests=[objects.InstancePCIRequest(**r)
                                          for r in fake_requests],
                                instance_uuid='fake-uuid')
        req_spec = objects.RequestSpec(
            instance_uuid='fake-uuid',
            project_id='12345',
            numa_topology=inst_topology,
            pci_requests=fake_requests_obj,
            flavor=objects.Flavor(root_gb=0,
                                  ephemeral_gb=0,
                                  memory_mb=512,
                                  vcpus=1))
        host = host_manager.HostState("fakehost", "fakenode")
        self.assertIsNone(host.updated)
        host.pci_stats = pci_stats.PciDeviceStats(
                                      [objects.PciDevicePool(vendor_id='8086',
                                                             product_id='15ed',
                                                             numa_node=1,
                                                             count=1)])
        host.numa_topology = fakes.NUMA_TOPOLOGY
        host.consume_from_request(req_spec)
        self.assertIsInstance(req_spec.numa_topology,
                              objects.InstanceNUMATopology)

        self.assertEqual(512, host.numa_topology.cells[1].memory_usage)
        self.assertEqual(1, host.numa_topology.cells[1].cpu_usage)
        self.assertEqual(0, len(host.pci_stats.pools))
        self.assertIsNotNone(host.updated)

    def test_stat_consumption_from_instance_with_pci_exception(self):
        fake_requests = [{'request_id': 'fake_request1', 'count': 3,
                          'spec': [{'vendor_id': '8086'}]}]
        fake_requests_obj = objects.InstancePCIRequests(
                                requests=[objects.InstancePCIRequest(**r)
                                          for r in fake_requests],
                                instance_uuid='fake-uuid')
        req_spec = objects.RequestSpec(
            instance_uuid='fake-uuid',
            project_id='12345',
            numa_topology=None,
            pci_requests=fake_requests_obj,
            flavor=objects.Flavor(root_gb=0,
                                  ephemeral_gb=0,
                                  memory_mb=1024,
                                  vcpus=1))
        host = host_manager.HostState("fakehost", "fakenode")
        self.assertIsNone(host.updated)
        fake_updated = mock.sentinel.fake_updated
        host.updated = fake_updated
        host.pci_stats = pci_stats.PciDeviceStats()
        with mock.patch.object(host.pci_stats, 'apply_requests',
                               side_effect=exception.PciDeviceRequestFailed):
            host.consume_from_request(req_spec)
        self.assertEqual(fake_updated, host.updated)

    def test_resources_consumption_from_compute_node(self):
        _ts_now = datetime.datetime(2015, 11, 11, 11, 0, 0)
        metrics = [
            dict(name='cpu.frequency',
                 value=1.0,
                 source='source1',
                 timestamp=_ts_now),
            dict(name='numa.membw.current',
                 numa_membw_values={"0": 10, "1": 43},
                 source='source2',
                 timestamp=_ts_now),
        ]
        hyper_ver_int = versionutils.convert_version_to_int('6.0.0')
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
            stats=None, pci_device_pools=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5)
        host = host_manager.HostState("fakehost", "fakenode")
        host.update(compute=compute)

        self.assertEqual(len(host.metrics), 2)
        self.assertEqual(1.0, host.metrics.to_list()[0]['value'])
        self.assertEqual('source1', host.metrics[0].source)
        self.assertEqual('cpu.frequency', host.metrics[0].name)
        self.assertEqual('numa.membw.current', host.metrics[1].name)
        self.assertEqual('source2', host.metrics.to_list()[1]['source'])
        self.assertEqual({'0': 10, '1': 43},
                         host.metrics[1].numa_membw_values)
        self.assertIsInstance(host.numa_topology, six.string_types)

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
import contextlib
import datetime

import mock
from oslo_serialization import jsonutils
from oslo_utils import versionutils
import six

import nova
from nova.compute import task_states
from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.pci import stats as pci_stats
from nova.scheduler import filters
from nova.scheduler import host_manager
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_instance
from nova.tests.unit.scheduler import fakes
from nova.tests import uuidsentinel as uuids


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
        self.flags(available_filters=[
            __name__ + '.FakeFilterClass1', __name__ + '.FakeFilterClass2'],
            group='filter_scheduler')
        self.flags(enabled_filters=['FakeFilterClass1'],
                   group='filter_scheduler')
        self.host_manager = host_manager.HostManager()
        cell = uuids.cell
        self.fake_hosts = [host_manager.HostState('fake_host%s' % x,
                'fake-node', cell) for x in range(1, 5)]
        self.fake_hosts += [host_manager.HostState('fake_multihost',
                'fake-node%s' % x, cell) for x in range(1, 5)]

        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    def test_load_filters(self):
        filters = self.host_manager._load_filters()
        self.assertEqual(filters, ['FakeFilterClass1'])

    def test_refresh_cells_caches(self):
        ctxt = nova_context.RequestContext('fake', 'fake')
        # Loading the non-cell0 mapping from the base test class.
        self.assertEqual(1, len(self.host_manager.enabled_cells))
        self.assertEqual(1, len(self.host_manager.cells))
        # Creating cell mappings for mocking the list of cell_mappings obtained
        # so that the refreshing mechanism can be properly tested. This will in
        # turn ignore the loaded cell mapping from the base test case setup.
        cell_uuid1 = uuids.cell1
        cell_mapping1 = objects.CellMapping(context=ctxt,
                                            uuid=cell_uuid1,
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1',
                                            disabled=False)
        cell_uuid2 = uuids.cell2
        cell_mapping2 = objects.CellMapping(context=ctxt,
                                            uuid=cell_uuid2,
                                            database_connection='fake:///db2',
                                            transport_url='fake:///mq2',
                                            disabled=True)
        cell_uuid3 = uuids.cell3
        cell_mapping3 = objects.CellMapping(context=ctxt,
                                            uuid=cell_uuid3,
                                            database_connection='fake:///db3',
                                            transport_url='fake:///mq3',
                                            disabled=False)
        cells = [cell_mapping1, cell_mapping2, cell_mapping3]
        with mock.patch('nova.objects.CellMappingList.get_all',
                        return_value=cells) as mock_cm:
            self.host_manager.refresh_cells_caches()
            mock_cm.assert_called_once()
        self.assertEqual(2, len(self.host_manager.enabled_cells))
        self.assertEqual(cell_uuid3, self.host_manager.enabled_cells[1].uuid)
        self.assertEqual(3, len(self.host_manager.cells))
        self.assertEqual(cell_uuid2, self.host_manager.cells[1].uuid)

    def test_refresh_cells_caches_except_cell0(self):
        ctxt = nova_context.RequestContext('fake-user', 'fake_project')
        cell_uuid0 = objects.CellMapping.CELL0_UUID
        cell_mapping0 = objects.CellMapping(context=ctxt,
                                            uuid=cell_uuid0,
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1')
        cells = objects.CellMappingList(cell_mapping0)
        # Mocking the return value of get_all cell_mappings to return only
        # the cell0 mapping to check if its filtered or not.
        with mock.patch('nova.objects.CellMappingList.get_all',
                        return_value=cells) as mock_cm:
            self.host_manager.refresh_cells_caches()
            mock_cm.assert_called_once()
        self.assertEqual(0, len(self.host_manager.cells))

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
        inst1 = objects.Instance(host='host1', uuid=uuids.instance_1)
        inst2 = objects.Instance(host='host1', uuid=uuids.instance_2)
        inst3 = objects.Instance(host='host2', uuid=uuids.instance_3)
        mock_get_all.return_value = objects.ComputeNodeList(objects=[cn1, cn2])
        mock_get_by_filters.return_value = objects.InstanceList(
                objects=[inst1, inst2, inst3])
        hm = self.host_manager
        hm._instance_info = {}
        hm._init_instance_info()
        self.assertEqual(len(hm._instance_info), 2)
        fake_info = hm._instance_info['host1']
        self.assertIn(uuids.instance_1, fake_info['instances'])
        self.assertIn(uuids.instance_2, fake_info['instances'])
        self.assertNotIn(uuids.instance_3, fake_info['instances'])
        exp_filters = {'deleted': False, 'host': [u'host1', u'host2']}
        mock_get_by_filters.assert_called_once_with(mock.ANY, exp_filters)

    @mock.patch.object(nova.objects.InstanceList, 'get_by_filters')
    @mock.patch.object(nova.objects.ComputeNodeList, 'get_all')
    def test_init_instance_info_compute_nodes(self, mock_get_all,
                                              mock_get_by_filters):
        cn1 = objects.ComputeNode(host='host1')
        cn2 = objects.ComputeNode(host='host2')
        inst1 = objects.Instance(host='host1', uuid=uuids.instance_1)
        inst2 = objects.Instance(host='host1', uuid=uuids.instance_2)
        inst3 = objects.Instance(host='host2', uuid=uuids.instance_3)
        cell = objects.CellMapping(database_connection='',
                                   target_url='')
        mock_get_by_filters.return_value = objects.InstanceList(
                objects=[inst1, inst2, inst3])
        hm = self.host_manager
        hm._instance_info = {}
        hm._init_instance_info({cell: [cn1, cn2]})
        self.assertEqual(len(hm._instance_info), 2)
        fake_info = hm._instance_info['host1']
        self.assertIn(uuids.instance_1, fake_info['instances'])
        self.assertIn(uuids.instance_2, fake_info['instances'])
        self.assertNotIn(uuids.instance_3, fake_info['instances'])
        exp_filters = {'deleted': False, 'host': [u'host1', u'host2']}
        mock_get_by_filters.assert_called_once_with(mock.ANY, exp_filters)
        # should not be called if the list of nodes was passed explicitly
        self.assertFalse(mock_get_all.called)

    def test_enabled_filters(self):
        enabled_filters = self.host_manager.enabled_filters
        self.assertEqual(1, len(enabled_filters))
        self.assertIsInstance(enabled_filters[0], FakeFilterClass1)

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

        self.stub_out(__name__ + '.FakeFilterClass1._filter_one',
                      fake_filter_one)

    def _verify_result(self, info, result, filters=True):
        for x in info['got_fprops']:
            self.assertEqual(x, info['expected_fprops'])
        if filters:
            self.assertEqual(set(info['expected_objs']), set(info['got_objs']))
        self.assertEqual(set(info['expected_objs']), set(result))

    def test_get_filtered_hosts(self):
        fake_properties = objects.RequestSpec(ignore_hosts=[],
                                              instance_uuid=uuids.instance,
                                              force_hosts=[],
                                              force_nodes=[])

        info = {'expected_objs': self.fake_hosts,
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_requested_destination(self):
        dest = objects.Destination(host='fake_host1', node='fake-node')
        fake_properties = objects.RequestSpec(requested_destination=dest,
                                              ignore_hosts=[],
                                              instance_uuid=uuids.fake_uuid1,
                                              force_hosts=[],
                                              force_nodes=[])

        info = {'expected_objs': [self.fake_hosts[0]],
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_wrong_requested_destination(self):
        dest = objects.Destination(host='dummy', node='fake-node')
        fake_properties = objects.RequestSpec(requested_destination=dest,
                                              ignore_hosts=[],
                                              instance_uuid=uuids.fake_uuid1,
                                              force_hosts=[],
                                              force_nodes=[])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}

        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result)

    def test_get_filtered_hosts_with_ignore(self):
        fake_properties = objects.RequestSpec(
            instance_uuid=uuids.instance,
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

    def test_get_filtered_hosts_with_ignore_case_insensitive(self):
        fake_properties = objects.RequestSpec(
            instance_uuids=uuids.fakehost,
            ignore_hosts=['FAKE_HOST1', 'FaKe_HoSt3', 'Fake_Multihost'],
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
            instance_uuid=uuids.instance,
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

    def test_get_filtered_hosts_with_force_case_insensitive(self):
        fake_properties = objects.RequestSpec(
            instance_uuids=uuids.fakehost,
            ignore_hosts=[],
            force_hosts=['FAKE_HOST1', 'FaKe_HoSt3', 'fake_host4',
                         'faKe_host5'],
            force_nodes=[])

        # [1] and [3] are host2 and host4
        info = {'expected_objs': [self.fake_hosts[0], self.fake_hosts[2],
                                  self.fake_hosts[3]],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    def test_get_filtered_hosts_with_no_matching_force_hosts(self):
        fake_properties = objects.RequestSpec(
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
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
            instance_uuid=uuids.instance,
            ignore_hosts=['fake_multihost'],
            force_hosts=[],
            force_nodes=['fake_node4', 'fake_node2'])

        info = {'expected_objs': [],
                'expected_fprops': fake_properties}
        self._mock_get_filtered_hosts(info)

        result = self.host_manager.get_filtered_hosts(self.fake_hosts,
                fake_properties)
        self._verify_result(info, result, False)

    @mock.patch('nova.scheduler.host_manager.LOG')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_all_host_states(self, mock_get_by_host, mock_get_all,
                                 mock_get_by_binary, mock_log):
        mock_get_by_host.return_value = []
        mock_get_all.return_value = fakes.COMPUTE_NODES
        mock_get_by_binary.return_value = fakes.SERVICES
        context = 'fake_context'

        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           self.host_manager.get_all_host_states(context)}
        self.assertEqual(4, len(host_states_map))

        calls = [
            mock.call(
                "Host %(hostname)s has more disk space than database "
                "expected (%(physical)s GB > %(database)s GB)",
                {'physical': 3333, 'database': 3072, 'hostname': 'node3'}
            ),
            mock.call(
                "No compute service record found for host %(host)s",
                {'host': 'fake'}
            )
        ]
        self.assertEqual(calls, mock_log.warning.call_args_list)

        # Check that .service is set properly
        for i in range(4):
            compute_node = fakes.COMPUTE_NODES[i]
            host = compute_node.host
            node = compute_node.hypervisor_hostname
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
        self.assertEqual(host_states_map[('host4', 'node4')].free_ram_mb,
                         8192)
        # 8191GB
        self.assertEqual(host_states_map[('host4', 'node4')].free_disk_mb,
                         8388608)

    @mock.patch.object(nova.objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(host_manager.HostState, '_update_from_compute_node')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.ServiceList, 'get_by_binary')
    def test_get_all_host_states_with_no_aggs(self, svc_get_by_binary,
                                              cn_get_all, update_from_cn,
                                              mock_get_by_host):
        svc_get_by_binary.return_value = [objects.Service(host='fake')]
        cn_get_all.return_value = [
            objects.ComputeNode(host='fake', hypervisor_hostname='fake')]
        mock_get_by_host.return_value = []
        self.host_manager.host_aggregates_map = collections.defaultdict(set)

        hosts = self.host_manager.get_all_host_states('fake-context')
        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        host_state = host_states_map[('fake', 'fake')]
        self.assertEqual([], host_state.aggregates)

    @mock.patch.object(nova.objects.InstanceList, 'get_uuids_by_host')
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
        mock_get_by_host.return_value = []
        fake_agg = objects.Aggregate(id=1)
        self.host_manager.host_aggregates_map = collections.defaultdict(
            set, {'fake': set([1])})
        self.host_manager.aggs_by_id = {1: fake_agg}

        hosts = self.host_manager.get_all_host_states('fake-context')
        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        host_state = host_states_map[('fake', 'fake')]
        self.assertEqual([fake_agg], host_state.aggregates)

    @mock.patch.object(nova.objects.InstanceList, 'get_uuids_by_host')
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
        mock_get_by_host.return_value = []
        fake_agg = objects.Aggregate(id=1)
        self.host_manager.host_aggregates_map = collections.defaultdict(
            set, {'other': set([1])})
        self.host_manager.aggs_by_id = {1: fake_agg}

        hosts = self.host_manager.get_all_host_states('fake-context')
        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        host_state = host_states_map[('fake', 'fake')]
        self.assertEqual([], host_state.aggregates)

    @mock.patch.object(nova.objects.InstanceList, 'get_uuids_by_host',
                       return_value=[])
    @mock.patch.object(host_manager.HostState, '_update_from_compute_node')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.ServiceList, 'get_by_binary')
    def test_get_all_host_states_corrupt_aggregates_info(self,
                                                         svc_get_by_binary,
                                                         cn_get_all,
                                                         update_from_cn,
                                                         mock_get_by_host):
        """Regression test for bug 1605804

        A host can be in multiple host-aggregates at the same time. When a
        host gets removed from an aggregate in thread A and this aggregate
        gets deleted in thread B, there can be a race-condition where the
        mapping data in the host_manager can get out of sync for a moment.
        This test simulates this condition for the bug-fix.
        """
        host_a = 'host_a'
        host_b = 'host_b'
        svc_get_by_binary.return_value = [objects.Service(host=host_a),
                                          objects.Service(host=host_b)]
        cn_get_all.return_value = [
            objects.ComputeNode(host=host_a, hypervisor_hostname=host_a),
            objects.ComputeNode(host=host_b, hypervisor_hostname=host_b)]

        aggregate = objects.Aggregate(id=1)
        aggregate.hosts = [host_a, host_b]
        aggr_list = objects.AggregateList()
        aggr_list.objects = [aggregate]
        self.host_manager.update_aggregates(aggr_list)

        aggregate.hosts = [host_a]
        self.host_manager.delete_aggregate(aggregate)

        self.host_manager.get_all_host_states('fake-context')

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
        inst1 = objects.Instance(uuid=uuids.instance)
        cn1 = objects.ComputeNode(host='host1')
        hm._instance_info = {'host1': {'instances': {uuids.instance: inst1},
                                       'updated': True}}
        host_state = host_manager.HostState('host1', cn1, uuids.cell)
        self.assertFalse(host_state.instances)
        mock_get_by_host.return_value = None
        host_state.update(
                inst_dict=hm._get_instance_info(context, cn1))
        self.assertFalse(mock_get_by_host.called)
        self.assertTrue(host_state.instances)
        self.assertEqual(host_state.instances[uuids.instance], inst1)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_all_host_states_not_updated(self, mock_get_by_host,
                                             mock_get_all_comp,
                                             mock_get_svc_by_binary):
        mock_get_all_comp.return_value = fakes.COMPUTE_NODES
        mock_get_svc_by_binary.return_value = fakes.SERVICES
        context = 'fake_context'
        hm = self.host_manager
        inst1 = objects.Instance(uuid=uuids.instance)
        cn1 = objects.ComputeNode(host='host1')
        hm._instance_info = {'host1': {'instances': {uuids.instance: inst1},
                                       'updated': False}}
        host_state = host_manager.HostState('host1', cn1, uuids.cell)
        self.assertFalse(host_state.instances)
        mock_get_by_host.return_value = [uuids.instance]
        host_state.update(
                inst_dict=hm._get_instance_info(context, cn1))
        mock_get_by_host.assert_called_once_with(context, cn1.host)
        self.assertTrue(host_state.instances)
        self.assertIn(uuids.instance, host_state.instances)
        inst = host_state.instances[uuids.instance]
        self.assertEqual(uuids.instance, inst.uuid)
        self.assertIsNotNone(inst._context, 'Instance is orphaned.')

    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_recreate_instance_info(self, mock_get_by_host):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_by_host.return_value = [uuids.instance_1, uuids.instance_2]
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': True,
                }}
        self.host_manager._recreate_instance_info('fake_context', host_name)
        new_info = self.host_manager._instance_info[host_name]
        self.assertEqual(len(new_info['instances']),
                         len(mock_get_by_host.return_value))
        self.assertFalse(new_info['updated'])

    def test_update_instance_info(self):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        inst3 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_3,
                                                host=host_name)
        inst4 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_4,
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
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        bad_host = 'bad_host'
        inst3 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_3,
                                                host=bad_host)
        inst_list3 = objects.InstanceList(objects=[inst3])
        self.host_manager.update_instance_info('fake_context', bad_host,
                                               inst_list3)
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', bad_host)
        self.assertEqual(len(new_info['instances']), len(orig_inst_dict))
        self.assertFalse(new_info['updated'])

    @mock.patch('nova.objects.HostMapping.get_by_host',
                side_effect=exception.HostMappingNotFound(name='host1'))
    def test_update_instance_info_unknown_host_mapping_not_found(self,
                                                                 get_by_host):
        """Tests that case that update_instance_info is called with an
        unregistered host so the host manager attempts to recreate the
        instance list, but there is no host mapping found for the given
        host (it might have just started not be discovered for cells
        v2 yet).
        """
        ctxt = nova_context.RequestContext()
        instance_info = objects.InstanceList()
        self.host_manager.update_instance_info(ctxt, 'host1', instance_info)
        self.assertDictEqual(
            {}, self.host_manager._instance_info['host1']['instances'])
        get_by_host.assert_called_once_with(ctxt, 'host1')

    def test_delete_instance_info(self):
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
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
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        bad_host = 'bad_host'
        self.host_manager.delete_instance_info('fake_context', bad_host,
                                               uuids.instance_1)
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', bad_host)
        self.assertEqual(len(new_info['instances']), len(orig_inst_dict))
        self.assertFalse(new_info['updated'])

    def test_sync_instance_info(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        self.host_manager.sync_instance_info('fake_context', host_name,
                                             [uuids.instance_2,
                                              uuids.instance_1])
        new_info = self.host_manager._instance_info[host_name]
        self.assertFalse(self.host_manager._recreate_instance_info.called)
        self.assertTrue(new_info['updated'])

    def test_sync_instance_info_fail(self):
        self.host_manager._recreate_instance_info = mock.MagicMock()
        host_name = 'fake_host'
        inst1 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_1,
                                                host=host_name)
        inst2 = fake_instance.fake_instance_obj('fake_context',
                                                uuid=uuids.instance_2,
                                                host=host_name)
        orig_inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        self.host_manager._instance_info = {
                host_name: {
                    'instances': orig_inst_dict,
                    'updated': False,
                }}
        self.host_manager.sync_instance_info('fake_context', host_name,
                                             [uuids.instance_2,
                                              uuids.instance_1, 'new'])
        new_info = self.host_manager._instance_info[host_name]
        self.host_manager._recreate_instance_info.assert_called_once_with(
                'fake_context', host_name)
        self.assertFalse(new_info['updated'])

    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    def test_get_computes_for_cells(self, mock_sl, mock_cn, mock_cm):
        cells = [
            objects.CellMapping(uuid=uuids.cell1,
                                db_connection='none://1',
                                transport_url='none://'),
            objects.CellMapping(uuid=uuids.cell2,
                                db_connection='none://2',
                                transport_url='none://'),
        ]
        mock_cm.return_value = cells
        mock_sl.side_effect = [
            [objects.ServiceList(host='foo')],
            [objects.ServiceList(host='bar')],
        ]
        mock_cn.side_effect = [
            [objects.ComputeNode(host='foo')],
            [objects.ComputeNode(host='bar')],
        ]
        context = nova_context.RequestContext('fake', 'fake')
        cns, srv = self.host_manager._get_computes_for_cells(context, cells)
        self.assertEqual({uuids.cell1: ['foo'],
                          uuids.cell2: ['bar']},
                         {cell: [cn.host for cn in computes]
                          for cell, computes in cns.items()})
        self.assertEqual(['bar', 'foo'], sorted(list(srv.keys())))

    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_uuids')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    def test_get_computes_for_cells_uuid(self, mock_sl, mock_cn, mock_cm):
        cells = [
            objects.CellMapping(uuid=uuids.cell1,
                                db_connection='none://1',
                                transport_url='none://'),
            objects.CellMapping(uuid=uuids.cell2,
                                db_connection='none://2',
                                transport_url='none://'),
        ]
        mock_cm.return_value = cells
        mock_sl.side_effect = [
            [objects.ServiceList(host='foo')],
            [objects.ServiceList(host='bar')],
        ]
        mock_cn.side_effect = [
            [objects.ComputeNode(host='foo')],
            [objects.ComputeNode(host='bar')],
        ]
        context = nova_context.RequestContext('fake', 'fake')
        cns, srv = self.host_manager._get_computes_for_cells(context, cells,
                                                             [])
        self.assertEqual({uuids.cell1: ['foo'],
                          uuids.cell2: ['bar']},
                         {cell: [cn.host for cn in computes]
                          for cell, computes in cns.items()})
        self.assertEqual(['bar', 'foo'], sorted(list(srv.keys())))

    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    def test_get_computes_for_cells_limit_to_cell(self, mock_sl,
                                                  mock_cn, mock_cm,
                                                  mock_target):
        host_manager.LOG.debug = host_manager.LOG.error
        cells = [
            objects.CellMapping(uuid=uuids.cell1,
                                database_connection='none://1',
                                transport_url='none://'),
            objects.CellMapping(uuid=uuids.cell2,
                                database_connection='none://2',
                                transport_url='none://'),
        ]
        mock_sl.return_value = [objects.ServiceList(host='foo')]
        mock_cn.return_value = [objects.ComputeNode(host='foo')]
        mock_cm.return_value = cells

        @contextlib.contextmanager
        def fake_set_target(context, cell):
            yield mock.sentinel.cctxt

        mock_target.side_effect = fake_set_target

        context = nova_context.RequestContext('fake', 'fake')
        cns, srv = self.host_manager._get_computes_for_cells(
            context, cells=cells[1:])
        self.assertEqual({uuids.cell2: ['foo']},
                         {cell: [cn.host for cn in computes]
                          for cell, computes in cns.items()})
        self.assertEqual(['foo'], list(srv.keys()))

        # NOTE(danms): We have two cells, but we should only have
        # targeted one if we honored the only-cell destination requirement,
        # and only looked up services and compute nodes in one
        mock_target.assert_called_once_with(context, cells[1])
        mock_cn.assert_called_once_with(mock.sentinel.cctxt)
        mock_sl.assert_called_once_with(mock.sentinel.cctxt, 'nova-compute',
                                        include_disabled=True)

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_computes_for_cells_failures(self, mock_sg):
        mock_sg.return_value = {
            uuids.cell1: ([mock.MagicMock(host='a'), mock.MagicMock(host='b')],
                          [mock.sentinel.c1n1, mock.sentinel.c1n2]),
            uuids.cell2: nova_context.did_not_respond_sentinel,
            uuids.cell3: nova_context.raised_exception_sentinel,
        }
        context = nova_context.RequestContext('fake', 'fake')
        cns, srv = self.host_manager._get_computes_for_cells(context, [])

        self.assertEqual({uuids.cell1: [mock.sentinel.c1n1,
                                        mock.sentinel.c1n2]}, cns)
        self.assertEqual(['a', 'b'], sorted(srv.keys()))


class HostManagerChangedNodesTestCase(test.NoDBTestCase):
    """Test case for HostManager class."""

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(HostManagerChangedNodesTestCase, self).setUp()
        self.host_manager = host_manager.HostManager()
        self.fake_hosts = [
              host_manager.HostState('host1', 'node1', uuids.cell),
              host_manager.HostState('host2', 'node2', uuids.cell),
              host_manager.HostState('host3', 'node3', uuids.cell),
              host_manager.HostState('host4', 'node4', uuids.cell)
            ]

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_all_host_states(self, mock_get_by_host, mock_get_all,
                                 mock_get_by_binary):
        mock_get_by_host.return_value = []
        mock_get_all.return_value = fakes.COMPUTE_NODES
        mock_get_by_binary.return_value = fakes.SERVICES
        context = 'fake_context'

        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           self.host_manager.get_all_host_states(context)}
        self.assertEqual(len(host_states_map), 4)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_all_host_states_after_delete_one(self, mock_get_by_host,
                                                  mock_get_all,
                                                  mock_get_by_binary):
        getter = (lambda n: n.hypervisor_hostname
                  if 'hypervisor_hostname' in n else None)
        running_nodes = [n for n in fakes.COMPUTE_NODES
                         if getter(n) != 'node4']

        mock_get_by_host.return_value = []
        mock_get_all.side_effect = [fakes.COMPUTE_NODES, running_nodes]
        mock_get_by_binary.side_effect = [fakes.SERVICES, fakes.SERVICES]
        context = 'fake_context'

        # first call: all nodes
        hosts = self.host_manager.get_all_host_states(context)
        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        self.assertEqual(len(host_states_map), 4)

        # second call: just running nodes
        hosts = self.host_manager.get_all_host_states(context)
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        self.assertEqual(len(host_states_map), 3)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_all_host_states_after_delete_all(self, mock_get_by_host,
                                                  mock_get_all,
                                                  mock_get_by_binary):
        mock_get_by_host.return_value = []
        mock_get_all.side_effect = [fakes.COMPUTE_NODES, []]
        mock_get_by_binary.side_effect = [fakes.SERVICES, fakes.SERVICES]
        context = 'fake_context'

        # first call: all nodes
        hosts = self.host_manager.get_all_host_states(context)
        # get_all_host_states returns a generator, so make a map from it
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        self.assertEqual(len(host_states_map), 4)

        # second call: no nodes
        hosts = self.host_manager.get_all_host_states(context)
        host_states_map = {(state.host, state.nodename): state for state in
                           hosts}
        self.assertEqual(len(host_states_map), 0)

    @mock.patch('nova.objects.ServiceList.get_by_binary')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_uuids')
    @mock.patch('nova.objects.InstanceList.get_uuids_by_host')
    def test_get_host_states_by_uuids(self, mock_get_by_host, mock_get_all,
                                      mock_get_by_binary):
        mock_get_by_host.return_value = []
        mock_get_all.side_effect = [fakes.COMPUTE_NODES, []]
        mock_get_by_binary.side_effect = [fakes.SERVICES, fakes.SERVICES]

        # Request 1: all nodes can satisfy the request
        hosts1 = self.host_manager.get_host_states_by_uuids(
            mock.sentinel.ctxt1, mock.sentinel.uuids1, objects.RequestSpec())
        # get_host_states_by_uuids returns a generator so convert the values
        # into an iterator
        host_states1 = iter(hosts1)

        # Request 2: no nodes can satisfy the request
        hosts2 = self.host_manager.get_host_states_by_uuids(
            mock.sentinel.ctxt2, mock.sentinel.uuids2, objects.RequestSpec())
        host_states2 = iter(hosts2)

        # Fake a concurrent request that is still processing the first result
        # to make sure all nodes are still available candidates to Request 1.
        num_hosts1 = len(list(host_states1))
        self.assertEqual(4, num_hosts1)

        # Verify that no nodes are available to Request 2.
        num_hosts2 = len(list(host_states2))
        self.assertEqual(0, num_hosts2)


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
            uuid=uuids.cn1,
            stats=stats, memory_mb=1, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host_ip='127.0.0.1', hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0)

        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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
            uuid=uuids.cn1,
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host_ip='127.0.0.1', hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0)

        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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
            uuid=uuids.cn1,
            stats=stats, memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host_ip='127.0.0.1', hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int, numa_topology=None,
            pci_device_pools=None, metrics=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0)

        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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
            instance_uuid=uuids.instance,
            flavor=objects.Flavor(root_gb=0, ephemeral_gb=0, memory_mb=0,
                                  vcpus=0),
            numa_topology=fake_numa_topology,
            pci_requests=objects.InstancePCIRequests(requests=[]))
        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)

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
            instance_uuid=uuids.instance,
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

        fake_requests = [{'request_id': uuids.request_id, 'count': 1,
                          'spec': [{'vendor_id': '8086'}]}]
        fake_requests_obj = objects.InstancePCIRequests(
                                requests=[objects.InstancePCIRequest(**r)
                                          for r in fake_requests],
                                instance_uuid=uuids.instance)
        req_spec = objects.RequestSpec(
            instance_uuid=uuids.instance,
            project_id='12345',
            numa_topology=inst_topology,
            pci_requests=fake_requests_obj,
            flavor=objects.Flavor(root_gb=0,
                                  ephemeral_gb=0,
                                  memory_mb=512,
                                  vcpus=1))
        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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
        fake_requests = [{'request_id': uuids.request_id, 'count': 3,
                          'spec': [{'vendor_id': '8086'}]}]
        fake_requests_obj = objects.InstancePCIRequests(
                                requests=[objects.InstancePCIRequest(**r)
                                          for r in fake_requests],
                                instance_uuid=uuids.instance)
        req_spec = objects.RequestSpec(
            instance_uuid=uuids.instance,
            project_id='12345',
            numa_topology=None,
            pci_requests=fake_requests_obj,
            flavor=objects.Flavor(root_gb=0,
                                  ephemeral_gb=0,
                                  memory_mb=1024,
                                  vcpus=1))
        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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
            uuid=uuids.cn1,
            metrics=jsonutils.dumps(metrics),
            memory_mb=0, free_disk_gb=0, local_gb=0,
            local_gb_used=0, free_ram_mb=0, vcpus=0, vcpus_used=0,
            disk_available_least=None,
            updated_at=datetime.datetime(2015, 11, 11, 11, 0, 0),
            host_ip='127.0.0.1', hypervisor_type='htype',
            hypervisor_hostname='hostname', cpu_info='cpu_info',
            supported_hv_specs=[],
            hypervisor_version=hyper_ver_int,
            numa_topology=fakes.NUMA_TOPOLOGY._to_json(),
            stats=None, pci_device_pools=None,
            cpu_allocation_ratio=16.0, ram_allocation_ratio=1.5,
            disk_allocation_ratio=1.0)
        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
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

    def test_stat_consumption_from_compute_node_not_ready(self):
        compute = objects.ComputeNode(free_ram_mb=100,
            uuid=uuids.compute_node_uuid)

        host = host_manager.HostState("fakehost", "fakenode", uuids.cell)
        host._update_from_compute_node(compute)
        # Because compute record not ready, the update of free ram
        # will not happen and the value will still be 0
        self.assertEqual(0, host.free_ram_mb)

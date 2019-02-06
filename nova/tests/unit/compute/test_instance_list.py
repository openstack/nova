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
import six

from nova.compute import instance_list
from nova.compute import multi_cell_list
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures


FAKE_CELLS = [objects.CellMapping(), objects.CellMapping()]


class TestInstanceList(test.NoDBTestCase):
    def setUp(self):
        super(TestInstanceList, self).setUp()

        cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                     name='cell%i' % i,
                                     transport_url='fake:///',
                                     database_connection='fake://')
                 for i in range(0, 3)]

        insts = {}
        for cell in cells:
            insts[cell.uuid] = list([
                dict(
                    uuid=getattr(uuids, '%s-inst%i' % (cell.name, i)),
                    hostname='%s-inst%i' % (cell.name, i))
                for i in range(0, 3)])

        self.cells = cells
        self.insts = insts
        self.context = nova_context.RequestContext()
        self.useFixture(fixtures.SpawnIsSynchronousFixture())

        self.flags(instance_list_cells_batch_strategy='fixed', group='api')

    def test_compare_simple_instance_quirks(self):
        # Ensure uuid,asc is added
        ctx = instance_list.InstanceSortContext(['key0'], ['asc'])
        self.assertEqual(['key0', 'uuid'], ctx.sort_keys)
        self.assertEqual(['asc', 'asc'], ctx.sort_dirs)

        # Ensure defaults are added
        ctx = instance_list.InstanceSortContext(None, None)
        self.assertEqual(['created_at', 'id', 'uuid'], ctx.sort_keys)
        self.assertEqual(['desc', 'desc', 'asc'], ctx.sort_dirs)

    @mock.patch('nova.db.api.instance_get_all_by_filters_sort')
    @mock.patch('nova.objects.CellMappingList.get_all')
    def test_get_instances_sorted(self, mock_cells, mock_inst):
        mock_cells.return_value = self.cells
        insts_by_cell = self.insts.values()

        mock_inst.side_effect = insts_by_cell
        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        None, None, [],
                                                        ['hostname'], ['asc'])
        insts_one = [inst['hostname'] for inst in insts]

        # Reverse the order that we get things from the cells so we can
        # make sure that the result is still sorted the same way
        insts_by_cell = list(reversed(list(insts_by_cell)))
        mock_inst.reset_mock()
        mock_inst.side_effect = insts_by_cell

        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        None, None, [],
                                                        ['hostname'], ['asc'])
        insts_two = [inst['hostname'] for inst in insts]

        self.assertEqual(insts_one, insts_two)

    @mock.patch('nova.objects.BuildRequestList.get_by_filters')
    @mock.patch('nova.compute.instance_list.get_instances_sorted')
    @mock.patch('nova.objects.CellMappingList.get_by_project_id')
    def test_user_gets_subset_of_cells(self, mock_cm, mock_gi, mock_br):
        self.flags(instance_list_per_project_cells=True, group='api')
        mock_gi.return_value = instance_list.InstanceLister(None, None), []
        mock_br.return_value = []
        user_context = nova_context.RequestContext('fake', 'fake')
        instance_list.get_instance_objects_sorted(
            user_context, {}, None, None, [], None, None)
        mock_gi.assert_called_once_with(user_context, {}, None, None, [],
                                        None, None,
                                        cell_mappings=mock_cm.return_value,
                                        batch_size=1000,
                                        cell_down_support=False)

    @mock.patch('nova.context.CELLS', new=FAKE_CELLS)
    @mock.patch('nova.context.load_cells')
    @mock.patch('nova.objects.BuildRequestList.get_by_filters')
    @mock.patch('nova.compute.instance_list.get_instances_sorted')
    @mock.patch('nova.objects.CellMappingList.get_by_project_id')
    def test_admin_gets_all_cells(self, mock_cm, mock_gi, mock_br, mock_lc):
        mock_gi.return_value = instance_list.InstanceLister(None, None), []
        mock_br.return_value = []
        admin_context = nova_context.RequestContext('fake', 'fake',
                                                    is_admin=True)
        instance_list.get_instance_objects_sorted(
            admin_context, {}, None, None, [], None, None)
        mock_gi.assert_called_once_with(admin_context, {}, None, None, [],
                                        None, None,
                                        cell_mappings=FAKE_CELLS,
                                        batch_size=100,
                                        cell_down_support=False)
        mock_cm.assert_not_called()
        mock_lc.assert_called_once_with()

    @mock.patch('nova.context.CELLS', new=FAKE_CELLS)
    @mock.patch('nova.context.load_cells')
    @mock.patch('nova.objects.BuildRequestList.get_by_filters')
    @mock.patch('nova.compute.instance_list.get_instances_sorted')
    @mock.patch('nova.objects.CellMappingList.get_by_project_id')
    def test_user_gets_all_cells(self, mock_cm, mock_gi, mock_br, mock_lc):
        self.flags(instance_list_per_project_cells=False, group='api')
        mock_gi.return_value = instance_list.InstanceLister(None, None), []
        mock_br.return_value = []
        user_context = nova_context.RequestContext('fake', 'fake')
        instance_list.get_instance_objects_sorted(
            user_context, {}, None, None, [], None, None)
        mock_gi.assert_called_once_with(user_context, {}, None, None, [],
                                        None, None,
                                        cell_mappings=FAKE_CELLS,
                                        batch_size=100,
                                        cell_down_support=False)
        mock_lc.assert_called_once_with()

    @mock.patch('nova.context.CELLS', new=FAKE_CELLS)
    @mock.patch('nova.context.load_cells')
    @mock.patch('nova.objects.BuildRequestList.get_by_filters')
    @mock.patch('nova.compute.instance_list.get_instances_sorted')
    @mock.patch('nova.objects.CellMappingList.get_by_project_id')
    def test_admin_gets_all_cells_anyway(self, mock_cm, mock_gi, mock_br,
                                         mock_lc):
        self.flags(instance_list_per_project_cells=True, group='api')
        mock_gi.return_value = instance_list.InstanceLister(None, None), []
        mock_br.return_value = []
        admin_context = nova_context.RequestContext('fake', 'fake',
                                                    is_admin=True)
        instance_list.get_instance_objects_sorted(
            admin_context, {}, None, None, [], None, None)
        mock_gi.assert_called_once_with(admin_context, {}, None, None, [],
                                        None, None,
                                        cell_mappings=FAKE_CELLS,
                                        batch_size=100,
                                        cell_down_support=False)
        mock_cm.assert_not_called()
        mock_lc.assert_called_once_with()

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_instances_with_down_cells(self, mock_sg):
        inst_cell0 = self.insts[uuids.cell0]
        # storing the uuids of the instances from the up cell
        uuid_initial = [inst['uuid'] for inst in inst_cell0]

        def wrap(thing):
            return multi_cell_list.RecordWrapper(ctx, self.context, thing)

        ctx = nova_context.RequestContext()
        instances = [wrap(inst) for inst in inst_cell0]

        # creating one up cell and two down cells
        ret_val = {}
        ret_val[uuids.cell0] = instances
        ret_val[uuids.cell1] = [wrap(exception.BuildRequestNotFound(uuid='f'))]
        ret_val[uuids.cell2] = [wrap(nova_context.did_not_respond_sentinel)]
        mock_sg.return_value = ret_val

        obj, res = instance_list.get_instances_sorted(self.context, {}, None,
                                                      None, [], None, None)

        uuid_final = [inst['uuid'] for inst in res]

        # return the results from the up cell, ignoring the down cell.
        self.assertEqual(uuid_initial, uuid_final)

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_instances_by_not_skipping_down_cells(self, mock_sg):
        self.flags(list_records_by_skipping_down_cells=False, group='api')
        inst_cell0 = self.insts[uuids.cell0]

        def wrap(thing):
            return multi_cell_list.RecordWrapper(ctx, self.context, thing)

        ctx = nova_context.RequestContext()
        instances = [wrap(inst) for inst in inst_cell0]

        # creating one up cell and two down cells
        ret_val = {}
        ret_val[uuids.cell0] = instances
        ret_val[uuids.cell1] = [wrap(exception.BuildRequestNotFound(uuid='f'))]
        ret_val[uuids.cell2] = [wrap(nova_context.did_not_respond_sentinel)]
        mock_sg.return_value = ret_val

        # Raises exception if a cell is down without skipping them
        # as CONF.api.list_records_by_skipping_down_cells is set to False.
        # This would in turn result in an API 500 internal error.
        exp = self.assertRaises(exception.NovaException,
            instance_list.get_instance_objects_sorted, self.context, {}, None,
            None, [], None, None)
        self.assertIn('configuration indicates', six.text_type(exp))

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_instances_with_cell_down_support(self, mock_sg):
        self.flags(list_records_by_skipping_down_cells=False, group='api')
        inst_cell0 = self.insts[uuids.cell0]
        # storing the uuids of the instances from the up cell
        uuid_initial = [inst['uuid'] for inst in inst_cell0]

        def wrap(thing):
            return multi_cell_list.RecordWrapper(ctx, self.context, thing)

        ctx = nova_context.RequestContext()
        instances = [wrap(inst) for inst in inst_cell0]

        # creating one up cell and two down cells
        ret_val = {}
        ret_val[uuids.cell0] = instances
        ret_val[uuids.cell1] = [wrap(exception.BuildRequestNotFound(uuid='f'))]
        ret_val[uuids.cell2] = [wrap(nova_context.did_not_respond_sentinel)]
        mock_sg.return_value = ret_val

        # From the new microversion (2.68) if cell_down_support is True
        # then CONF.api.list_records_by_skipping_down_cells will be ignored.
        # Exception will not be raised even if its False.
        obj, res = instance_list.get_instances_sorted(self.context, {}, None,
                                                      None, [], None, None,
                                                      cell_down_support=True)

        uuid_final = [inst['uuid'] for inst in res]

        # return the results from the up cell, ignoring the down cell and
        # constructing partial results later.
        self.assertEqual(uuid_initial, uuid_final)

    def test_batch_size_fixed(self):
        fixed_size = 200
        self.flags(instance_list_cells_batch_strategy='fixed', group='api')
        self.flags(instance_list_cells_batch_fixed_size=fixed_size,
                   group='api')

        # We call the batch size calculator with various arguments, including
        # lists of cells which are just counted, so the cardinality is all that
        # matters.

        # One cell, so batch at $limit
        ret = instance_list.get_instance_list_cells_batch_size(
            1000, [mock.sentinel.cell1])
        self.assertEqual(1000, ret)

        # Two cells, so batch at $fixed_size
        ret = instance_list.get_instance_list_cells_batch_size(
            1000, [mock.sentinel.cell1, mock.sentinel.cell2])

        self.assertEqual(fixed_size, ret)

        # Four cells, so batch at $fixed_size
        ret = instance_list.get_instance_list_cells_batch_size(
            1000, [mock.sentinel.cell1, mock.sentinel.cell2,
                   mock.sentinel.cell3, mock.sentinel.cell4])
        self.assertEqual(fixed_size, ret)

        # Three cells, tiny limit, so batch at lower threshold
        ret = instance_list.get_instance_list_cells_batch_size(
            10, [mock.sentinel.cell1,
                 mock.sentinel.cell2,
                 mock.sentinel.cell3])
        self.assertEqual(100, ret)

        # Three cells, limit above floor, so batch at limit
        ret = instance_list.get_instance_list_cells_batch_size(
            110, [mock.sentinel.cell1,
                  mock.sentinel.cell2,
                  mock.sentinel.cell3])
        self.assertEqual(110, ret)

    def test_batch_size_distributed(self):
        self.flags(instance_list_cells_batch_strategy='distributed',
                   group='api')

        # One cell, so batch at $limit
        ret = instance_list.get_instance_list_cells_batch_size(1000, [1])
        self.assertEqual(1000, ret)

        # Two cells so batch at ($limit/2)+10%
        ret = instance_list.get_instance_list_cells_batch_size(1000, [1, 2])
        self.assertEqual(550, ret)

        # Four cells so batch at ($limit/4)+10%
        ret = instance_list.get_instance_list_cells_batch_size(1000, [1, 2,
                                                                      3, 4])
        self.assertEqual(275, ret)

        # Three cells, tiny limit, so batch at lower threshold
        ret = instance_list.get_instance_list_cells_batch_size(10, [1, 2, 3])
        self.assertEqual(100, ret)

        # Three cells, small limit, so batch at lower threshold
        ret = instance_list.get_instance_list_cells_batch_size(110, [1, 2, 3])
        self.assertEqual(100, ret)

        # No cells, so batch at $limit
        ret = instance_list.get_instance_list_cells_batch_size(1000, [])
        self.assertEqual(1000, ret)


class TestInstanceListBig(test.NoDBTestCase):
    def setUp(self):
        super(TestInstanceListBig, self).setUp()

        cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                     name='cell%i' % i,
                                     transport_url='fake:///',
                                     database_connection='fake://')
                 for i in range(0, 3)]

        insts = list([
            dict(
                uuid=getattr(uuids, 'inst%i' % i),
                hostname='inst%i' % i)
            for i in range(0, 100)])

        self.cells = cells
        self.insts = insts
        self.context = nova_context.RequestContext()
        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    @mock.patch('nova.db.api.instance_get_all_by_filters_sort')
    @mock.patch('nova.objects.CellMappingList.get_all')
    def test_get_instances_batched(self, mock_cells, mock_inst):
        mock_cells.return_value = self.cells

        def fake_get_insts(ctx, filters, limit, *a, **k):
            for i in range(0, limit):
                yield self.insts.pop()

        mock_inst.side_effect = fake_get_insts
        obj, insts = instance_list.get_instances_sorted(self.context, {},
                                                        50, None, [],
                                                        ['hostname'], ['desc'],
                                                        batch_size=10)

        # Make sure we returned exactly how many were requested
        insts = list(insts)
        self.assertEqual(50, len(insts))

        # Since the instances are all uniform, we should have a
        # predictable number of queries to the database. 5 queries
        # would get us 50 results, plus one more gets triggered by the
        # sort to fill the buffer for the first cell feeder that runs
        # dry.
        self.assertEqual(6, mock_inst.call_count)

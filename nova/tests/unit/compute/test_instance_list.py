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

from nova.compute import instance_list
from nova.compute import multi_cell_list
from nova import context as nova_context
from nova import objects
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel as uuids


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
        self.context = mock.sentinel.context
        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    def test_compare_simple_instance_quirks(self):
        # Ensure uuid,asc is added
        ctx = instance_list.InstanceSortContext(['key0'], ['asc'])
        self.assertEqual(['key0', 'uuid'], ctx.sort_keys)
        self.assertEqual(['asc', 'asc'], ctx.sort_dirs)

        # Ensure defaults are added
        ctx = instance_list.InstanceSortContext(None, None)
        self.assertEqual(['created_at', 'id', 'uuid'], ctx.sort_keys)
        self.assertEqual(['desc', 'desc', 'asc'], ctx.sort_dirs)

    @mock.patch('nova.db.instance_get_all_by_filters_sort')
    @mock.patch('nova.objects.CellMappingList.get_all')
    def test_get_instances_sorted(self, mock_cells, mock_inst):
        mock_cells.return_value = self.cells
        insts_by_cell = self.insts.values()

        mock_inst.side_effect = insts_by_cell
        insts = instance_list.get_instances_sorted(self.context, {},
                                                   None, None,
                                                   [], ['hostname'], ['asc'])
        insts_one = [inst['hostname'] for inst in insts]

        # Reverse the order that we get things from the cells so we can
        # make sure that the result is still sorted the same way
        insts_by_cell = list(reversed(list(insts_by_cell)))
        mock_inst.reset_mock()
        mock_inst.side_effect = insts_by_cell

        insts = instance_list.get_instances_sorted(self.context, {},
                                                   None, None,
                                                   [], ['hostname'], ['asc'])
        insts_two = [inst['hostname'] for inst in insts]

        self.assertEqual(insts_one, insts_two)

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_instances_with_down_cells(self, mock_sg):
        inst_cell0 = self.insts[uuids.cell0]
        # storing the uuids of the instances from the up cell
        uuid_initial = [inst['uuid'] for inst in inst_cell0]

        instances = (multi_cell_list.RecordWrapper(self.context, inst)
                     for inst in inst_cell0)

        # creating one up cell and two down cells
        ret_val = {}
        ret_val[uuids.cell0] = instances
        ret_val[uuids.cell1] = nova_context.raised_exception_sentinel
        ret_val[uuids.cell2] = nova_context.did_not_respond_sentinel
        mock_sg.return_value = ret_val

        res = instance_list.get_instances_sorted(self.context, {}, None, None,
                                                 [], None, None)

        uuid_final = [inst['uuid'] for inst in res]

        # return the results from the up cell, ignoring the down cell.
        self.assertEqual(uuid_initial, uuid_final)

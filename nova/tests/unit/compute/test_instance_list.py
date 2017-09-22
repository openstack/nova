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

import datetime
import mock

from nova.compute import instance_list
from nova import objects
from nova import test
from nova.tests import fixtures
from nova.tests import uuidsentinel as uuids


class TestUtils(test.NoDBTestCase):
    def test_compare_simple(self):
        dt1 = datetime.datetime(2015, 11, 5, 20, 30, 00)
        dt2 = datetime.datetime(1955, 10, 25, 1, 21, 00)

        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456, 'key4': dt1}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123, 'key4': dt2}

        # Equal key0, inst == inst2
        ctx = instance_list.InstanceSortContext(['key0'], ['asc'])
        self.assertEqual(0, ctx.compare_instances(inst1, inst2))

        # Equal key0, inst == inst2 (direction should not matter)
        ctx = instance_list.InstanceSortContext(['key0'], ['desc'])
        self.assertEqual(0, ctx.compare_instances(inst1, inst2))

        # Ascending by key1, inst1 < inst2
        ctx = instance_list.InstanceSortContext(['key1'], ['asc'])
        self.assertEqual(-1, ctx.compare_instances(inst1, inst2))

        # Descending by key1, inst2 < inst1
        ctx = instance_list.InstanceSortContext(['key1'], ['desc'])
        self.assertEqual(1, ctx.compare_instances(inst1, inst2))

        # Ascending by key2, inst2 < inst1
        ctx = instance_list.InstanceSortContext(['key2'], ['asc'])
        self.assertEqual(1, ctx.compare_instances(inst1, inst2))

        # Descending by key2, inst1 < inst2
        ctx = instance_list.InstanceSortContext(['key2'], ['desc'])
        self.assertEqual(-1, ctx.compare_instances(inst1, inst2))

        # Ascending by key4, inst1 > inst2
        ctx = instance_list.InstanceSortContext(['key4'], ['asc'])
        self.assertEqual(1, ctx.compare_instances(inst1, inst2))

        # Descending by key4, inst1 < inst2
        ctx = instance_list.InstanceSortContext(['key4'], ['desc'])
        self.assertEqual(-1, ctx.compare_instances(inst1, inst2))

    def test_compare_multiple(self):
        # key0 should not affect ordering, but key1 should

        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123}

        # Should be equivalent to ascending by key1
        ctx = instance_list.InstanceSortContext(['key0', 'key1'],
                                                ['asc', 'asc'])
        self.assertEqual(-1, ctx.compare_instances(inst1, inst2))

        # Should be equivalent to descending by key1
        ctx = instance_list.InstanceSortContext(['key0', 'key1'],
                                                ['asc', 'desc'])
        self.assertEqual(1, ctx.compare_instances(inst1, inst2))

    def test_wrapper(self):
        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123}

        # Should sort by key1
        ctx = instance_list.InstanceSortContext(['key0', 'key1'],
                                                ['asc', 'asc'])
        iw1 = instance_list.InstanceWrapper(ctx, inst1)
        iw2 = instance_list.InstanceWrapper(ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 < iw2)
        self.assertFalse(iw2 < iw1)

        # Should sort reverse by key1
        ctx = instance_list.InstanceSortContext(['key0', 'key1'],
                                                ['asc', 'desc'])
        iw1 = instance_list.InstanceWrapper(ctx, inst1)
        iw2 = instance_list.InstanceWrapper(ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 > iw2)
        self.assertFalse(iw2 > iw1)


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

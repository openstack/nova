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

from nova.compute import multi_cell_list
from nova import test


class TestUtils(test.NoDBTestCase):
    def test_compare_simple(self):
        dt1 = datetime.datetime(2015, 11, 5, 20, 30, 00)
        dt2 = datetime.datetime(1955, 10, 25, 1, 21, 00)

        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456, 'key4': dt1}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123, 'key4': dt2}

        # Equal key0, inst == inst2
        ctx = multi_cell_list.RecordSortContext(['key0'], ['asc'])
        self.assertEqual(0, ctx.compare_records(inst1, inst2))

        # Equal key0, inst == inst2 (direction should not matter)
        ctx = multi_cell_list.RecordSortContext(['key0'], ['desc'])
        self.assertEqual(0, ctx.compare_records(inst1, inst2))

        # Ascending by key1, inst1 < inst2
        ctx = multi_cell_list.RecordSortContext(['key1'], ['asc'])
        self.assertEqual(-1, ctx.compare_records(inst1, inst2))

        # Descending by key1, inst2 < inst1
        ctx = multi_cell_list.RecordSortContext(['key1'], ['desc'])
        self.assertEqual(1, ctx.compare_records(inst1, inst2))

        # Ascending by key2, inst2 < inst1
        ctx = multi_cell_list.RecordSortContext(['key2'], ['asc'])
        self.assertEqual(1, ctx.compare_records(inst1, inst2))

        # Descending by key2, inst1 < inst2
        ctx = multi_cell_list.RecordSortContext(['key2'], ['desc'])
        self.assertEqual(-1, ctx.compare_records(inst1, inst2))

        # Ascending by key4, inst1 > inst2
        ctx = multi_cell_list.RecordSortContext(['key4'], ['asc'])
        self.assertEqual(1, ctx.compare_records(inst1, inst2))

        # Descending by key4, inst1 < inst2
        ctx = multi_cell_list.RecordSortContext(['key4'], ['desc'])
        self.assertEqual(-1, ctx.compare_records(inst1, inst2))

    def test_compare_multiple(self):
        # key0 should not affect ordering, but key1 should

        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123}

        # Should be equivalent to ascending by key1
        ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                ['asc', 'asc'])
        self.assertEqual(-1, ctx.compare_records(inst1, inst2))

        # Should be equivalent to descending by key1
        ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                ['asc', 'desc'])
        self.assertEqual(1, ctx.compare_records(inst1, inst2))

    def test_wrapper(self):
        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456}
        inst2 = {'key0': 'foo', 'key1': 's', 'key2': 123}

        # Should sort by key1
        ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                ['asc', 'asc'])
        iw1 = multi_cell_list.RecordWrapper(ctx, inst1)
        iw2 = multi_cell_list.RecordWrapper(ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 < iw2)
        self.assertFalse(iw2 < iw1)

        # Should sort reverse by key1
        ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                ['asc', 'desc'])
        iw1 = multi_cell_list.RecordWrapper(ctx, inst1)
        iw2 = multi_cell_list.RecordWrapper(ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 > iw2)
        self.assertFalse(iw2 > iw1)

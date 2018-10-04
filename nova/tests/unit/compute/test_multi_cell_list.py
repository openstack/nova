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

from contextlib import contextmanager
import copy
import datetime
import mock
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import multi_cell_list
from nova import context
from nova import exception
from nova import objects
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

        ctx = context.RequestContext()
        ctx.cell_uuid = uuids.cell

        # Should sort by key1
        sort_ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                     ['asc', 'asc'])
        iw1 = multi_cell_list.RecordWrapper(ctx, sort_ctx, inst1)
        iw2 = multi_cell_list.RecordWrapper(ctx, sort_ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 < iw2)
        self.assertFalse(iw2 < iw1)

        # Should sort reverse by key1
        sort_ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                     ['asc', 'desc'])
        iw1 = multi_cell_list.RecordWrapper(ctx, sort_ctx, inst1)
        iw2 = multi_cell_list.RecordWrapper(ctx, sort_ctx, inst2)
        # Check this both ways to make sure we're comparing against -1
        # and not just nonzero return from cmp()
        self.assertTrue(iw1 > iw2)
        self.assertFalse(iw2 > iw1)

        # Make sure we can tell which cell a request came from
        self.assertEqual(uuids.cell, iw1.cell_uuid)

    def test_wrapper_sentinels(self):
        inst1 = {'key0': 'foo', 'key1': 'd', 'key2': 456}

        ctx = context.RequestContext()
        ctx.cell_uuid = uuids.cell

        sort_ctx = multi_cell_list.RecordSortContext(['key0', 'key1'],
                                                     ['asc', 'asc'])
        iw1 = multi_cell_list.RecordWrapper(ctx, sort_ctx, inst1)

        # Wrappers with sentinels
        iw2 = multi_cell_list.RecordWrapper(ctx, sort_ctx,
                                            context.did_not_respond_sentinel)
        iw3 = multi_cell_list.RecordWrapper(ctx, sort_ctx,
                                            exception.InstanceNotFound(
                                                instance_id='fake'))

        # NOTE(danms): The sentinel wrappers always win
        self.assertTrue(iw2 < iw1)
        self.assertTrue(iw3 < iw1)
        self.assertFalse(iw1 < iw2)
        self.assertFalse(iw1 < iw3)

        # NOTE(danms): Comparing two wrappers with sentinels will always return
        # True for less-than because we're just naive about always favoring the
        # left hand side. This is fine for our purposes but put it here to make
        # it explicit.
        self.assertTrue(iw2 < iw3)
        self.assertTrue(iw3 < iw2)

    def test_query_wrapper_success(self):
        def test(ctx, data):
            for thing in data:
                yield thing

        self.assertEqual([1, 2, 3],
                         list(multi_cell_list.query_wrapper(
                             None, test, [1, 2, 3])))

    def test_query_wrapper_timeout(self):
        def test(ctx):
            raise exception.CellTimeout

        self.assertEqual([context.did_not_respond_sentinel],
                         [x._db_record for x in
                          multi_cell_list.query_wrapper(
                              mock.MagicMock(), test)])

    def test_query_wrapper_fail(self):
        def tester(ctx):
            raise test.TestingException

        self.assertIsInstance(
            # query_wrapper is a generator so we convert to a list and
            # check the type on the first and only result
            [x._db_record for x in multi_cell_list.query_wrapper(
                mock.MagicMock(), tester)][0],
            test.TestingException)


class TestListContext(multi_cell_list.RecordSortContext):
    def compare_records(self, rec1, rec2):
        return -1


class TestLister(multi_cell_list.CrossCellLister):
    CONTEXT_CLS = TestListContext

    def __init__(self, data, sort_keys, sort_dirs,
                 cells=None, batch_size=None):
        self._data = data
        self._count_by_cell = {}
        super(TestLister, self).__init__(self.CONTEXT_CLS(sort_keys,
                                                          sort_dirs),
                                         cells=cells, batch_size=batch_size)

    @property
    def marker_identifier(self):
        return 'id'

    def _method_called(self, ctx, method, arg):
        self._count_by_cell.setdefault(ctx.cell_uuid, {})
        self._count_by_cell[ctx.cell_uuid].setdefault(method, [])
        self._count_by_cell[ctx.cell_uuid][method].append(arg)

    def call_summary(self, method):
        results = {
            'total': 0,
            'count_by_cell': [],
            'limit_by_cell': [],
            'total_by_cell': [],
            'called_in_cell': [],
        }
        for i, cell in enumerate(self._count_by_cell):
            if method not in self._count_by_cell[cell]:
                continue
            results['total'] += len(self._count_by_cell[cell][method])
            # List of number of calls in each cell
            results['count_by_cell'].append(
                len(self._count_by_cell[cell][method]))
            # List of limits used in calls to each cell
            results['limit_by_cell'].append(
                self._count_by_cell[cell][method])
            try:
                # List of total results fetched from each cell
                results['total_by_cell'].append(sum(
                    self._count_by_cell[cell][method]))
            except TypeError:
                # Don't do this for non-integer args
                pass
            results['called_in_cell'].append(cell)
        results['count_by_cell'].sort()
        results['limit_by_cell'].sort()
        results['total_by_cell'].sort()
        results['called_in_cell'].sort()
        return results

    def get_marker_record(self, ctx, marker):
        self._method_called(ctx, 'get_marker_record', marker)
        # Always assume this came from the second cell
        cell = self.cells[1]
        return cell.uuid, self._data[0]

    def get_marker_by_values(self, ctx, values):
        self._method_called(ctx, 'get_marker_by_values', values)
        return self._data[0]

    def get_by_filters(self, ctx, filters, limit, marker, **kwargs):
        self._method_called(ctx, 'get_by_filters', limit)
        if 'batch_size' in kwargs:
            count = min(kwargs['batch_size'], limit)
        else:
            count = limit
        batch = self._data[:count]
        self._data = self._data[count:]
        return batch


@contextmanager
def target_cell_cheater(context, target_cell):
    # In order to help us do accounting, we need to mimic the real
    # behavior where at least cell_uuid gets set on the context, which
    # doesn't happen in the simple test fixture.
    context = copy.deepcopy(context)
    context.cell_uuid = target_cell.uuid
    yield context


@mock.patch('nova.context.target_cell', new=target_cell_cheater)
class TestBatching(test.NoDBTestCase):
    def setUp(self):
        super(TestBatching, self).setUp()

        self._data = [{'id': 'foo-%i' % i}
                      for i in range(0, 1000)]
        self._cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                           name='cell%i' % i)
                       for i in range(0, 10)]

    def test_batches_not_needed(self):
        lister = TestLister(self._data, [], [],
                            cells=self._cells, batch_size=10)
        ctx = context.RequestContext()
        res = list(lister.get_records_sorted(ctx, {}, 5, None))
        self.assertEqual(5, len(res))
        summary = lister.call_summary('get_by_filters')
        # We only needed one batch per cell to hit the total,
        # so we should have the same number of calls as cells
        self.assertEqual(len(self._cells), summary['total'])
        # One call per cell, hitting all cells
        self.assertEqual(len(self._cells), len(summary['count_by_cell']))
        self.assertTrue(all([
            cell_count == 1 for cell_count in summary['count_by_cell']]))

    def test_batches(self):
        lister = TestLister(self._data, [], [],
                            cells=self._cells, batch_size=10)
        ctx = context.RequestContext()
        res = list(lister.get_records_sorted(ctx, {}, 500, None))
        self.assertEqual(500, len(res))
        summary = lister.call_summary('get_by_filters')

        # Since we got everything from one cell (due to how things are sorting)
        # we should have made 500 / 10 calls to one cell, and 1 call to
        # the rest
        calls_expected = [1 for cell in self._cells[1:]] + [500 / 10]
        self.assertEqual(calls_expected, summary['count_by_cell'])

        # Since we got everything from one cell (due to how things are sorting)
        # we should have received 500 from one cell and 10 from the rest
        count_expected = [10 for cell in self._cells[1:]] + [500]
        self.assertEqual(count_expected, summary['total_by_cell'])

        # Since we got everything from one cell (due to how things are sorting)
        # we should have a bunch of calls for batches of 10, one each for
        # every cell except the one that served the bulk of the requests which
        # should have 500 / 10 batches of 10.
        limit_expected = ([[10] for cell in self._cells[1:]] +
                          [[10 for i in range(0, 500 // 10)]])
        self.assertEqual(limit_expected, summary['limit_by_cell'])

    def test_no_batches(self):
        lister = TestLister(self._data, [], [],
                            cells=self._cells)
        ctx = context.RequestContext()
        res = list(lister.get_records_sorted(ctx, {}, 50, None))
        self.assertEqual(50, len(res))
        summary = lister.call_summary('get_by_filters')

        # Since we used no batches we should have one call per cell
        calls_expected = [1 for cell in self._cells]
        self.assertEqual(calls_expected, summary['count_by_cell'])

        # Since we used no batches, each cell should have returned 50 results
        count_expected = [50 for cell in self._cells]
        self.assertEqual(count_expected, summary['total_by_cell'])

        # Since we used no batches, each cell call should be for $limit
        limit_expected = [[count] for count in count_expected]
        self.assertEqual(limit_expected, summary['limit_by_cell'])


class FailureListContext(multi_cell_list.RecordSortContext):
    def compare_records(self, rec1, rec2):
        return 0


class FailureLister(TestLister):
    CONTEXT_CLS = FailureListContext

    def __init__(self, *a, **k):
        super(FailureLister, self).__init__(*a, **k)
        self._fails = {}

    def set_fails(self, cell, fails):
        self._fails[cell] = fails

    def get_by_filters(self, ctx, *a, **k):
        try:
            action = self._fails[ctx.cell_uuid].pop(0)
        except (IndexError, KeyError):
            action = None

        if action == context.did_not_respond_sentinel:
            raise exception.CellTimeout
        elif isinstance(action, Exception):
            raise test.TestingException
        else:
            return super(FailureLister, self).get_by_filters(ctx, *a, **k)


@mock.patch('nova.context.target_cell', new=target_cell_cheater)
class TestBaseClass(test.NoDBTestCase):
    def test_with_failing_cells(self):
        data = [{'id': 'foo-%i' % i} for i in range(0, 100)]
        cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                     name='cell%i' % i)
                 for i in range(0, 3)]

        lister = FailureLister(data, [], [], cells=cells)
        # Two of the cells will fail, one with timeout and one
        # with an error
        lister.set_fails(uuids.cell0, [context.did_not_respond_sentinel])
        # Note that InstanceNotFound exception will never appear during
        # instance listing, the aim is to only simulate a situation where
        # there could be some type of exception arising.
        lister.set_fails(uuids.cell1, exception.InstanceNotFound(
            instance_id='fake'))
        ctx = context.RequestContext()
        result = lister.get_records_sorted(ctx, {}, 50, None, batch_size=10)
        # We should still have 50 results since there are enough from the
        # good cells to fill our limit.
        self.assertEqual(50, len(list(result)))
        # Make sure the counts line up
        self.assertEqual(1, len(lister.cells_failed))
        self.assertEqual(1, len(lister.cells_timed_out))
        self.assertEqual(1, len(lister.cells_responded))

    def test_with_failing_middle_cells(self):
        data = [{'id': 'foo-%i' % i} for i in range(0, 100)]
        cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                     name='cell%i' % i)
                 for i in range(0, 3)]

        lister = FailureLister(data, [], [], cells=cells)
        # One cell will succeed and then time out, one will fail immediately,
        # and the last will always work
        lister.set_fails(uuids.cell0, [None, context.did_not_respond_sentinel])
        # Note that BuildAbortException will never appear during instance
        # listing, the aim is to only simulate a situation where there could
        # be some type of exception arising.
        lister.set_fails(uuids.cell1, exception.BuildAbortException(
            instance_uuid='fake', reason='fake'))
        ctx = context.RequestContext()
        result = lister.get_records_sorted(ctx, {}, 50, None,
                                           batch_size=5)
        # We should still have 50 results since there are enough from the
        # good cells to fill our limit.
        self.assertEqual(50, len(list(result)))
        # Make sure the counts line up
        self.assertEqual(1, len(lister.cells_responded))
        self.assertEqual(1, len(lister.cells_failed))
        self.assertEqual(1, len(lister.cells_timed_out))

    def test_marker_cell_not_requeried(self):
        data = [{'id': 'foo-%i' % i} for i in range(0, 100)]
        cells = [objects.CellMapping(uuid=getattr(uuids, 'cell%i' % i),
                                     name='cell%i' % i)
                 for i in range(0, 3)]

        lister = TestLister(data, [], [], cells=cells)
        ctx = context.RequestContext()
        result = list(lister.get_records_sorted(ctx, {}, 10, None))
        result = list(lister.get_records_sorted(ctx, {}, 10, result[-1]['id']))

        # get_marker_record() is called untargeted and its result defines which
        # cell we skip.
        gmr_summary = lister.call_summary('get_marker_record')
        self.assertEqual([None], gmr_summary['called_in_cell'])

        # All cells other than the second one should have been called for
        # a local marker
        gmbv_summary = lister.call_summary('get_marker_by_values')
        self.assertEqual(sorted([cell.uuid for cell in cells
                                 if cell.uuid != uuids.cell1]),
                         gmbv_summary['called_in_cell'])

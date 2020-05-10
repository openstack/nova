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

import abc
import copy
import heapq

import eventlet
from oslo_log import log as logging

import nova.conf
from nova import context
from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class RecordSortContext(object):
    def __init__(self, sort_keys, sort_dirs):
        self.sort_keys = sort_keys
        self.sort_dirs = sort_dirs

    def compare_records(self, rec1, rec2):
        """Implements cmp(rec1, rec2) for the first key that is different.

        Adjusts for the requested sort direction by inverting the result
        as needed.
        """
        for skey, sdir in zip(self.sort_keys, self.sort_dirs):
            resultflag = 1 if sdir == 'desc' else -1
            if rec1[skey] < rec2[skey]:
                return resultflag
            elif rec1[skey] > rec2[skey]:
                return resultflag * -1
        return 0


class RecordWrapper(object):
    """Wrap a DB object from the database so it is sortable.

    We use heapq.merge() below to do the merge sort of things from the
    cell databases. That routine assumes it can use regular python
    operators (> and <) on the contents. Since that won't work with
    instances from the database (and depends on the sort keys/dirs),
    we need this wrapper class to provide that.

    Implementing __lt__ is enough for heapq.merge() to do its work.
    """
    def __init__(self, ctx, sort_ctx, db_record):
        self.cell_uuid = ctx.cell_uuid
        self._sort_ctx = sort_ctx
        self._db_record = db_record

    def __lt__(self, other):
        # NOTE(danms): This makes us always sort failure sentinels
        # higher than actual results. We do this so that they bubble
        # up in the get_records_sorted() feeder loop ahead of anything
        # else, and so that the implementation of RecordSortContext
        # never sees or has to handle the sentinels. If we did not
        # sort these to the top then we could potentially return
        # $limit results from good cells before we noticed the failed
        # cells, and would not properly report them as failed for
        # fix-up in the higher layers.
        if context.is_cell_failure_sentinel(self._db_record):
            return True
        elif context.is_cell_failure_sentinel(other._db_record):
            return False

        r = self._sort_ctx.compare_records(self._db_record,
                                           other._db_record)
        # cmp(x, y) returns -1 if x < y
        return r == -1


def query_wrapper(ctx, fn, *args, **kwargs):
    """This is a helper to run a query with predictable fail semantics.

    This is a generator which will mimic the scatter_gather_cells() behavior
    by honoring a timeout and catching exceptions, yielding the usual
    sentinel objects instead of raising. It wraps these in RecordWrapper
    objects, which will prioritize them to the merge sort, causing them to
    be handled by the main get_objects_sorted() feeder loop quickly and
    gracefully.
    """
    with eventlet.timeout.Timeout(context.CELL_TIMEOUT, exception.CellTimeout):
        try:
            for record in fn(ctx, *args, **kwargs):
                yield record
        except exception.CellTimeout:
            # Here, we yield a RecordWrapper (no sort_ctx needed since
            # we won't call into the implementation's comparison routines)
            # wrapping the sentinel indicating timeout.
            yield RecordWrapper(ctx, None, context.did_not_respond_sentinel)
            return
        except Exception as e:
            # Here, we yield a RecordWrapper (no sort_ctx needed since
            # we won't call into the implementation's comparison routines)
            # wrapping the exception object indicating failure.
            yield RecordWrapper(ctx, None, e.__class__(e.args))
            return


class CrossCellLister(metaclass=abc.ABCMeta):
    """An implementation of a cross-cell efficient lister.

    This primarily provides a listing implementation for fetching
    records from across multiple cells, paginated and sorted
    appropriately.  The external interface is the get_records_sorted()
    method. You should implement this if you need to efficiently list
    your data type from cell databases.

    """
    def __init__(self, sort_ctx, cells=None, batch_size=None):
        self.sort_ctx = sort_ctx
        self.cells = cells
        self.batch_size = batch_size
        self._cells_responded = set()
        self._cells_failed = set()
        self._cells_timed_out = set()

    @property
    def cells_responded(self):
        """A list of uuids representing those cells that returned a successful
        result.
        """
        return list(self._cells_responded)

    @property
    def cells_failed(self):
        """A list of uuids representing those cells that failed to return a
        successful result.
        """
        return list(self._cells_failed)

    @property
    def cells_timed_out(self):
        """A list of uuids representing those cells that timed out while being
        contacted.
        """
        return list(self._cells_timed_out)

    @property
    @abc.abstractmethod
    def marker_identifier(self):
        """Return the name of the property used as the marker identifier.

        For instances (and many other types) this is 'uuid', but could also
        be things like 'id' or anything else used as the marker identifier
        when fetching a page of results.
        """
        pass

    @abc.abstractmethod
    def get_marker_record(self, ctx, marker_id):
        """Get the cell UUID and instance of the marker record by id.

        This needs to look up the marker record in whatever cell it is in
        and return it. It should be populated with values corresponding to
        what is in self.sort_ctx.sort_keys.

        :param ctx: A RequestContext
        :param marker_id: The identifier of the marker to find
        :returns: A tuple of cell_uuid where the marker was found and an
                  instance of the marker from the database
        :raises: MarkerNotFound if the marker does not exist
        """
        pass

    @abc.abstractmethod
    def get_marker_by_values(self, ctx, values):
        """Get the identifier of the marker record by value.

        When we need to paginate across cells, the marker record exists
        in only one of those cells. The rest of the cells must decide on
        a record to be their equivalent marker with which to return the
        next page of results. This must be done by value, based on the
        values of the sort_keys properties on the actual marker, as if
        the results were sorted appropriately and the actual marker existed
        in each cell.

        :param ctx: A RequestContext
        :param values: The values of the sort_keys properties of fhe actual
                       marker instance
        :returns: The identifier of the equivalent marker in the local database
        """
        pass

    @abc.abstractmethod
    def get_by_filters(self, ctx, filters, limit, marker, **kwargs):
        """List records by filters, sorted and paginated.

        This is the standard filtered/sorted list method for the data type
        we are trying to list out of the database. Additional kwargs are
        passsed through.

        :param ctx: A RequestContext
        :param filters: A dict of column=filter items
        :param limit: A numeric limit on the number of results, or None
        :param marker: The marker identifier, or None
        :returns: A list of records
        """
        pass

    def get_records_sorted(self, ctx, filters, limit, marker, **kwargs):
        """Get a cross-cell list of records matching filters.

        This iterates cells in parallel generating a unified and sorted
        list of records as efficiently as possible. It takes care to
        iterate the list as infrequently as possible. We wrap the results
        in RecordWrapper objects so that they are sortable by
        heapq.merge(), which requires that the '<' operator just works.

        Our sorting requirements are encapsulated into the
        RecordSortContext provided to the constructor for this object.

        This function is a generator of records from the database like what you
        would get from instance_get_all_by_filters_sort() in the DB API.

        NOTE: Since we do these in parallel, a nonzero limit will be passed
        to each database query, although the limit will be enforced in the
        output of this function. Meaning, we will still query $limit from each
        database, but only return $limit total results.

        :param cell_down_support: True if the API (and caller) support
                                  returning a minimal instance
                                  construct if the relevant cell is
                                  down. If its True, then the value of
                                  CONF.api.list_records_by_skipping_down_cells
                                  is ignored and if its False, results are
                                  either skipped or erred based on the value of
                                  CONF.api.list_records_by_skipping_down_cells.
        """

        cell_down_support = kwargs.pop('cell_down_support', False)

        if marker:
            # A marker identifier was provided from the API. Call this
            # the 'global' marker as it determines where we start the
            # process across all cells. Look up the record in
            # whatever cell it is in and record the values for the
            # sort keys so we can find the marker instance in each
            # cell (called the 'local' marker).
            global_marker_cell, global_marker_record = self.get_marker_record(
                ctx, marker)
            global_marker_values = [global_marker_record[key]
                                    for key in self.sort_ctx.sort_keys]

        def do_query(cctx):
            """Generate RecordWrapper(record) objects from a cell.

            We do this inside the thread (created by
            scatter_gather_all_cells()) so that we return wrappers and
            avoid having to iterate the combined result list in the
            caller again. This is run against each cell by the
            scatter_gather routine.
            """

            # The local marker is an identifier of a record in a cell
            # that is found by the special method
            # get_marker_by_values(). It should be the next record
            # in order according to the sort provided, but after the
            # marker instance which may have been in another cell.
            local_marker = None

            # Since the regular DB query routines take a marker and assume that
            # the marked record was the last entry of the previous page, we
            # may need to prefix it to our result query if we're not the cell
            # that had the actual marker record.
            local_marker_prefix = []

            marker_id = self.marker_identifier

            if marker:
                if cctx.cell_uuid == global_marker_cell:
                    local_marker = marker
                else:
                    local_marker = self.get_marker_by_values(
                        cctx, global_marker_values)
                if local_marker:
                    if local_marker != marker:
                        # We did find a marker in our cell, but it wasn't
                        # the global marker. Thus, we will use it as our
                        # marker in the main query below, but we also need
                        # to prefix that result with this marker instance
                        # since the result below will not return it and it
                        # has not been returned to the user yet. Note that
                        # we do _not_ prefix the marker instance if our
                        # marker was the global one since that has already
                        # been sent to the user.
                        local_marker_filters = copy.copy(filters)
                        if marker_id not in local_marker_filters:
                            # If an $id filter was provided, it will
                            # have included our marker already if this
                            # instance is desired in the output
                            # set. If it wasn't, we specifically query
                            # for it. If the other filters would have
                            # excluded it, then we'll get an empty set
                            # here and not include it in the output as
                            # expected.
                            local_marker_filters[marker_id] = [local_marker]
                        local_marker_prefix = self.get_by_filters(
                            cctx, local_marker_filters, limit=1, marker=None,
                            **kwargs)
                else:
                    # There was a global marker but everything in our
                    # cell is _before_ that marker, so we return
                    # nothing. If we didn't have this clause, we'd
                    # pass marker=None to the query below and return a
                    # full unpaginated set for our cell.
                    return

            if local_marker_prefix:
                # Per above, if we had a matching marker object, that is
                # the first result we should generate.
                yield RecordWrapper(cctx, self.sort_ctx,
                                    local_marker_prefix[0])

            # If a batch size was provided, use that as the limit per
            # batch. If not, then ask for the entire $limit in a single
            # batch.
            batch_size = self.batch_size or limit

            # Keep track of how many we have returned in all batches
            return_count = 0

            # If limit was unlimited then keep querying batches until
            # we run out of results. Otherwise, query until the total count
            # we have returned exceeds the limit.
            while limit is None or return_count < limit:
                batch_count = 0

                # Do not query a full batch if it would cause our total
                # to exceed the limit
                if limit:
                    query_size = min(batch_size, limit - return_count)
                else:
                    query_size = batch_size

                # Get one batch
                query_result = self.get_by_filters(
                    cctx, filters,
                    limit=query_size or None, marker=local_marker,
                    **kwargs)

                # Yield wrapped results from the batch, counting as we go
                # (to avoid traversing the list to count). Also, update our
                # local_marker each time so that local_marker is the end of
                # this batch in order to find the next batch.
                for item in query_result:
                    local_marker = item[self.marker_identifier]
                    yield RecordWrapper(cctx, self.sort_ctx, item)
                    batch_count += 1

                # No results means we are done for this cell
                if not batch_count:
                    break

                return_count += batch_count
                LOG.debug(('Listed batch of %(batch)i results from cell '
                           'out of %(limit)s limit. Returned %(total)i '
                           'total so far.'),
                          {'batch': batch_count,
                           'total': return_count,
                           'limit': limit or 'no'})

        # NOTE(danms): The calls to do_query() will return immediately
        # with a generator. There is no point in us checking the
        # results for failure or timeout since we have not actually
        # run any code in do_query() until the first iteration
        # below. The query_wrapper() utility handles inline
        # translation of failures and timeouts to sentinels which will
        # be generated and consumed just like any normal result below.
        if self.cells:
            results = context.scatter_gather_cells(ctx, self.cells,
                                                   context.CELL_TIMEOUT,
                                                   query_wrapper, do_query)
        else:
            results = context.scatter_gather_all_cells(ctx,
                                                       query_wrapper, do_query)

        # If a limit was provided, it was passed to the per-cell query
        # routines.  That means we have NUM_CELLS * limit items across
        # results. So, we need to consume from that limit below and
        # stop returning results. Call that total_limit since we will
        # modify it in the loop below, but do_query() above also looks
        # at the original provided limit.
        total_limit = limit or 0

        # Generate results from heapq so we can return the inner
        # instance instead of the wrapper. This is basically free
        # as it works as our caller iterates the results.
        feeder = heapq.merge(*results.values())
        while True:
            try:
                item = next(feeder)
            except StopIteration:
                return

            if context.is_cell_failure_sentinel(item._db_record):
                if (not CONF.api.list_records_by_skipping_down_cells and
                        not cell_down_support):
                    # Value the config
                    # ``CONF.api.list_records_by_skipping_down_cells`` only if
                    # cell_down_support is False and generate the exception
                    # if CONF.api.list_records_by_skipping_down_cells is False.
                    # In all other cases the results from the down cell should
                    # be skipped now to either construct minimal constructs
                    # later if cell_down_support is True or to simply return
                    # the skipped results if cell_down_support is False.
                    raise exception.NovaException(
                        _('Cell %s is not responding but configuration '
                          'indicates that we should fail.')
                          % item.cell_uuid)
                LOG.warning('Cell %s is not responding and hence is '
                            'being omitted from the results',
                            item.cell_uuid)
                if item._db_record == context.did_not_respond_sentinel:
                    self._cells_timed_out.add(item.cell_uuid)
                elif isinstance(item._db_record, Exception):
                    self._cells_failed.add(item.cell_uuid)
                # We might have received one batch but timed out or failed
                # on a later one, so be sure we fix the accounting.
                if item.cell_uuid in self._cells_responded:
                    self._cells_responded.remove(item.cell_uuid)
                continue

            yield item._db_record
            self._cells_responded.add(item.cell_uuid)
            total_limit -= 1
            if total_limit == 0:
                # We'll only hit this if limit was nonzero and we just
                # generated our last one
                return

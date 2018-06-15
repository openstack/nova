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
import itertools

import six

from oslo_log import log as logging

from nova import context

LOG = logging.getLogger(__name__)


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
    def __init__(self, sort_ctx, db_record):
        self._sort_ctx = sort_ctx
        self._db_record = db_record

    def __lt__(self, other):
        r = self._sort_ctx.compare_records(self._db_record,
                                           other._db_record)
        # cmp(x, y) returns -1 if x < y
        return r == -1


@six.add_metaclass(abc.ABCMeta)
class CrossCellLister(object):
    """An implementation of a cross-cell efficient lister.

    This primarily provides a listing implementation for fetching
    records from across all cells, paginated and sorted appropriately.
    The external interface is the get_records_sorted() method. You should
    implement this if you need to efficiently list your data type from
    cell databases.
    """
    def __init__(self, sort_ctx):
        self.sort_ctx = sort_ctx

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
        """Get an instance of the marker record by id.

        This needs to look up the marker record in whatever cell it is in
        and return it. It should be populated with values corresponding to
        what is in self.sort_ctx.sort_keys.

        :param ctx: A RequestContext
        :param marker_id: The identifier of the marker to find
        :returns: An instance of the marker from the database
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

        """

        if marker:
            # A marker identifier was provided from the API. Call this
            # the 'global' marker as it determines where we start the
            # process across all cells. Look up the record in
            # whatever cell it is in and record the values for the
            # sort keys so we can find the marker instance in each
            # cell (called the 'local' marker).
            global_marker_record = self.get_marker_record(ctx, marker)
            global_marker_values = [global_marker_record[key]
                                    for key in self.sort_ctx.sort_keys]

        def do_query(ctx):
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
                # FIXME(danms): If we knew which cell we were in here, we could
                # avoid looking up the marker again. But, we don't currently.

                local_marker = self.get_marker_by_values(ctx,
                                                         global_marker_values)
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
                            ctx, local_marker_filters, limit=1, marker=None,
                            **kwargs)
                else:
                    # There was a global marker but everything in our
                    # cell is _before_ that marker, so we return
                    # nothing. If we didn't have this clause, we'd
                    # pass marker=None to the query below and return a
                    # full unpaginated set for our cell.
                    return []

            main_query_result = self.get_by_filters(
                ctx, filters,
                limit=limit, marker=local_marker,
                **kwargs)

            return (RecordWrapper(self.sort_ctx, inst) for inst in
                    itertools.chain(local_marker_prefix, main_query_result))

        # NOTE(tssurya): When the below routine provides sentinels to indicate
        # a timeout on a cell, we ignore that cell to avoid the crash when
        # doing the merge below and continue merging the results from the 'up'
        # cells.
        # TODO(tssurya): Modify this to return the minimal available info from
        # the down cells.
        results = context.scatter_gather_all_cells(ctx, do_query)
        for cell_uuid in list(results):
            if results[cell_uuid] in (context.did_not_respond_sentinel,
                                      context.raised_exception_sentinel):
                LOG.warning("Cell %s is not responding and hence skipped "
                            "from the results.", cell_uuid)
                results.pop(cell_uuid)

        # If a limit was provided, it was passed to the per-cell query
        # routines.  That means we have NUM_CELLS * limit items across
        # results. So, we need to consume from that limit below and
        # stop returning results.
        limit = limit or 0

        # Generate results from heapq so we can return the inner
        # instance instead of the wrapper. This is basically free
        # as it works as our caller iterates the results.
        for i in heapq.merge(*results.values()):
            yield i._db_record
            limit -= 1
            if limit == 0:
                # We'll only hit this if limit was nonzero and we just
                # generated our last one
                return

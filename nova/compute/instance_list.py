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

import copy
import heapq
import itertools

from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import instance as instance_obj


class InstanceSortContext(object):
    def __init__(self, sort_keys, sort_dirs):
        self._sort_keys = sort_keys
        self._sort_dirs = sort_dirs

    def compare_instances(self, inst1, inst2):
        """Implements cmp(inst1, inst2) for the first key that is different

        Adjusts for the requested sort direction by inverting the result
        as needed.
        """
        for skey, sdir in zip(self._sort_keys, self._sort_dirs):
            resultflag = 1 if sdir == 'desc' else -1
            if inst1[skey] < inst2[skey]:
                return resultflag
            elif inst1[skey] > inst2[skey]:
                return resultflag * -1
        return 0


class InstanceWrapper(object):
    """Wrap an instance object from the database so it is sortable.

    We use heapq.merge() below to do the merge sort of things from the
    cell databases. That routine assumes it can use regular python
    operators (> and <) on the contents. Since that won't work with
    instances from the database (and depends on the sort keys/dirs),
    we need this wrapper class to provide that.

    Implementing __lt__ is enough for heapq.merge() to do its work.
    """
    def __init__(self, sort_ctx, db_instance):
        self._sort_ctx = sort_ctx
        self._db_instance = db_instance

    def __lt__(self, other):
        r = self._sort_ctx.compare_instances(self._db_instance,
                                             other._db_instance)
        # cmp(x, y) returns -1 if x < y
        return r == -1


def _get_marker_instance(ctx, marker):
    """Get the marker instance from its cell.

    This returns the marker instance from the cell in which it lives
    """

    try:
        im = objects.InstanceMapping.get_by_instance_uuid(ctx, marker)
    except exception.InstanceMappingNotFound:
        raise exception.MarkerNotFound(marker=marker)

    elevated = ctx.elevated(read_deleted='yes')
    with context.target_cell(elevated, im.cell_mapping) as cctx:
        try:
            db_inst = db.instance_get_by_uuid(cctx, marker,
                                              columns_to_join=[])
        except exception.InstanceNotFound:
            raise exception.MarkerNotFound(marker=marker)
    return db_inst


def get_instances_sorted(ctx, filters, limit, marker, columns_to_join,
                         sort_keys, sort_dirs):
    """Get a cross-cell list of instances matching filters.

    This iterates cells in parallel generating a unified and sorted
    list of instances as efficiently as possible. It takes care to
    iterate the list as infrequently as possible. We wrap the results
    in InstanceWrapper objects so that they are sortable by
    heapq.merge(), which requires that the '<' operator just works. We
    encapsulate our sorting requirements into an InstanceSortContext
    which we pass to all of the wrappers so they behave the way we
    want.

    This function is a generator of instances from the database like what you
    would get from instance_get_all_by_filters_sort() in the DB API.

    NOTE: Since we do these in parallel, a nonzero limit will be passed
    to each database query, although the limit will be enforced in the
    output of this function. Meaning, we will still query $limit from each
    database, but only return $limit total results.
    """

    if not sort_keys:
        # This is the default from the process_sort_params() method in
        # the DB API. It doesn't really matter, as this only comes into
        # play if the user didn't ask for a specific ordering, but we
        # use the same scheme for consistency.
        sort_keys = ['created_at', 'id']
        sort_dirs = ['asc', 'asc']

    if 'uuid' not in sort_keys:
        # Historically the default sort includes 'id' (see above), which
        # should give us a stable ordering. Since we're striping across
        # cell databases here, many sort_keys arrangements will yield
        # nothing unique across all the databases to give us a stable
        # ordering, which can mess up expected client pagination behavior.
        # So, throw uuid into the sort_keys at the end if it's not already
        # there to keep us repeatable.
        sort_keys = copy.copy(sort_keys) + ['uuid']
        sort_dirs = copy.copy(sort_dirs) + ['asc']

    sort_ctx = InstanceSortContext(sort_keys, sort_dirs)

    if marker:
        # A marker UUID was provided from the API. Call this the 'global'
        # marker as it determines where we start the process across
        # all cells. Look up the instance in whatever cell it is in and
        # record the values for the sort keys so we can find the marker
        # instance in each cell (called the 'local' marker).
        global_marker_instance = _get_marker_instance(ctx, marker)
        global_marker_values = [global_marker_instance[key]
                                for key in sort_keys]

    def do_query(ctx):
        """Generate InstanceWrapper(Instance) objects from a cell.

        We do this inside the thread (created by
        scatter_gather_all_cells()) so that we return wrappers and
        avoid having to iterate the combined result list in the caller
        again. This is run against each cell by the scatter_gather
        routine.
        """

        # The local marker is a uuid of an instance in a cell that is found
        # by the special method instance_get_by_sort_filters(). It should
        # be the next instance in order according to the sort provided,
        # but after the marker instance which may have been in another cell.
        local_marker = None

        # Since the regular DB query routines take a marker and assume that
        # the marked instance was the last entry of the previous page, we
        # may need to prefix it to our result query if we're not the cell
        # that had the actual marker instance.
        local_marker_prefix = []

        if marker:
            # FIXME(danms): If we knew which cell we were in here, we could
            # avoid looking up the marker again. But, we don't currently.

            local_marker = db.instance_get_by_sort_filters(
                ctx, sort_keys, sort_dirs, global_marker_values)
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
                    if 'uuid' not in local_marker_filters:
                        # If a uuid filter was provided, it will
                        # have included our marker already if this instance
                        # is desired in the output set. If it wasn't, we
                        # specifically query for it. If the other filters would
                        # have excluded it, then we'll get an empty set here
                        # and not include it in the output as expected.
                        local_marker_filters['uuid'] = [local_marker]
                    local_marker_prefix = db.instance_get_all_by_filters_sort(
                        ctx, local_marker_filters, limit=1, marker=None,
                        columns_to_join=columns_to_join,
                        sort_keys=sort_keys,
                        sort_dirs=sort_dirs)
            else:
                # There was a global marker but everything in our cell is
                # _before_ that marker, so we return nothing. If we didn't
                # have this clause, we'd pass marker=None to the query below
                # and return a full unpaginated set for our cell.
                return []

        main_query_result = db.instance_get_all_by_filters_sort(
            ctx, filters,
            limit=limit, marker=local_marker,
            columns_to_join=columns_to_join,
            sort_keys=sort_keys,
            sort_dirs=sort_dirs)

        return (InstanceWrapper(sort_ctx, inst) for inst in
                itertools.chain(local_marker_prefix, main_query_result))

    # FIXME(danms): If we raise or timeout on a cell we need to handle
    # that here gracefully. The below routine will provide sentinels
    # to indicate that, which will crash the merge below, but we don't
    # handle this anywhere yet anyway.
    results = context.scatter_gather_all_cells(ctx, do_query)

    # If a limit was provided, and passed to the per-cell query routines.
    # That means we have NUM_CELLS * limit items across results. So, we
    # need to consume from that limit below and stop returning results.
    limit = limit or 0

    # Generate results from heapq so we can return the inner
    # instance instead of the wrapper. This is basically free
    # as it works as our caller iterates the results.
    for i in heapq.merge(*results.values()):
        yield i._db_instance
        limit -= 1
        if limit == 0:
            # We'll only hit this if limit was nonzero and we just generated
            # our last one
            return


def get_instance_objects_sorted(ctx, filters, limit, marker, expected_attrs,
                                sort_keys, sort_dirs):
    """Same as above, but return an InstanceList."""
    columns_to_join = instance_obj._expected_cols(expected_attrs)
    instance_generator = get_instances_sorted(ctx, filters, limit, marker,
                                              columns_to_join, sort_keys,
                                              sort_dirs)
    if 'fault' in expected_attrs:
        # We join fault above, so we need to make sure we don't ask
        # make_instance_list to do it again for us
        expected_attrs = copy.copy(expected_attrs)
        expected_attrs.remove('fault')
    return instance_obj._make_instance_list(ctx, objects.InstanceList(),
                                            instance_generator,
                                            expected_attrs)

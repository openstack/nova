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

import heapq

from nova import context
from nova import db


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

    FIXME: Make limit work
    FIXME: Make marker work
    """

    if not sort_keys:
        # This is the default from the process_sort_params() method in
        # the DB API. It doesn't really matter, as this only comes into
        # play if the user didn't ask for a specific ordering, but we
        # use the same scheme for consistency.
        sort_keys = ['created_at', 'id']
        sort_dirs = ['asc', 'asc']

    sort_ctx = InstanceSortContext(sort_keys, sort_dirs)

    def do_query(ctx):
        """Generate InstanceWrapper(Instance) objects from a cell.

        We do this inside the thread (created by
        scatter_gather_all_cells()) so that we return wrappers and
        avoid having to iterate the combined result list in the caller
        again. This is run against each cell by the scatter_gather
        routine.
        """

        return (InstanceWrapper(sort_ctx, inst) for inst in
                db.instance_get_all_by_filters_sort(
                    ctx, filters,
                    limit=limit, marker=marker,
                    columns_to_join=columns_to_join,
                    sort_keys=sort_keys,
                sort_dirs=sort_dirs))

    # FIXME(danms): If we raise or timeout on a cell we need to handle
    # that here gracefully. The below routine will provide sentinels
    # to indicate that, which will crash the merge below, but we don't
    # handle this anywhere yet anyway.
    results = context.scatter_gather_all_cells(ctx, do_query)

    # Generate results from heapq so we can return the inner
    # instance instead of the wrapper. This is basically free
    # as it works as our caller iterates the results.
    for i in heapq.merge(*results.values()):
        yield i._db_instance

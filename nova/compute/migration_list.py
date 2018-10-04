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

from nova.compute import multi_cell_list
from nova import context
from nova.db import api as db
from nova import exception
from nova import objects
from nova.objects import base


class MigrationSortContext(multi_cell_list.RecordSortContext):
    def __init__(self, sort_keys, sort_dirs):
        if not sort_keys:
            sort_keys = ['created_at', 'id']
            sort_dirs = ['desc', 'desc']

        if 'uuid' not in sort_keys:
            # Add uuid into the list of sort_keys. Since we're striping
            # across cell databases here, many sort_keys arrangements will
            # yield nothing unique across all the databases to give us a stable
            # ordering, which can mess up expected client pagination behavior.
            # So, throw uuid into the sort_keys at the end if it's not already
            # there to keep us repeatable.
            sort_keys = copy.copy(sort_keys) + ['uuid']
            sort_dirs = copy.copy(sort_dirs) + ['asc']

        super(MigrationSortContext, self).__init__(sort_keys, sort_dirs)


class MigrationLister(multi_cell_list.CrossCellLister):
    def __init__(self, sort_keys, sort_dirs):
        super(MigrationLister, self).__init__(
            MigrationSortContext(sort_keys, sort_dirs))

    @property
    def marker_identifier(self):
        return 'uuid'

    def get_marker_record(self, ctx, marker):
        """Get the marker migration from its cell.

        This returns the marker migration from the cell in which it lives
        """
        results = context.scatter_gather_skip_cell0(
            ctx, db.migration_get_by_uuid, marker)
        db_migration = None
        for result_cell_uuid, result in results.items():
            if not context.is_cell_failure_sentinel(result):
                db_migration = result
                cell_uuid = result_cell_uuid
                break
        if not db_migration:
            raise exception.MarkerNotFound(marker=marker)
        return cell_uuid, db_migration

    def get_marker_by_values(self, ctx, values):
        return db.migration_get_by_sort_filters(ctx,
                                                self.sort_ctx.sort_keys,
                                                self.sort_ctx.sort_dirs,
                                                values)

    def get_by_filters(self, ctx, filters, limit, marker, **kwargs):
        return db.migration_get_all_by_filters(
            ctx, filters, limit=limit, marker=marker,
            sort_keys=self.sort_ctx.sort_keys,
            sort_dirs=self.sort_ctx.sort_dirs)


def get_migration_objects_sorted(ctx, filters, limit, marker,
                                 sort_keys, sort_dirs):
    mig_generator = MigrationLister(sort_keys, sort_dirs).get_records_sorted(
        ctx, filters, limit, marker)
    return base.obj_make_list(ctx, objects.MigrationList(), objects.Migration,
                              mig_generator)

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

from oslo_utils.fixture import uuidsentinel

from nova.compute import migration_list
from nova import context
from nova import exception
from nova import objects
from nova import test


class TestMigrationListObjects(test.TestCase):
    NUMBER_OF_CELLS = 3

    def setUp(self):
        super(TestMigrationListObjects, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.num_migrations = 3
        self.migrations = []

        start = datetime.datetime(1985, 10, 25, 1, 21, 0)

        self.cells = objects.CellMappingList.get_all(self.context)
        # Create three migrations in each of the real cells. Leave the
        # first cell empty to make sure we don't break with an empty
        # one.
        for cell in self.cells[1:]:
            for i in range(0, self.num_migrations):
                with context.target_cell(self.context, cell) as cctx:
                    mig = objects.Migration(cctx,
                                            uuid=getattr(
                                                uuidsentinel,
                                                '%s_mig%i' % (cell.name, i)
                                            ),
                                            created_at=start,
                                            migration_type='resize',
                                            instance_uuid=getattr(
                                                uuidsentinel,
                                                'inst%i' % i)
                                            )
                    mig.create()
                self.migrations.append(mig)

    def test_get_instance_objects_sorted(self):
        filters = {}
        limit = None
        marker = None
        sort_keys = ['uuid']
        sort_dirs = ['asc']
        migs = migration_list.get_migration_objects_sorted(
            self.context, filters, limit, marker,
            sort_keys, sort_dirs)
        found_uuids = [x.uuid for x in migs]
        had_uuids = sorted([x['uuid'] for x in self.migrations])
        self.assertEqual(had_uuids, found_uuids)

    def test_get_instance_objects_sorted_paged(self):
        """Query a full first page and ensure an empty second one.

        This uses created_at which is enforced to be the same across
        each migration by setUp(). This will help make sure we still
        have a stable ordering, even when we only claim to care about
        created_at.
        """
        migp1 = migration_list.get_migration_objects_sorted(
            self.context, {}, None, None,
            ['created_at'], ['asc'])
        self.assertEqual(len(self.migrations), len(migp1))
        migp2 = migration_list.get_migration_objects_sorted(
            self.context, {}, None, migp1[-1]['uuid'],
            ['created_at'], ['asc'])
        self.assertEqual(0, len(migp2))

    def test_get_marker_record_not_found(self):
        marker = uuidsentinel.not_found
        self.assertRaises(exception.MarkerNotFound,
                          migration_list.get_migration_objects_sorted,
                          self.context, {}, None, marker, None, None)

    def test_get_sorted_with_limit(self):
        migs = migration_list.get_migration_objects_sorted(
            self.context, {}, 2, None, ['uuid'], ['asc'])
        uuids = [mig['uuid'] for mig in migs]
        had_uuids = [mig.uuid for mig in self.migrations]
        self.assertEqual(sorted(had_uuids)[:2], uuids)
        self.assertEqual(2, len(uuids))

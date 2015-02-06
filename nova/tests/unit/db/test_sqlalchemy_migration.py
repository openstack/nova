# Copyright 2014 IBM Corp.
#
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

from migrate import UniqueConstraint
from oslo_db.sqlalchemy import utils as db_utils

from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import migration
from nova import test


class TestNullInstanceUuidScanDB(test.TestCase):

    # NOTE(mriedem): Copied from the 267 database migration.
    def downgrade(self, migrate_engine):
        UniqueConstraint('uuid',
                         table=db_utils.get_table(migrate_engine, 'instances'),
                         name='uniq_instances0uuid').drop()
        for table_name in ('instances', 'shadow_instances'):
            table = db_utils.get_table(migrate_engine, table_name)
            table.columns.uuid.alter(nullable=True)

    def setUp(self):
        super(TestNullInstanceUuidScanDB, self).setUp()

        self.engine = db_api.get_engine()
        # When this test runs, we've already run the schema migration to make
        # instances.uuid non-nullable, so we have to alter the table here
        # so we can test against a real database.
        self.downgrade(self.engine)
        # Now create fake entries in the fixed_ips, consoles and
        # instances table where (instance_)uuid is None for testing.
        for table_name in ('fixed_ips', 'instances', 'consoles'):
            table = db_utils.get_table(self.engine, table_name)
            fake_record = {'id': 1}
            table.insert().execute(fake_record)

    def test_db_null_instance_uuid_scan_readonly(self):
        results = migration.db_null_instance_uuid_scan(delete=False)
        self.assertEqual(1, results.get('instances'))
        self.assertEqual(1, results.get('consoles'))
        # The fixed_ips table should be ignored.
        self.assertNotIn('fixed_ips', results)
        # Now pick a random table with an instance_uuid column and show it's
        # in the results but with 0 hits.
        self.assertEqual(0, results.get('instance_info_caches'))
        # Make sure nothing was deleted.
        for table_name in ('fixed_ips', 'instances', 'consoles'):
            table = db_utils.get_table(self.engine, table_name)
            record = table.select(table.c.id == 1).execute().first()
            self.assertIsNotNone(record)

    def test_db_null_instance_uuid_scan_delete(self):
        results = migration.db_null_instance_uuid_scan(delete=True)
        self.assertEqual(1, results.get('instances'))
        self.assertEqual(1, results.get('consoles'))
        # The fixed_ips table should be ignored.
        self.assertNotIn('fixed_ips', results)
        # Now pick a random table with an instance_uuid column and show it's
        # in the results but with 0 hits.
        self.assertEqual(0, results.get('instance_info_caches'))
        # Make sure fixed_ips wasn't touched, but instances and instance_faults
        # records were deleted.
        fixed_ips = db_utils.get_table(self.engine, 'fixed_ips')
        record = fixed_ips.select(fixed_ips.c.id == 1).execute().first()
        self.assertIsNotNone(record)

        consoles = db_utils.get_table(self.engine, 'consoles')
        record = consoles.select(consoles.c.id == 1).execute().first()
        self.assertIsNone(record)

        instances = db_utils.get_table(self.engine, 'instances')
        record = instances.select(instances.c.id == 1).execute().first()
        self.assertIsNone(record)

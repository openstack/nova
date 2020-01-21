# Copyright 2015 IBM Corp.
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

import datetime
import re

from dateutil import parser as dateutil_parser
from oslo_utils import timeutils
from sqlalchemy.dialects import sqlite
from sqlalchemy import func
from sqlalchemy import MetaData
from sqlalchemy import select

from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova.tests.functional import test_servers


class TestDatabaseArchive(test_servers.ServersTestBase):
    """Tests DB API for archiving (soft) deleted records"""

    def setUp(self):
        super(TestDatabaseArchive, self).setUp()
        # TODO(mriedem): pull this out so we can re-use it in
        # test_archive_deleted_rows_fk_constraint
        # SQLite doesn't enforce foreign key constraints without a pragma.
        engine = sqlalchemy_api.get_engine()
        dialect = engine.url.get_dialect()
        if dialect == sqlite.dialect:
            # We're seeing issues with foreign key support in SQLite 3.6.20
            # SQLAlchemy doesn't support it at all with < SQLite 3.6.19
            # It works fine in SQLite 3.7.
            # So return early to skip this test if running SQLite < 3.7
            import sqlite3
            tup = sqlite3.sqlite_version_info
            if tup[0] < 3 or (tup[0] == 3 and tup[1] < 7):
                self.skipTest(
                    'sqlite version too old for reliable SQLA foreign_keys')
            engine.connect().execute("PRAGMA foreign_keys = ON")

    def test_archive_deleted_rows(self):
        # Boots a server, deletes it, and then tries to archive it.
        server = self._create_server()
        server_id = server['id']
        # Assert that there are instance_actions. instance_actions are
        # interesting since we don't soft delete them but they have a foreign
        # key back to the instances table.
        actions = self.api.get_instance_actions(server_id)
        self.assertTrue(len(actions),
                        'No instance actions for server: %s' % server_id)
        self._delete_server(server)
        # Verify we have the soft deleted instance in the database.
        admin_context = context.get_admin_context(read_deleted='yes')
        # This will raise InstanceNotFound if it's not found.
        instance = db.instance_get_by_uuid(admin_context, server_id)
        # Make sure it's soft deleted.
        self.assertNotEqual(0, instance.deleted)
        # Verify we have some system_metadata since we'll check that later.
        self.assertTrue(len(instance.system_metadata),
                        'No system_metadata for instance: %s' % server_id)
        # Now try and archive the soft deleted records.
        results, deleted_instance_uuids, archived = \
            db.archive_deleted_rows(max_rows=100)
        # verify system_metadata was dropped
        self.assertIn('instance_system_metadata', results)
        self.assertEqual(len(instance.system_metadata),
                         results['instance_system_metadata'])
        # Verify that instances rows are dropped
        self.assertIn('instances', results)
        # Verify that instance_actions and actions_event are dropped
        # by the archive
        self.assertIn('instance_actions', results)
        self.assertIn('instance_actions_events', results)
        self.assertEqual(sum(results.values()), archived)

    def test_archive_deleted_rows_with_undeleted_residue(self):
        # Boots a server, deletes it, and then tries to archive it.
        server = self._create_server()
        server_id = server['id']
        # Assert that there are instance_actions. instance_actions are
        # interesting since we don't soft delete them but they have a foreign
        # key back to the instances table.
        actions = self.api.get_instance_actions(server_id)
        self.assertTrue(len(actions),
                        'No instance actions for server: %s' % server_id)
        self._delete_server(server)
        # Verify we have the soft deleted instance in the database.
        admin_context = context.get_admin_context(read_deleted='yes')
        # This will raise InstanceNotFound if it's not found.
        instance = db.instance_get_by_uuid(admin_context, server_id)
        # Make sure it's soft deleted.
        self.assertNotEqual(0, instance.deleted)
        # Undelete the instance_extra record to make sure we delete it anyway
        extra = db.instance_extra_get_by_instance_uuid(admin_context,
                                                       instance.uuid)
        self.assertNotEqual(0, extra.deleted)
        db.instance_extra_update_by_uuid(admin_context, instance.uuid,
                                         {'deleted': 0})
        extra = db.instance_extra_get_by_instance_uuid(admin_context,
                                                       instance.uuid)
        self.assertEqual(0, extra.deleted)
        # Verify we have some system_metadata since we'll check that later.
        self.assertTrue(len(instance.system_metadata),
                        'No system_metadata for instance: %s' % server_id)
        # Now try and archive the soft deleted records.
        results, deleted_instance_uuids, archived = \
            db.archive_deleted_rows(max_rows=100)
        # verify system_metadata was dropped
        self.assertIn('instance_system_metadata', results)
        self.assertEqual(len(instance.system_metadata),
                         results['instance_system_metadata'])
        # Verify that instances rows are dropped
        self.assertIn('instances', results)
        # Verify that instance_actions and actions_event are dropped
        # by the archive
        self.assertIn('instance_actions', results)
        self.assertIn('instance_actions_events', results)
        self.assertEqual(sum(results.values()), archived)

    def _get_table_counts(self):
        engine = sqlalchemy_api.get_engine()
        conn = engine.connect()
        meta = MetaData(engine)
        meta.reflect()
        shadow_tables = sqlalchemy_api._purgeable_tables(meta)
        results = {}
        for table in shadow_tables:
            r = conn.execute(
                select([func.count()]).select_from(table)).fetchone()
            results[table.name] = r[0]
        return results

    def test_archive_then_purge_all(self):
        server = self._create_server()
        server_id = server['id']
        self._delete_server(server)
        results, deleted_ids, archived = db.archive_deleted_rows(max_rows=1000)
        self.assertEqual([server_id], deleted_ids)

        lines = []

        def status(msg):
            lines.append(msg)

        admin_context = context.get_admin_context()
        deleted = sqlalchemy_api.purge_shadow_tables(admin_context,
                                                     None, status_fn=status)
        self.assertNotEqual(0, deleted)
        self.assertNotEqual(0, len(lines))
        self.assertEqual(sum(results.values()), archived)
        for line in lines:
            self.assertIsNotNone(re.match(r'Deleted [1-9][0-9]* rows from .*',
                                          line))

        results = self._get_table_counts()
        # No table should have any rows
        self.assertFalse(any(results.values()))

    def test_archive_then_purge_by_date(self):
        server = self._create_server()
        server_id = server['id']
        self._delete_server(server)
        results, deleted_ids, archived = db.archive_deleted_rows(max_rows=1000)
        self.assertEqual([server_id], deleted_ids)
        self.assertEqual(sum(results.values()), archived)

        pre_purge_results = self._get_table_counts()

        past = timeutils.utcnow() - datetime.timedelta(hours=1)
        admin_context = context.get_admin_context()
        deleted = sqlalchemy_api.purge_shadow_tables(admin_context,
                                                     past)
        # Make sure we didn't delete anything if the marker is before
        # we started
        self.assertEqual(0, deleted)

        results = self._get_table_counts()
        # Nothing should be changed if we didn't purge anything
        self.assertEqual(pre_purge_results, results)

        future = timeutils.utcnow() + datetime.timedelta(hours=1)
        deleted = sqlalchemy_api.purge_shadow_tables(admin_context, future)
        # Make sure we deleted things when the marker is after
        # we started
        self.assertNotEqual(0, deleted)

        results = self._get_table_counts()
        # There should be no rows in any table if we purged everything
        self.assertFalse(any(results.values()))

    def test_purge_with_real_date(self):
        """Make sure the result of dateutil's parser works with the
           query we're making to sqlalchemy.
        """
        server = self._create_server()
        server_id = server['id']
        self._delete_server(server)
        results, deleted_ids, archived = db.archive_deleted_rows(max_rows=1000)
        self.assertEqual([server_id], deleted_ids)
        date = dateutil_parser.parse('oct 21 2015', fuzzy=True)
        admin_context = context.get_admin_context()
        deleted = sqlalchemy_api.purge_shadow_tables(admin_context, date)
        self.assertEqual(0, deleted)
        self.assertEqual(sum(results.values()), archived)

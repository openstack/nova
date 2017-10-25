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

from sqlalchemy.dialects import sqlite

from nova import context
from nova import db
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova.tests.functional import test_servers
from nova.tests.unit import fake_network


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

    def _create_server(self):
        """Creates a minimal test server via the compute API

        Ensures the server is created and can be retrieved from the compute API
        and waits for it to be ACTIVE.

        :returns: created server (dict)
        """
        # TODO(mriedem): We should pull this up into the parent class so we
        # don't have so much copy/paste in these functional tests.
        fake_network.set_stub_network_methods(self)

        # Create a server
        server = self._build_minimal_create_server_request()
        created_server = self.api.post_server({'server': server})
        self.assertTrue(created_server['id'])
        created_server_id = created_server['id']

        # Check it's there
        found_server = self.api.get_server(created_server_id)
        self.assertEqual(created_server_id, found_server['id'])

        found_server = self._wait_for_state_change(found_server, 'BUILD')
        # It should be available...
        self.assertEqual('ACTIVE', found_server['status'])
        return found_server

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
        self._delete_server(server_id)
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
        results, deleted_instance_uuids = db.archive_deleted_rows(max_rows=100)
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
        self._delete_server(server_id)
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
        results, deleted_instance_uuids = db.archive_deleted_rows(max_rows=100)
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

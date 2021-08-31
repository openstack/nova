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
        self.enforce_fk_constraints()

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
        # Create a pci_devices record to simulate an instance that had a PCI
        # device allocated at the time it was deleted. There is a window of
        # time between deletion of the instance record and freeing of the PCI
        # device in nova-compute's _complete_deletion method during RT update.
        db.pci_device_update(admin_context, 1, 'fake-address',
                             {'compute_node_id': 1,
                              'address': 'fake-address',
                              'vendor_id': 'fake',
                              'product_id': 'fake',
                              'dev_type': 'fake',
                              'label': 'fake',
                              'status': 'allocated',
                              'instance_uuid': instance.uuid})
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
        # Verify that the pci_devices record has not been dropped
        self.assertNotIn('pci_devices', results)

    def test_archive_deleted_rows_incomplete(self):
        """This tests a scenario where archive_deleted_rows is run with
        --max_rows and does not run to completion.

        That is, the archive is stopped before all archivable records have been
        archived. Specifically, the problematic state is when a single instance
        becomes partially archived (example: 'instance_extra' record for one
        instance has been archived while its 'instances' record remains). Any
        access of the instance (example: listing deleted instances) that
        triggers the retrieval of a dependent record that has been archived
        away, results in undefined behavior that may raise an error.

        We will force the system into a state where a single deleted instance
        is partially archived. We want to verify that we can, for example,
        successfully do a GET /servers/detail at any point between partial
        archive_deleted_rows runs without errors.
        """
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
        # Archive deleted records iteratively, 1 row at a time, and try to do a
        # GET /servers/detail between each run. All should succeed.
        exceptions = []
        while True:
            _, _, archived = db.archive_deleted_rows(max_rows=1)
            try:
                # Need to use the admin API to list deleted servers.
                self.admin_api.get_servers(search_opts={'deleted': True})
            except Exception as ex:
                exceptions.append(ex)
            if archived == 0:
                break
        self.assertFalse(exceptions)

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

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
from oslo_utils import fixture as osloutils_fixture
from oslo_utils import timeutils
import sqlalchemy as sa
from sqlalchemy import func

from nova import context
from nova.db.main import api as db
from nova import objects
from nova.tests.functional import integrated_helpers
from nova import utils as nova_utils


class TestDatabaseArchive(integrated_helpers._IntegratedTestBase):
    """Tests DB API for archiving (soft) deleted records"""

    def setUp(self):
        # Disable filters (namely the ComputeFilter) because we'll manipulate
        # time.
        self.flags(
            enabled_filters=['AllHostsFilter'], group='filter_scheduler')
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

    def test_archive_deleted_rows_parent_child_trees_one_at_time(self):
        """Test that we are archiving parent + child rows "trees" one at a time

        Previously, we archived deleted rows in batches of max_rows parents +
        their child rows in a single database transaction. Doing it that way
        limited how high a value of max_rows could be specified by the caller
        because of the size of the database transaction it could generate.

        For example, in a large scale deployment with hundreds of thousands of
        deleted rows and constant server creation and deletion activity, a
        value of max_rows=1000 might exceed the database's configured maximum
        packet size or timeout due to a database deadlock, forcing the operator
        to use a much lower max_rows value like 100 or 50.

        And when the operator has e.g. 500,000 deleted instances rows (and
        millions of deleted rows total) they are trying to archive, being
        forced to use a max_rows value several orders of magnitude lower than
        the number of rows they need to archive was a poor user experience.

        This tests that we are archiving each parent plus their child rows one
        at a time while limiting the total number of rows per table in a batch
        as soon as the total number of archived rows is >= max_rows.
        """
        # Boot two servers and delete them, then try to archive rows.
        for i in range(2):
            server = self._create_server()
            self._delete_server(server)

        # Use max_rows=5 to limit the archive to one complete parent +
        # child rows tree.
        table_to_rows, _, _ = db.archive_deleted_rows(max_rows=5)

        # We should have archived only one instance because the parent +
        # child tree will have >= max_rows of 5.
        self.assertEqual(1, table_to_rows['instances'])

        # Archive once more to archive the other instance (and its child rows).
        table_to_rows, _, _ = db.archive_deleted_rows(max_rows=5)
        self.assertEqual(1, table_to_rows['instances'])

        # There should be nothing else to archive.
        _, _, total_rows_archived = db.archive_deleted_rows(max_rows=100)
        self.assertEqual(0, total_rows_archived)

    def _get_table_counts(self):
        engine = db.get_engine()
        conn = engine.connect()
        meta = sa.MetaData()
        meta.reflect(bind=engine)
        shadow_tables = db._purgeable_tables(meta)
        results = {}
        for table in shadow_tables:
            r = conn.execute(
                sa.select(func.count()).select_from(table)
            ).fetchone()
            results[table.name] = r[0]
        return results

    def test_archive_then_purge_all(self):
        # Enable the generation of task_log records by the instance usage audit
        # nova-compute periodic task.
        self.flags(instance_usage_audit=True)
        compute = self.computes['compute']

        server = self._create_server()
        server_id = server['id']

        admin_context = context.get_admin_context()
        future = timeutils.utcnow() + datetime.timedelta(days=30)

        with osloutils_fixture.TimeFixture(future):
            # task_log records are generated by the _instance_usage_audit
            # periodic task.
            compute.manager._instance_usage_audit(admin_context)
            # Audit period defaults to 1 month, the last audit period will
            # be the previous calendar month.
            begin, end = nova_utils.last_completed_audit_period()
            # Verify that we have 1 task_log record per audit period.
            task_logs = objects.TaskLogList.get_all(
                admin_context, 'instance_usage_audit', begin, end)
            self.assertEqual(1, len(task_logs))

        self._delete_server(server)
        results, deleted_ids, archived = db.archive_deleted_rows(
            max_rows=1000, task_log=True)
        self.assertEqual([server_id], deleted_ids)

        lines = []

        def status(msg):
            lines.append(msg)

        deleted = db.purge_shadow_tables(admin_context, None, status_fn=status)
        self.assertNotEqual(0, deleted)
        self.assertNotEqual(0, len(lines))
        self.assertEqual(sum(results.values()), archived)
        for line in lines:
            self.assertIsNotNone(re.match(r'Deleted [1-9][0-9]* rows from .*',
                                          line))
        # Ensure we purged task_log records.
        self.assertIn('shadow_task_log', str(lines))

        results = self._get_table_counts()
        # No table should have any rows
        self.assertFalse(any(results.values()))

    def test_archive_then_purge_by_date(self):
        # Enable the generation of task_log records by the instance usage audit
        # nova-compute periodic task.
        self.flags(instance_usage_audit=True)
        compute = self.computes['compute']

        # Simulate a server that was created 30 days ago, needed to test the
        # task_log coverage. The task_log audit period defaults to 1 month, so
        # for a server to appear in the task_log, it must have been active
        # during the previous calendar month.
        month_ago = timeutils.utcnow() - datetime.timedelta(days=30)
        with osloutils_fixture.TimeFixture(month_ago):
            server = self._create_server()

        server_id = server['id']
        admin_context = context.get_admin_context()

        # task_log records are generated by the _instance_usage_audit
        # periodic task.
        compute.manager._instance_usage_audit(admin_context)
        # Audit period defaults to 1 month, the last audit period will
        # be the previous calendar month.
        begin, end = nova_utils.last_completed_audit_period()
        # Verify that we have 1 task_log record per audit period.
        task_logs = objects.TaskLogList.get_all(
            admin_context, 'instance_usage_audit', begin, end)
        self.assertEqual(1, len(task_logs))

        # Delete the server and archive deleted rows.
        self._delete_server(server)
        results, deleted_ids, archived = db.archive_deleted_rows(
            max_rows=1000, task_log=True)
        self.assertEqual([server_id], deleted_ids)
        self.assertEqual(sum(results.values()), archived)

        pre_purge_results = self._get_table_counts()

        # Make sure we didn't delete anything if the marker is before
        # we started
        past = timeutils.utcnow() - datetime.timedelta(days=31)
        deleted = db.purge_shadow_tables(admin_context, past)
        self.assertEqual(0, deleted)

        # Nothing should be changed if we didn't purge anything
        results = self._get_table_counts()
        self.assertEqual(pre_purge_results, results)

        # Make sure we deleted things when the marker is after
        # we started
        future = timeutils.utcnow() + datetime.timedelta(hours=1)
        deleted = db.purge_shadow_tables(admin_context, future)
        self.assertNotEqual(0, deleted)

        # There should be no rows in any table if we purged everything
        results = self._get_table_counts()
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
        deleted = db.purge_shadow_tables(admin_context, date)
        self.assertEqual(0, deleted)
        self.assertEqual(sum(results.values()), archived)

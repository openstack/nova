#    Copyright 2011 OpenStack Foundation
#    Copyright 2011 Ilya Alekseyev
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
import sys
import warnings

import ddt
import fixtures
import mock
from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel
from oslo_utils import uuidutils
from six.moves import StringIO

from nova.cmd import manage
from nova import conf
from nova import context
from nova.db import api as db
from nova.db import migration
from nova.db.sqlalchemy import migration as sqla_migration
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_requests


CONF = conf.CONF


class UtilitiesTestCase(test.NoDBTestCase):

    def test_mask_passwd(self):
        # try to trip up the regex match with extra : and @.
        url1 = ("http://user:pass@domain.com:1234/something?"
                "email=me@somewhere.com")
        self.assertEqual(
            ("http://user:****@domain.com:1234/something?"
             "email=me@somewhere.com"),
            manage.mask_passwd_in_url(url1))

        # pretty standard kinds of urls that we expect, have different
        # schemes. This ensures none of the parts get lost.
        url2 = "mysql+pymysql://root:pass@127.0.0.1/nova_api?charset=utf8"
        self.assertEqual(
            "mysql+pymysql://root:****@127.0.0.1/nova_api?charset=utf8",
            manage.mask_passwd_in_url(url2))

        url3 = "rabbit://stackrabbit:pass@10.42.0.53:5672/"
        self.assertEqual(
            "rabbit://stackrabbit:****@10.42.0.53:5672/",
            manage.mask_passwd_in_url(url3))

        url4 = ("mysql+pymysql://nova:my_password@my_IP/nova_api?"
                "charset=utf8&ssl_ca=/etc/nova/tls/mysql/ca-cert.pem"
                "&ssl_cert=/etc/nova/tls/mysql/server-cert.pem"
                "&ssl_key=/etc/nova/tls/mysql/server-key.pem")
        url4_safe = ("mysql+pymysql://nova:****@my_IP/nova_api?"
                "charset=utf8&ssl_ca=/etc/nova/tls/mysql/ca-cert.pem"
                "&ssl_cert=/etc/nova/tls/mysql/server-cert.pem"
                "&ssl_key=/etc/nova/tls/mysql/server-key.pem")
        self.assertEqual(
            url4_safe,
            manage.mask_passwd_in_url(url4))


class DbCommandsTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(DbCommandsTestCase, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.commands = manage.DbCommands()
        self.useFixture(nova_fixtures.Database())
        self.useFixture(nova_fixtures.Database(database='api'))

    def test_online_migrations_unique(self):
        names = [m.__name__ for m in self.commands.online_migrations]
        self.assertEqual(len(set(names)), len(names),
                         'Online migrations must have a unique name')

    def test_archive_deleted_rows_negative(self):
        self.assertEqual(2, self.commands.archive_deleted_rows(-1))

    def test_archive_deleted_rows_large_number(self):
        large_number = '1' * 100
        self.assertEqual(2, self.commands.archive_deleted_rows(large_number))

    @mock.patch.object(manage.DbCommands, 'purge')
    @mock.patch.object(db, 'archive_deleted_rows',
                       # Each call to archive in each cell returns
                       # total_rows_archived=15, so passing max_rows=30 will
                       # only iterate the first two cells.
                       return_value=(dict(instances=10, consoles=5),
                                     list(), 15))
    def _test_archive_deleted_rows_all_cells(self, mock_db_archive,
                                             mock_purge, purge=False):
        cell_dbs = nova_fixtures.CellDatabases()
        cell_dbs.add_cell_database('fake:///db1')
        cell_dbs.add_cell_database('fake:///db2')
        cell_dbs.add_cell_database('fake:///db3')
        self.useFixture(cell_dbs)

        ctxt = context.RequestContext()

        cell_mapping1 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1',
                                            name='cell1')
        cell_mapping1.create()
        cell_mapping2 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db2',
                                            transport_url='fake:///mq2',
                                            name='cell2')
        cell_mapping2.create()
        cell_mapping3 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db3',
                                            transport_url='fake:///mq3',
                                            name='cell3')
        cell_mapping3.create()
        # Archive with max_rows=30, so we test the case that when we are out of
        # limit, we don't go to the remaining cell.
        result = self.commands.archive_deleted_rows(30, verbose=True,
                                                    all_cells=True,
                                                    purge=purge)
        mock_db_archive.assert_has_calls([
            # Called with max_rows=30 but only 15 were archived.
            mock.call(test.MatchType(context.RequestContext), 30, before=None),
            # So the total from the last call was 15 and the new max_rows=15
            # for the next call in the second cell.
            mock.call(test.MatchType(context.RequestContext), 15, before=None)
        ])
        output = self.output.getvalue()
        expected = '''\
+-----------------+-------------------------+
| Table           | Number of Rows Archived |
+-----------------+-------------------------+
| cell1.consoles  | 5                       |
| cell1.instances | 10                      |
| cell2.consoles  | 5                       |
| cell2.instances | 10                      |
+-----------------+-------------------------+
'''
        if purge:
            expected += 'Rows were archived, running purge...\n'
            mock_purge.assert_called_once_with(purge_all=True, verbose=True,
                                               all_cells=True)
        else:
            mock_purge.assert_not_called()
        self.assertEqual(expected, output)
        self.assertEqual(1, result)

    def test_archive_deleted_rows_all_cells(self):
        self._test_archive_deleted_rows_all_cells()

    def test_archive_deleted_rows_all_cells_purge(self):
        self._test_archive_deleted_rows_all_cells(purge=True)

    @mock.patch.object(db, 'archive_deleted_rows')
    def test_archive_deleted_rows_all_cells_until_complete(self,
                                                           mock_db_archive):
        # First two calls to archive in each cell return total_rows_archived=15
        # and the last call returns 0 (nothing left to archive).
        fake_return = (dict(instances=10, consoles=5), list(), 15)
        mock_db_archive.side_effect = [fake_return,
                                       (dict(), list(), 0),
                                       fake_return,
                                       (dict(), list(), 0),
                                       (dict(), list(), 0)]
        cell_dbs = nova_fixtures.CellDatabases()
        cell_dbs.add_cell_database('fake:///db1')
        cell_dbs.add_cell_database('fake:///db2')
        cell_dbs.add_cell_database('fake:///db3')
        self.useFixture(cell_dbs)

        ctxt = context.RequestContext()

        cell_mapping1 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1',
                                            name='cell1')
        cell_mapping1.create()
        cell_mapping2 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db2',
                                            transport_url='fake:///mq2',
                                            name='cell2')
        cell_mapping2.create()
        cell_mapping3 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db3',
                                            transport_url='fake:///mq3',
                                            name='cell3')
        cell_mapping3.create()
        # Archive with max_rows=30, so we test that subsequent max_rows are not
        # reduced when until_complete=True. There is no max total limit.
        result = self.commands.archive_deleted_rows(30, verbose=True,
                                                    all_cells=True,
                                                    until_complete=True)
        mock_db_archive.assert_has_calls([
            # Called with max_rows=30 but only 15 were archived.
            mock.call(test.MatchType(context.RequestContext), 30, before=None),
            # Called with max_rows=30 but 0 were archived (nothing left to
            # archive in this cell)
            mock.call(test.MatchType(context.RequestContext), 30, before=None),
            # So the total from the last call was 0 and the new max_rows=30
            # because until_complete=True.
            mock.call(test.MatchType(context.RequestContext), 30, before=None),
            # Called with max_rows=30 but 0 were archived (nothing left to
            # archive in this cell)
            mock.call(test.MatchType(context.RequestContext), 30, before=None),
            # Called one final time with max_rows=30
            mock.call(test.MatchType(context.RequestContext), 30, before=None)
        ])
        output = self.output.getvalue()
        expected = '''\
Archiving.....complete
+-----------------+-------------------------+
| Table           | Number of Rows Archived |
+-----------------+-------------------------+
| cell1.consoles  | 5                       |
| cell1.instances | 10                      |
| cell2.consoles  | 5                       |
| cell2.instances | 10                      |
+-----------------+-------------------------+
'''
        self.assertEqual(expected, output)
        self.assertEqual(1, result)

    @mock.patch.object(db, 'archive_deleted_rows',
                       return_value=(
                               dict(instances=10, consoles=5), list(), 15))
    def _test_archive_deleted_rows(self, mock_db_archive, verbose=False):
        result = self.commands.archive_deleted_rows(20, verbose=verbose)
        mock_db_archive.assert_called_once_with(
            test.MatchType(context.RequestContext), 20, before=None)
        output = self.output.getvalue()
        if verbose:
            expected = '''\
+-----------+-------------------------+
| Table     | Number of Rows Archived |
+-----------+-------------------------+
| consoles  | 5                       |
| instances | 10                      |
+-----------+-------------------------+
'''
            self.assertEqual(expected, output)
        else:
            self.assertEqual(0, len(output))
        self.assertEqual(1, result)

    def test_archive_deleted_rows(self):
        # Tests that we don't show any table output (not verbose).
        self._test_archive_deleted_rows()

    def test_archive_deleted_rows_verbose(self):
        # Tests that we get table output.
        self._test_archive_deleted_rows(verbose=True)

    @mock.patch.object(db, 'archive_deleted_rows')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_archive_deleted_rows_until_complete(self, mock_get_all,
                                                 mock_db_archive,
                                                 verbose=False):
        mock_db_archive.side_effect = [
            ({'instances': 10, 'instance_extra': 5}, list(), 15),
            ({'instances': 5, 'instance_faults': 1}, list(), 6),
            ({}, list(), 0)]
        result = self.commands.archive_deleted_rows(20, verbose=verbose,
                                                    until_complete=True)
        self.assertEqual(1, result)
        if verbose:
            expected = """\
Archiving.....complete
+-----------------+-------------------------+
| Table           | Number of Rows Archived |
+-----------------+-------------------------+
| instance_extra  | 5                       |
| instance_faults | 1                       |
| instances       | 15                      |
+-----------------+-------------------------+
"""
        else:
            expected = ''

        self.assertEqual(expected, self.output.getvalue())
        mock_db_archive.assert_has_calls([
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
        ])

    def test_archive_deleted_rows_until_complete_quiet(self):
        self.test_archive_deleted_rows_until_complete(verbose=False)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    @mock.patch.object(db, 'archive_deleted_rows')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_archive_deleted_rows_until_stopped(self, mock_get_all,
                                                mock_db_archive,
                                                mock_db_purge,
                                                verbose=True):
        mock_db_archive.side_effect = [
            ({'instances': 10, 'instance_extra': 5}, list(), 15),
            ({'instances': 5, 'instance_faults': 1}, list(), 6),
            KeyboardInterrupt]
        result = self.commands.archive_deleted_rows(20, verbose=verbose,
                                                    until_complete=True,
                                                    purge=True)
        self.assertEqual(1, result)
        if verbose:
            expected = """\
Archiving.....stopped
+-----------------+-------------------------+
| Table           | Number of Rows Archived |
+-----------------+-------------------------+
| instance_extra  | 5                       |
| instance_faults | 1                       |
| instances       | 15                      |
+-----------------+-------------------------+
Rows were archived, running purge...
"""
        else:
            expected = ''

        self.assertEqual(expected, self.output.getvalue())
        mock_db_archive.assert_has_calls([
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
        ])
        mock_db_purge.assert_called_once_with(mock.ANY, None,
                                              status_fn=mock.ANY)

    @mock.patch.object(db, 'archive_deleted_rows')
    def test_archive_deleted_rows_until_stopped_cells(self, mock_db_archive,
                                                      verbose=True):
        # Test when archive with all_cells=True and until_complete=True,
        # when hit KeyboardInterrupt, it will directly return and not
        # process remaining cells.
        mock_db_archive.side_effect = [
            ({'instances': 10, 'instance_extra': 5}, list(), 15),
            KeyboardInterrupt]
        cell_dbs = nova_fixtures.CellDatabases()
        cell_dbs.add_cell_database('fake:///db1')
        cell_dbs.add_cell_database('fake:///db2')
        cell_dbs.add_cell_database('fake:///db3')
        self.useFixture(cell_dbs)

        ctxt = context.RequestContext()

        cell_mapping1 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1',
                                            name='cell1')
        cell_mapping1.create()
        cell_mapping2 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db2',
                                            transport_url='fake:///mq2',
                                            name='cell2')
        cell_mapping2.create()
        cell_mapping3 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db3',
                                            transport_url='fake:///mq3',
                                            name='cell3')
        cell_mapping3.create()
        result = self.commands.archive_deleted_rows(20, verbose=verbose,
                                                    until_complete=True,
                                                    all_cells=True)
        self.assertEqual(1, result)
        if verbose:
            expected = '''\
Archiving....stopped
+----------------------+-------------------------+
| Table                | Number of Rows Archived |
+----------------------+-------------------------+
| cell1.instance_extra | 5                       |
| cell1.instances      | 10                      |
+----------------------+-------------------------+
'''
        else:
            expected = ''

        self.assertEqual(expected, self.output.getvalue())
        mock_db_archive.assert_has_calls([
            mock.call(test.MatchType(context.RequestContext), 20, before=None),
            mock.call(test.MatchType(context.RequestContext), 20, before=None)
        ])

    def test_archive_deleted_rows_until_stopped_quiet(self):
        self.test_archive_deleted_rows_until_stopped(verbose=False)

    @mock.patch.object(db, 'archive_deleted_rows')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_archive_deleted_rows_before(self, mock_get_all, mock_db_archive):
        mock_db_archive.side_effect = [
            ({'instances': 10, 'instance_extra': 5}, list(), 15),
            ({'instances': 5, 'instance_faults': 1}, list(), 6),
            KeyboardInterrupt]
        result = self.commands.archive_deleted_rows(20, before='2017-01-13')
        mock_db_archive.assert_called_once_with(
                test.MatchType(context.RequestContext), 20,
                before=datetime.datetime(2017, 1, 13))
        self.assertEqual(1, result)

    @mock.patch.object(db, 'archive_deleted_rows', return_value=({}, [], 0))
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_archive_deleted_rows_verbose_no_results(self, mock_get_all,
                                                     mock_db_archive):
        result = self.commands.archive_deleted_rows(20, verbose=True,
                                                    purge=True)
        mock_db_archive.assert_called_once_with(
            test.MatchType(context.RequestContext), 20, before=None)
        output = self.output.getvalue()
        # If nothing was archived, there should be no purge messages
        self.assertIn('Nothing was archived.', output)
        self.assertEqual(0, result)

    @mock.patch.object(db, 'archive_deleted_rows')
    @mock.patch.object(objects.RequestSpec, 'destroy_bulk')
    @mock.patch.object(objects.InstanceGroup, 'destroy_members_bulk')
    def test_archive_deleted_rows_and_api_db_records(
            self, mock_members_destroy, mock_reqspec_destroy, mock_db_archive,
            verbose=True):
        self.useFixture(nova_fixtures.Database())
        self.useFixture(nova_fixtures.Database(database='api'))

        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(context=ctxt,
                                           uuid=cell_uuid,
                                           database_connection='fake:///db',
                                           transport_url='fake:///mq',
                                           name='cell1')
        cell_mapping.create()
        uuids = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id, uuid=uuid)\
                                .create()
            objects.InstanceMapping(ctxt, project_id=ctxt.project_id,
                                cell_mapping=cell_mapping, instance_uuid=uuid)\
                                .create()

        mock_db_archive.return_value = (
            dict(instances=2, consoles=5), uuids, 7)
        mock_reqspec_destroy.return_value = 2
        mock_members_destroy.return_value = 0
        result = self.commands.archive_deleted_rows(20, verbose=verbose,
                                                    all_cells=True)

        self.assertEqual(1, result)
        mock_db_archive.assert_has_calls([
            mock.call(test.MatchType(context.RequestContext), 20, before=None)
        ])
        self.assertEqual(1, mock_reqspec_destroy.call_count)
        mock_members_destroy.assert_called_once()

        output = self.output.getvalue()
        if verbose:
            expected = '''\
+------------------------------+-------------------------+
| Table                        | Number of Rows Archived |
+------------------------------+-------------------------+
| API_DB.instance_group_member | 0                       |
| API_DB.instance_mappings     | 2                       |
| API_DB.request_specs         | 2                       |
| cell1.consoles               | 5                       |
| cell1.instances              | 2                       |
+------------------------------+-------------------------+
'''
            self.assertEqual(expected, output)
        else:
            self.assertEqual(0, len(output))

    @mock.patch.object(objects.CellMappingList, 'get_all',
                       side_effect=db_exc.CantStartEngineError)
    def test_archive_deleted_rows_without_api_connection_configured(self,
                                                           mock_get_all):
        result = self.commands.archive_deleted_rows(20, verbose=True)
        mock_get_all.assert_called_once()
        output = self.output.getvalue()
        expected = '''\
Failed to connect to API DB so aborting this archival attempt. \
Please check your config file to make sure that [api_database]/connection \
is set and run this command again.
'''
        self.assertEqual(expected, output)
        self.assertEqual(3, result)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    def test_purge_all(self, mock_purge):
        mock_purge.return_value = 1
        ret = self.commands.purge(purge_all=True)
        self.assertEqual(0, ret)
        mock_purge.assert_called_once_with(mock.ANY, None, status_fn=mock.ANY)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    def test_purge_date(self, mock_purge):
        mock_purge.return_value = 1
        ret = self.commands.purge(before='oct 21 2015')
        self.assertEqual(0, ret)
        mock_purge.assert_called_once_with(mock.ANY,
                                           datetime.datetime(2015, 10, 21),
                                           status_fn=mock.ANY)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    def test_purge_date_fail(self, mock_purge):
        ret = self.commands.purge(before='notadate')
        self.assertEqual(2, ret)
        self.assertFalse(mock_purge.called)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    def test_purge_no_args(self, mock_purge):
        ret = self.commands.purge()
        self.assertEqual(1, ret)
        self.assertFalse(mock_purge.called)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    def test_purge_nothing_deleted(self, mock_purge):
        mock_purge.return_value = 0
        ret = self.commands.purge(purge_all=True)
        self.assertEqual(3, ret)

    @mock.patch('nova.db.sqlalchemy.api.purge_shadow_tables')
    @mock.patch('nova.objects.CellMappingList.get_all')
    def test_purge_all_cells(self, mock_get_cells, mock_purge):
        cell1 = objects.CellMapping(uuid=uuidsentinel.cell1, name='cell1',
                                    database_connection='foo1',
                                    transport_url='bar1')
        cell2 = objects.CellMapping(uuid=uuidsentinel.cell2, name='cell2',
                                    database_connection='foo2',
                                    transport_url='bar2')

        mock_get_cells.return_value = [cell1, cell2]

        values = [123, 456]

        def fake_purge(*args, **kwargs):
            val = values.pop(0)
            kwargs['status_fn'](val)
            return val
        mock_purge.side_effect = fake_purge

        ret = self.commands.purge(purge_all=True, all_cells=True, verbose=True)
        self.assertEqual(0, ret)
        mock_get_cells.assert_called_once_with(mock.ANY)
        output = self.output.getvalue()
        expected = """\
Cell %s: 123
Cell %s: 456
""" % (cell1.identity, cell2.identity)

        self.assertEqual(expected, output)

    @mock.patch('nova.objects.CellMappingList.get_all')
    def test_purge_all_cells_no_api_config(self, mock_get_cells):
        mock_get_cells.side_effect = db_exc.DBError
        ret = self.commands.purge(purge_all=True, all_cells=True)
        self.assertEqual(4, ret)
        self.assertIn('Unable to get cell list', self.output.getvalue())

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 0})
    def test_null_instance_uuid_scan_no_records_found(self, mock_scan):
        self.commands.null_instance_uuid_scan()
        self.assertIn("There were no records found", self.output.getvalue())

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 1, 'bar': 0})
    def _test_null_instance_uuid_scan(self, mock_scan, delete):
        self.commands.null_instance_uuid_scan(delete)
        output = self.output.getvalue()

        if delete:
            self.assertIn("Deleted 1 records from table 'foo'.", output)
            self.assertNotIn("Deleted 0 records from table 'bar'.", output)
        else:
            self.assertIn("1 records in the 'foo' table", output)
            self.assertNotIn("0 records in the 'bar' table", output)
        self.assertNotIn("There were no records found", output)

    def test_null_instance_uuid_scan_readonly(self):
        self._test_null_instance_uuid_scan(delete=False)

    def test_null_instance_uuid_scan_delete(self):
        self._test_null_instance_uuid_scan(delete=True)

    @mock.patch.object(sqla_migration, 'db_version', return_value=2)
    def test_version(self, sqla_migrate):
        self.commands.version()
        sqla_migrate.assert_called_once_with(context=None, database='main')

    @mock.patch.object(sqla_migration, 'db_sync')
    def test_sync(self, sqla_sync):
        self.commands.sync(version=4, local_cell=True)
        sqla_sync.assert_called_once_with(context=None,
                                          version=4, database='main')

    @mock.patch('nova.db.migration.db_sync')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid', return_value='map')
    def test_sync_cell0(self, mock_get_by_uuid, mock_db_sync):
        ctxt = context.get_admin_context()
        cell_ctxt = context.get_admin_context()
        with test.nested(
                mock.patch('nova.context.RequestContext',
                           return_value=ctxt),
                mock.patch('nova.context.target_cell')) \
                                   as (mock_get_context,
                                       mock_target_cell):
            fake_target_cell_mock = mock.MagicMock()
            fake_target_cell_mock.__enter__.return_value = cell_ctxt
            mock_target_cell.return_value = fake_target_cell_mock
            self.commands.sync(version=4)
            mock_get_by_uuid.assert_called_once_with(ctxt,
                                        objects.CellMapping.CELL0_UUID)
            mock_target_cell.assert_called_once_with(ctxt, 'map')

            db_sync_calls = [
                mock.call(4, context=cell_ctxt),
                mock.call(4)
            ]
            mock_db_sync.assert_has_calls(db_sync_calls)

    @mock.patch.object(objects.CellMapping, 'get_by_uuid',
                       side_effect=test.TestingException('invalid connection'))
    def test_sync_cell0_unknown_error(self, mock_get_by_uuid):
        """Asserts that a detailed error message is given when an unknown
        error occurs trying to get the cell0 cell mapping.
        """
        result = self.commands.sync()
        self.assertEqual(1, result)
        mock_get_by_uuid.assert_called_once_with(
            test.MatchType(context.RequestContext),
            objects.CellMapping.CELL0_UUID)
        expected = """ERROR: Could not access cell0.
Has the nova_api database been created?
Has the nova_cell0 database been created?
Has "nova-manage api_db sync" been run?
Has "nova-manage cell_v2 map_cell0" been run?
Is [api_database]/connection set in nova.conf?
Is the cell0 database connection URL correct?
Error: invalid connection
"""
        self.assertEqual(expected, self.output.getvalue())

    def _fake_db_command(self, migrations=None):
        if migrations is None:
            mock_mig_1 = mock.MagicMock(__name__="mock_mig_1")
            mock_mig_2 = mock.MagicMock(__name__="mock_mig_2")
            mock_mig_1.return_value = (5, 4)
            mock_mig_2.return_value = (6, 6)
            migrations = (mock_mig_1, mock_mig_2)

        class _CommandSub(manage.DbCommands):
            online_migrations = migrations

        return _CommandSub

    @mock.patch('nova.context.get_admin_context')
    def test_online_migrations(self, mock_get_context):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        ctxt = mock_get_context.return_value
        command_cls = self._fake_db_command()
        command = command_cls()
        command.online_data_migrations(10)
        command_cls.online_migrations[0].assert_called_once_with(ctxt, 10)
        command_cls.online_migrations[1].assert_called_once_with(ctxt, 6)
        expected = """\
5 rows matched query mock_mig_1, 4 migrated
6 rows matched query mock_mig_2, 6 migrated
+------------+--------------+-----------+
| Migration  | Total Needed | Completed |
+------------+--------------+-----------+
| mock_mig_1 |      5       |     4     |
| mock_mig_2 |      6       |     6     |
+------------+--------------+-----------+
"""
        self.assertEqual(expected, sys.stdout.getvalue())

    @mock.patch('nova.context.get_admin_context')
    def test_online_migrations_no_max_count(self, mock_get_context):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        total = [120]
        batches = [50, 40, 30, 0]
        runs = []

        def fake_migration(context, count):
            self.assertEqual(mock_get_context.return_value, context)
            runs.append(count)
            count = batches.pop(0)
            total[0] -= count
            return count, count

        command_cls = self._fake_db_command((fake_migration,))
        command = command_cls()
        command.online_data_migrations(None)
        expected = """\
Running batches of 50 until complete
50 rows matched query fake_migration, 50 migrated
40 rows matched query fake_migration, 40 migrated
30 rows matched query fake_migration, 30 migrated
+----------------+--------------+-----------+
|   Migration    | Total Needed | Completed |
+----------------+--------------+-----------+
| fake_migration |     120      |    120    |
+----------------+--------------+-----------+
"""
        self.assertEqual(expected, sys.stdout.getvalue())
        self.assertEqual([], batches)
        self.assertEqual(0, total[0])
        self.assertEqual([50, 50, 50, 50], runs)

    @mock.patch('nova.context.get_admin_context')
    def test_online_migrations_error(self, mock_get_context):
        good_remaining = [50]

        def good_migration(context, count):
            self.assertEqual(mock_get_context.return_value, context)
            found = good_remaining[0]
            done = min(found, count)
            good_remaining[0] -= done
            return found, done

        bad_migration = mock.MagicMock()
        bad_migration.side_effect = test.TestingException
        bad_migration.__name__ = 'bad'

        command_cls = self._fake_db_command((bad_migration, good_migration))
        command = command_cls()

        # bad_migration raises an exception, but it could be because
        # good_migration had not completed yet. We should get 1 in this case,
        # because some work was done, and the command should be reiterated.
        self.assertEqual(1, command.online_data_migrations(max_count=50))

        # When running this for the second time, there's no work left for
        # good_migration to do, but bad_migration still fails - should
        # get 2 this time.
        self.assertEqual(2, command.online_data_migrations(max_count=50))

        # When --max-count is not used, we should get 2 if all possible
        # migrations completed but some raise exceptions
        good_remaining = [125]
        self.assertEqual(2, command.online_data_migrations(None))

    def test_online_migrations_bad_max(self):
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count=-2))
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count='a'))
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count=0))

    def test_online_migrations_no_max(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = {}, False
            self.assertEqual(0,
                             self.commands.online_data_migrations())

    def test_online_migrations_finished(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = {}, False
            self.assertEqual(0,
                             self.commands.online_data_migrations(max_count=5))

    def test_online_migrations_not_finished(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = {'mig': (10, 5)}, False
            self.assertEqual(1,
                             self.commands.online_data_migrations(max_count=5))


class ApiDbCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ApiDbCommandsTestCase, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.commands = manage.ApiDbCommands()

    @mock.patch.object(sqla_migration, 'db_version', return_value=2)
    def test_version(self, sqla_migrate):
        self.commands.version()
        sqla_migrate.assert_called_once_with(context=None,
                                             database='api')

    @mock.patch.object(sqla_migration, 'db_sync')
    def test_sync(self, sqla_sync):
        self.commands.sync(version=4)
        sqla_sync.assert_called_once_with(context=None,
                                          version=4, database='api')


@ddt.ddt
class CellV2CommandsTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(CellV2CommandsTestCase, self).setUp()
        self.useFixture(nova_fixtures.Database())
        self.useFixture(nova_fixtures.Database(database='api'))
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.commands = manage.CellV2Commands()

    def test_map_cell_and_hosts(self):
        # Create some fake compute nodes and check if they get host mappings
        ctxt = context.RequestContext()
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        self.commands.map_cell_and_hosts(cell_transport_url, name='ssd',
                                         verbose=True)
        cell_mapping_uuid = self.output.getvalue().strip()
        # Verify the cell mapping
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_mapping_uuid)
        self.assertEqual('ssd', cell_mapping.name)
        self.assertEqual(cell_transport_url, cell_mapping.transport_url)
        # Verify the host mappings
        for i in range(3):
            host = 'host%s' % i
            host_mapping = objects.HostMapping.get_by_host(ctxt, host)
            self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)

    def test_map_cell_and_hosts_duplicate(self):
        # Create a cell mapping and hosts and check that nothing new is created
        ctxt = context.RequestContext()
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_mapping_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        # Create compute nodes that will map to the cell
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()
            host_mapping = objects.HostMapping(
                    ctxt, host=host, cell_mapping=cell_mapping)
            host_mapping.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        retval = self.commands.map_cell_and_hosts(cell_transport_url,
                                                  name='ssd',
                                                  verbose=True)
        self.assertEqual(0, retval)
        output = self.output.getvalue().strip()
        expected = ''
        for i in range(3):
            expected += ('Host host%s is already mapped to cell %s\n' %
                         (i, cell_mapping_uuid))
        expected += 'All hosts are already mapped to cell(s).'
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_partial_update(self):
        # Create a cell mapping and partial hosts and check that
        # missing HostMappings are created
        ctxt = context.RequestContext()
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_mapping_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        # Create compute nodes that will map to the cell
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()

        # NOTE(danms): Create a second node on one compute to make sure
        # we handle that case
        compute_node = objects.ComputeNode(ctxt, host='host0', **values)
        compute_node.create()

        # Only create 2 existing HostMappings out of 3
        for i in range(2):
            host = 'host%s' % i
            host_mapping = objects.HostMapping(
                    ctxt, host=host, cell_mapping=cell_mapping)
            host_mapping.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        self.commands.map_cell_and_hosts(cell_transport_url,
                                         name='ssd',
                                         verbose=True)
        # Verify the HostMapping for the last host was created
        host_mapping = objects.HostMapping.get_by_host(ctxt, 'host2')
        self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)
        # Verify the output
        output = self.output.getvalue().strip()
        expected = ''
        for i in [0, 1, 0]:
            expected += ('Host host%s is already mapped to cell %s\n' %
                         (i, cell_mapping_uuid))
        # The expected CellMapping UUID for the last host should be the same
        expected += cell_mapping.uuid
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_no_hosts_found(self):
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        retval = self.commands.map_cell_and_hosts(cell_transport_url,
                                                  name='ssd',
                                                  verbose=True)
        self.assertEqual(0, retval)
        output = self.output.getvalue().strip()
        expected = 'No hosts found to map to cell, exiting.'
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_no_transport_url(self):
        self.flags(transport_url=None)
        retval = self.commands.map_cell_and_hosts()
        self.assertEqual(1, retval)
        output = self.output.getvalue().strip()
        expected = ('Must specify --transport-url if [DEFAULT]/transport_url '
                    'is not set in the configuration file.')
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_transport_url_config(self):
        self.flags(transport_url = "fake://guest:devstack@127.0.0.1:9999/")
        retval = self.commands.map_cell_and_hosts()
        self.assertEqual(0, retval)

    @mock.patch.object(context, 'target_cell')
    def test_map_instances(self, mock_target_cell):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        for i in range(3):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        self.commands.map_instances(cell_uuid)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
            # Verify that map_instances populates user_id.
            self.assertEqual(ctxt.user_id, inst_mapping.user_id)
            self.assertEqual(cell_mapping.uuid, inst_mapping.cell_mapping.uuid)
        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))

    @mock.patch.object(context, 'target_cell')
    def test_map_instances_duplicates(self, mock_target_cell):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        for i in range(3):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        objects.InstanceMapping(ctxt, project_id=ctxt.project_id,
                user_id=ctxt.user_id, instance_uuid=instance_uuids[0],
                cell_mapping=cell_mapping).create()

        self.commands.map_instances(cell_uuid)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)

        mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                ctxt.project_id)
        self.assertEqual(3, len(mappings))
        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))

    @mock.patch.object(context, 'target_cell')
    def test_map_instances_two_batches(self, mock_target_cell):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        # Batch size is 50 in map_instances
        for i in range(60):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid)
        self.assertEqual(0, ret)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
        self.assertEqual(2, mock_target_cell.call_count)
        mock_target_cell.assert_called_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))

    @mock.patch.object(context, 'target_cell')
    def test_map_instances_max_count(self, mock_target_cell):
        # NOTE(gibi): map_instances command uses non canonical UUID
        # serialization for the marker instance mapping. The db schema is not
        # violated so we suppress the warning here.
        warnings.filterwarnings('ignore', message=".*invalid UUID.*")
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        for i in range(6):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid, max_count=3)
        self.assertEqual(1, ret)

        for uuid in instance_uuids[:3]:
            # First three are mapped
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
        for uuid in instance_uuids[3:]:
            # Last three are not
            self.assertRaises(exception.InstanceMappingNotFound,
                    objects.InstanceMapping.get_by_instance_uuid, ctxt,
                    uuid)
        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))

    @mock.patch.object(context, 'target_cell')
    def test_map_instances_marker_deleted(self, mock_target_cell):
        # NOTE(gibi): map_instances command uses non canonical UUID
        # serialization for the marker instance mapping. The db schema is not
        # violated so we suppress the warning here.
        warnings.filterwarnings('ignore', message=".*invalid UUID.*")
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        for i in range(6):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid, max_count=3)
        self.assertEqual(1, ret)

        # Instances are mapped in the order created so we know the marker is
        # based off the third instance.
        marker = instance_uuids[2].replace('-', ' ')
        marker_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                marker)
        marker_mapping.destroy()

        ret = self.commands.map_instances(cell_uuid)
        self.assertEqual(0, ret)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
        self.assertEqual(2, mock_target_cell.call_count)
        mock_target_cell.assert_called_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))

    @mock.patch.object(context, 'target_cell')
    def test_map_instances_marker_reset(self, mock_target_cell):
        # NOTE(gibi): map_instances command uses non canonical UUID
        # serialization for the marker instance mapping. The db schema is not
        # violated so we suppress the warning here.
        warnings.filterwarnings('ignore', message=".*invalid UUID.*")
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        instance_uuids = []
        for i in range(5):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             user_id=ctxt.user_id, uuid=uuid).create()

        # Maps first three instances.
        ret = self.commands.map_instances(cell_uuid, max_count=3)
        self.assertEqual(1, ret)

        # Verifying that the marker is now based on third instance
        # i.e the position of the marker.
        inst_mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                                        'INSTANCE_MIGRATION_MARKER')
        marker = inst_mappings[0].instance_uuid.replace(' ', '-')
        self.assertEqual(instance_uuids[2], marker)

        # Now calling reset with map_instances max_count=2 would reset
        # the marker as expected and start map_instances from the beginning.
        # This implies we end up finding the marker based on second instance.
        ret = self.commands.map_instances(cell_uuid, max_count=2,
                                          reset_marker=True)
        self.assertEqual(1, ret)

        inst_mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                                        'INSTANCE_MIGRATION_MARKER')
        marker = inst_mappings[0].instance_uuid.replace(' ', '-')
        self.assertEqual(instance_uuids[1], marker)

        # Maps 4th instance using the marker (3rd is already mapped).
        ret = self.commands.map_instances(cell_uuid, max_count=2)
        self.assertEqual(1, ret)

        # Verifying that the marker is now based on fourth instance
        # i.e the position of the marker.
        inst_mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                                        'INSTANCE_MIGRATION_MARKER')
        marker = inst_mappings[0].instance_uuid.replace(' ', '-')
        self.assertEqual(instance_uuids[3], marker)

        # Maps first four instances (all four duplicate entries which
        # are already present from previous calls)
        ret = self.commands.map_instances(cell_uuid, max_count=4,
                                          reset_marker=True)
        self.assertEqual(1, ret)

        # Verifying that the marker is still based on fourth instance
        # i.e the position of the marker.
        inst_mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                                        'INSTANCE_MIGRATION_MARKER')
        marker = inst_mappings[0].instance_uuid.replace(' ', '-')
        self.assertEqual(instance_uuids[3], marker)

        # Maps the 5th instance.
        ret = self.commands.map_instances(cell_uuid)
        self.assertEqual(0, ret)

    def test_map_instances_validate_cell_uuid(self):
        # create a random cell_uuid which is invalid
        cell_uuid = uuidutils.generate_uuid()
        # check that it raises an exception
        self.assertRaises(exception.CellMappingNotFound,
            self.commands.map_instances, cell_uuid)

    def test_map_cell0(self):
        ctxt = context.RequestContext()
        database_connection = 'fake:/foobar//'
        self.commands.map_cell0(database_connection)
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual(database_connection, cell_mapping.database_connection)

    @mock.patch.object(manage.CellV2Commands, '_map_cell0', new=mock.Mock())
    def test_map_cell0_returns_0_on_successful_create(self):
        self.assertEqual(0, self.commands.map_cell0())

    @mock.patch.object(manage.CellV2Commands, '_map_cell0')
    def test_map_cell0_returns_0_if_cell0_already_exists(self, _map_cell0):
        _map_cell0.side_effect = db_exc.DBDuplicateEntry
        exit_code = self.commands.map_cell0()
        self.assertEqual(0, exit_code)
        output = self.output.getvalue().strip()
        self.assertEqual('Cell0 is already setup', output)

    def test_map_cell0_default_database(self):
        CONF.set_default('connection',
                         'fake://netloc/nova',
                         group='database')
        ctxt = context.RequestContext()
        self.commands.map_cell0()
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual('fake://netloc/nova_cell0',
                         cell_mapping.database_connection)

    @ddt.data('mysql+pymysql://nova:abcd0123:AB@controller/%s',
              'mysql+pymysql://nova:abcd0123?AB@controller/%s',
              'mysql+pymysql://nova:abcd0123@AB@controller/%s',
              'mysql+pymysql://nova:abcd0123/AB@controller/%s',
              'mysql+pymysql://test:abcd0123/AB@controller/%s?charset=utf8')
    def test_map_cell0_default_database_special_characters(self,
                                                           connection):
        """Tests that a URL with special characters, like in the credentials,
        is handled properly.
        """
        decoded_connection = connection % 'nova'
        self.flags(connection=decoded_connection, group='database')
        ctxt = context.RequestContext()
        self.commands.map_cell0()
        cell_mapping = objects.CellMapping.get_by_uuid(
            ctxt, objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual(
            connection % 'nova_cell0',
            cell_mapping.database_connection)
        # Delete the cell mapping for the next iteration.
        cell_mapping.destroy()

    def _test_migrate_simple_command(self, cell0_sync_fail=False):
        ctxt = context.RequestContext()
        CONF.set_default('connection',
                         'fake://netloc/nova',
                         group='database')
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()

        transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        cell_uuid = uuidsentinel.cell

        @mock.patch('nova.db.migration.db_sync')
        @mock.patch.object(context, 'target_cell')
        @mock.patch.object(uuidutils, 'generate_uuid',
                return_value=cell_uuid)
        def _test(mock_gen_uuid, mock_target_cell, mock_db_sync):
            if cell0_sync_fail:
                mock_db_sync.side_effect = db_exc.DBError
            result = self.commands.simple_cell_setup(transport_url)
            mock_db_sync.assert_called()
            return result

        r = _test()
        self.assertEqual(0, r)

        # Check cell0 from default
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual('fake://netloc/nova_cell0',
                         cell_mapping.database_connection)

        # Verify the cell mapping
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
        self.assertEqual(transport_url, cell_mapping.transport_url)
        # Verify the host mappings
        for i in range(3):
            host = 'host%s' % i
            host_mapping = objects.HostMapping.get_by_host(ctxt, host)
            self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)

    def test_simple_command_single(self):
        self._test_migrate_simple_command()

    def test_simple_command_cell0_fail(self):
        # Make sure that if db_sync fails, we still do all the other
        # bits
        self._test_migrate_simple_command(cell0_sync_fail=True)

    def test_simple_command_multiple(self):
        # Make sure that the command is idempotent
        self._test_migrate_simple_command()
        self._test_migrate_simple_command()

    def test_instance_verify_no_mapping(self):
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(1, r)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_instance_verify_has_only_instance_mapping(self, mock_get):
        im = objects.InstanceMapping(cell_mapping=None)
        mock_get.return_value = im
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(2, r)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch.object(context, 'target_cell')
    def test_instance_verify_has_all_mappings(self, mock_target_cell,
                                                mock_get2, mock_get1):
        cm = objects.CellMapping(name='foo', uuid=uuidsentinel.cel)
        im = objects.InstanceMapping(cell_mapping=cm)
        mock_get1.return_value = im
        mock_get2.return_value = None
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(0, r)

    def test_instance_verify_quiet(self):
        # NOTE(danms): This will hit the first use of the say() wrapper
        # and reasonably verify that path
        self.assertEqual(1, self.commands.verify_instance(uuidsentinel.foo,
                                                          quiet=True))

    @mock.patch.object(context, 'target_cell')
    def test_instance_verify_has_instance_mapping_but_no_instance(self,
                                                    mock_target_cell):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(context=ctxt,
                                            uuid=cell_uuid,
                                            database_connection='fake:///db',
                                            transport_url='fake:///mq')
        cell_mapping.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        uuid = uuidutils.generate_uuid()
        objects.Instance(ctxt, project_id=ctxt.project_id, uuid=uuid).create()
        objects.InstanceMapping(ctxt, project_id=ctxt.project_id,
                                cell_mapping=cell_mapping, instance_uuid=uuid)\
                                .create()
        # a scenario where an instance is deleted, but not archived.
        inst = objects.Instance.get_by_uuid(ctxt, uuid)
        inst.destroy()
        r = self.commands.verify_instance(uuid)
        self.assertEqual(3, r)
        self.assertIn('has been deleted', self.output.getvalue())
        # a scenario where there is only the instance mapping but no instance
        # like when an instance has been archived but the instance mapping
        # was not deleted.
        uuid = uuidutils.generate_uuid()
        objects.InstanceMapping(ctxt, project_id=ctxt.project_id,
                                cell_mapping=cell_mapping, instance_uuid=uuid)\
                                .create()
        r = self.commands.verify_instance(uuid)
        self.assertEqual(4, r)
        self.assertIn('has been archived', self.output.getvalue())

    def _return_compute_nodes(self, ctxt, num=1):
        nodes = []
        for i in range(num):
            nodes.append(objects.ComputeNode(ctxt,
                                             uuid=uuidutils.generate_uuid(),
                                             host='host%s' % i,
                                             vcpus=1,
                                             memory_mb=1,
                                             local_gb=1,
                                             vcpus_used=0,
                                             memory_mb_used=0,
                                             local_gb_used=0,
                                             hypervisor_type='',
                                             hypervisor_version=1,
                                             cpu_info=''))
        return nodes

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_discover_hosts_single_cell(self, mock_cell_mapping_get_all,
                                        mock_target_cell):
        ctxt = context.RequestContext()

        compute_nodes = self._return_compute_nodes(ctxt)
        for compute_node in compute_nodes:
            compute_node.create()

        cell_mapping = objects.CellMapping(context=ctxt,
                                           uuid=uuidutils.generate_uuid(),
                                           database_connection='fake:///db',
                                           transport_url='fake:///mq')
        cell_mapping.create()

        mock_target_cell.return_value.__enter__.return_value = ctxt

        self.commands.discover_hosts(cell_uuid=cell_mapping.uuid)

        # Check that the host mappings were created
        for i, compute_node in enumerate(compute_nodes):
            host_mapping = objects.HostMapping.get_by_host(ctxt,
                                                           compute_node.host)
            self.assertEqual('host%s' % i, host_mapping.host)

        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))
        mock_cell_mapping_get_all.assert_not_called()

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    def test_discover_hosts_single_cell_no_new_hosts(
            self, mock_cell_mapping_get_all, mock_target_cell):
        ctxt = context.RequestContext()

        # Create some compute nodes and matching host mappings
        cell_mapping = objects.CellMapping(context=ctxt,
                                           uuid=uuidutils.generate_uuid(),
                                           database_connection='fake:///db',
                                           transport_url='fake:///mq')
        cell_mapping.create()

        compute_nodes = self._return_compute_nodes(ctxt)
        for compute_node in compute_nodes:
            compute_node.create()
            host_mapping = objects.HostMapping(context=ctxt,
                                               host=compute_node.host,
                                               cell_mapping=cell_mapping)
            host_mapping.create()

        with mock.patch('nova.objects.HostMapping.create') as mock_create:
            self.commands.discover_hosts(cell_uuid=cell_mapping.uuid)
            mock_create.assert_not_called()

        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext),
            test.MatchObjPrims(cell_mapping))
        mock_cell_mapping_get_all.assert_not_called()

    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_discover_hosts_multiple_cells(self,
                                           mock_cell_mapping_get_by_uuid):
        # Create in-memory databases for cell1 and cell2 to let target_cell
        # run for real. We want one compute node in cell1's db and the other
        # compute node in cell2's db.
        cell_dbs = nova_fixtures.CellDatabases()
        cell_dbs.add_cell_database('fake:///db1')
        cell_dbs.add_cell_database('fake:///db2')
        self.useFixture(cell_dbs)

        ctxt = context.RequestContext()

        cell_mapping0 = objects.CellMapping(
            context=ctxt,
            uuid=objects.CellMapping.CELL0_UUID,
            database_connection='fake:///db0',
            transport_url='none:///')
        cell_mapping0.create()
        cell_mapping1 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db1',
                                            transport_url='fake:///mq1')
        cell_mapping1.create()
        cell_mapping2 = objects.CellMapping(context=ctxt,
                                            uuid=uuidutils.generate_uuid(),
                                            database_connection='fake:///db2',
                                            transport_url='fake:///mq2')
        cell_mapping2.create()

        compute_nodes = self._return_compute_nodes(ctxt, num=2)
        # Create the first compute node in cell1's db
        with context.target_cell(ctxt, cell_mapping1) as cctxt:
            compute_nodes[0]._context = cctxt
            compute_nodes[0].create()
        # Create the first compute node in cell2's db
        with context.target_cell(ctxt, cell_mapping2) as cctxt:
            compute_nodes[1]._context = cctxt
            compute_nodes[1].create()

        self.commands.discover_hosts(verbose=True)
        output = self.output.getvalue().strip()
        self.assertNotEqual('', output)

        # Check that the host mappings were created
        for i, compute_node in enumerate(compute_nodes):
            host_mapping = objects.HostMapping.get_by_host(ctxt,
                                                           compute_node.host)
            self.assertEqual('host%s' % i, host_mapping.host)

        mock_cell_mapping_get_by_uuid.assert_not_called()

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts_strict(self, mock_discover_hosts):
        # Check for exit code 0 if unmapped hosts found
        mock_discover_hosts.return_value = ['fake']
        self.assertEqual(self.commands.discover_hosts(strict=True), 0)

        # Check for exit code 1 if no unmapped hosts are found
        mock_discover_hosts.return_value = []
        self.assertEqual(self.commands.discover_hosts(strict=True), 1)

        # Check the return when strict=False
        self.assertIsNone(self.commands.discover_hosts())

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts_by_service(self, mock_discover_hosts):
        mock_discover_hosts.return_value = ['fake']
        ret = self.commands.discover_hosts(by_service=True, strict=True)
        self.assertEqual(0, ret)
        mock_discover_hosts.assert_called_once_with(mock.ANY, None,
                                                    mock.ANY,
                                                    True)

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts_mapping_exists(self, mock_discover_hosts):
        mock_discover_hosts.side_effect = exception.HostMappingExists(
            name='fake')
        ret = self.commands.discover_hosts()
        output = self.output.getvalue().strip()
        self.assertEqual(2, ret)
        expected = ("ERROR: Duplicate host mapping was encountered. This "
                    "command should be run once after all compute hosts "
                    "have been deployed and should not be run in parallel. "
                    "When run in parallel, the commands will collide with "
                    "each other trying to map the same hosts in the database "
                    "at the same time. Error: Host 'fake' mapping already "
                    "exists")
        self.assertEqual(expected, output)

    def test_validate_transport_url_in_conf(self):
        from_conf = 'fake://user:pass@host:5672/'
        self.flags(transport_url=from_conf)
        self.assertEqual(from_conf,
                         self.commands._validate_transport_url(None))

    def test_validate_transport_url_on_command_line(self):
        from_cli = 'fake://user:pass@host:5672/'
        self.assertEqual(from_cli,
                         self.commands._validate_transport_url(from_cli))

    def test_validate_transport_url_missing(self):
        self.flags(transport_url=None)
        self.assertIsNone(self.commands._validate_transport_url(None))

    def test_validate_transport_url_favors_command_line(self):
        self.flags(transport_url='fake://user:pass@host:5672/')
        from_cli = 'fake://otheruser:otherpass@otherhost:5673'
        self.assertEqual(from_cli,
                         self.commands._validate_transport_url(from_cli))

    def test_validate_transport_url_invalid_url(self):
        self.assertIsNone(self.commands._validate_transport_url('not-a-url'))
        self.assertIn('Invalid transport URL', self.output.getvalue())

    def test_non_unique_transport_url_database_connection_checker(self):
        ctxt = context.RequestContext()
        cell1 = objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq1',
                            database_connection='fake:///db1')
        cell1.create()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell2,
                            name='cell2',
                            transport_url='fake://mq2',
                            database_connection='fake:///db2').create()
        resultf = self.commands.\
                    _non_unique_transport_url_database_connection_checker(
                                        ctxt, None,
                                        'fake://mq3', 'fake:///db3')
        resultt = self.commands.\
                    _non_unique_transport_url_database_connection_checker(
                                        ctxt, None,
                                        'fake://mq1', 'fake:///db1')
        resultd = self.commands.\
                    _non_unique_transport_url_database_connection_checker(
                                        ctxt, cell1,
                                        'fake://mq1', 'fake:///db1')

        self.assertFalse(resultf)
        self.assertTrue(resultt)
        self.assertFalse(resultd)
        self.assertIn('exists', self.output.getvalue())

    def test_create_cell_use_params(self):
        ctxt = context.get_context()
        kwargs = dict(
            name='fake-name',
            transport_url='http://fake-transport-url',
            database_connection='fake-db-connection')
        status = self.commands.create_cell(verbose=True, **kwargs)
        self.assertEqual(0, status)
        cell2_uuid = self.output.getvalue().strip()
        self.commands.create_cell(**kwargs)
        cell2 = objects.CellMapping.get_by_uuid(ctxt, cell2_uuid)
        self.assertEqual(kwargs['name'], cell2.name)
        self.assertEqual(kwargs['database_connection'],
                         cell2.database_connection)
        self.assertEqual(kwargs['transport_url'], cell2.transport_url)
        self.assertIs(cell2.disabled, False)

    def test_create_cell_use_params_with_template(self):
        ctxt = context.get_context()
        self.flags(transport_url='rabbit://host:1234')
        kwargs = dict(
            name='fake-name',
            transport_url='{scheme}://other-{hostname}:{port}',
            database_connection='fake-db-connection')
        status = self.commands.create_cell(verbose=True, **kwargs)
        self.assertEqual(0, status)
        cell2_uuid = self.output.getvalue().strip()
        self.commands.create_cell(**kwargs)

        # Make sure it ended up as a template in the database
        db_cm = objects.CellMapping._get_by_uuid_from_db(ctxt, cell2_uuid)
        self.assertEqual('{scheme}://other-{hostname}:{port}',
                         db_cm.transport_url)

        # Make sure it gets translated if we load by object
        cell2 = objects.CellMapping.get_by_uuid(ctxt, cell2_uuid)
        self.assertEqual(kwargs['name'], cell2.name)
        self.assertEqual(kwargs['database_connection'],
                         cell2.database_connection)
        self.assertEqual('rabbit://other-host:1234', cell2.transport_url)
        self.assertIs(cell2.disabled, False)

    def test_create_cell_use_config_values(self):
        settings = dict(
            transport_url='http://fake-conf-transport-url',
            database_connection='fake-conf-db-connection')
        self.flags(connection=settings['database_connection'],
                   group='database')
        self.flags(transport_url=settings['transport_url'])
        ctxt = context.get_context()

        status = self.commands.create_cell(verbose=True)
        self.assertEqual(0, status)
        cell1_uuid = self.output.getvalue().split('\n')[-2].strip()
        cell1 = objects.CellMapping.get_by_uuid(ctxt, cell1_uuid)
        self.assertIsNone(cell1.name)
        self.assertEqual(settings['database_connection'],
                         cell1.database_connection)
        self.assertEqual(settings['transport_url'], cell1.transport_url)

    def test_create_cell_failed_if_non_unique(self):
        kwargs = dict(
            name='fake-name',
            transport_url='http://fake-transport-url',
            database_connection='fake-db-connection')
        status1 = self.commands.create_cell(verbose=True, **kwargs)
        status2 = self.commands.create_cell(verbose=True, **kwargs)
        self.assertEqual(0, status1)
        self.assertEqual(2, status2)
        self.assertIn('exists', self.output.getvalue())

    def test_create_cell_failed_if_no_transport_url(self):
        self.flags(transport_url=None)
        status = self.commands.create_cell()
        self.assertEqual(1, status)
        self.assertIn('--transport-url', self.output.getvalue())

    def test_create_cell_failed_if_no_database_connection(self):
        self.flags(connection=None, group='database')
        status = self.commands.create_cell(transport_url='http://fake-url')
        self.assertEqual(1, status)
        self.assertIn('--database_connection', self.output.getvalue())

    def test_create_cell_pre_disabled(self):
        ctxt = context.get_context()
        kwargs = dict(
            name='fake-name1',
            transport_url='http://fake-transport-url1',
            database_connection='fake-db-connection1')
        status1 = self.commands.create_cell(verbose=True, disabled=True,
                                            **kwargs)
        self.assertEqual(0, status1)
        cell_uuid1 = self.output.getvalue().strip()
        cell1 = objects.CellMapping.get_by_uuid(ctxt, cell_uuid1)
        self.assertEqual(kwargs['name'], cell1.name)
        self.assertIs(cell1.disabled, True)

    def test_list_cells_verbose_false(self):
        ctxt = context.RequestContext()
        cell_mapping0 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map0,
            database_connection='fake://user1:pass1@host1/db0',
            transport_url='none://user1:pass1@host1/',
            name='cell0')
        cell_mapping0.create()
        cell_mapping1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map1,
            database_connection='fake://user1@host1/db0',
            transport_url='none://user1@host1/vhost1',
            name='cell1')
        cell_mapping1.create()
        self.assertEqual(0, self.commands.list_cells())
        output = self.output.getvalue().strip()
        self.assertEqual('''\
+-------+--------------------------------------+---------------------------+-----------------------------+----------+
|  Name |                 UUID                 |       Transport URL       |     Database Connection     | Disabled |
+-------+--------------------------------------+---------------------------+-----------------------------+----------+
| cell0 | %(uuid_map0)s |  none://user1:****@host1/ | fake://user1:****@host1/db0 |  False   |
| cell1 | %(uuid_map1)s | none://user1@host1/vhost1 |    fake://user1@host1/db0   |  False   |
+-------+--------------------------------------+---------------------------+-----------------------------+----------+''' %  # noqa
                {"uuid_map0": uuidsentinel.map0,
                 "uuid_map1": uuidsentinel.map1},
                output)

    def test_list_cells_multiple_sorted_verbose_true(self):
        ctxt = context.RequestContext()
        cell_mapping0 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map0,
            database_connection='fake:///db0', transport_url='none:///',
            name='cell0')
        cell_mapping0.create()
        cell_mapping1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map1,
            database_connection='fake:///dblon', transport_url='fake:///mqlon',
            name='london', disabled=True)
        cell_mapping1.create()
        cell_mapping2 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map2,
            database_connection='fake:///dbdal', transport_url='fake:///mqdal',
            name='dallas')
        cell_mapping2.create()
        no_name = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.none,
            database_connection='fake:///dbnone',
            transport_url='fake:///mqnone')
        no_name.create()
        self.assertEqual(0, self.commands.list_cells(verbose=True))
        output = self.output.getvalue().strip()
        self.assertEqual('''\
+--------+--------------------------------------+----------------+---------------------+----------+
|  Name  |                 UUID                 | Transport URL  | Database Connection | Disabled |
+--------+--------------------------------------+----------------+---------------------+----------+
|        | %(uuid_none)s | fake:///mqnone |    fake:///dbnone   |  False   |
| cell0  | %(uuid_map0)s |    none:///    |     fake:///db0     |  False   |
| dallas | %(uuid_map2)s | fake:///mqdal  |    fake:///dbdal    |  False   |
| london | %(uuid_map1)s | fake:///mqlon  |    fake:///dblon    |   True   |
+--------+--------------------------------------+----------------+---------------------+----------+''' %  # noqa
                {"uuid_map0": uuidsentinel.map0,
                 "uuid_map1": uuidsentinel.map1,
                 "uuid_map2": uuidsentinel.map2,
                 "uuid_none": uuidsentinel.none},
                output)

    def test_delete_cell_not_found(self):
        """Tests trying to delete a cell that is not found by uuid."""
        cell_uuid = uuidutils.generate_uuid()
        self.assertEqual(1, self.commands.delete_cell(cell_uuid))
        output = self.output.getvalue().strip()
        self.assertEqual('Cell with uuid %s was not found.' % cell_uuid,
                         output)

    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    def test_delete_cell_host_mappings_exist(self, mock_get_cn):
        """Tests trying to delete a cell which has host mappings."""
        cell_uuid = uuidutils.generate_uuid()
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=cell_uuid, database_connection='fake:///db',
            transport_url='fake:///mq')
        cm.create()
        # create a host mapping in this cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm)
        hm.create()
        mock_get_cn.return_value = []
        self.assertEqual(2, self.commands.delete_cell(cell_uuid))
        output = self.output.getvalue().strip()
        self.assertIn('There are existing hosts mapped to cell', output)

    @mock.patch.object(objects.InstanceList, 'get_all')
    def test_delete_cell_instance_mappings_exist_with_instances(
        self, mock_get_all):
        """Tests trying to delete a cell which has instance mappings."""
        cell_uuid = uuidutils.generate_uuid()
        ctxt = context.get_admin_context()
        mock_get_all.return_value = [objects.Instance(
            ctxt, uuid=uuidsentinel.instance)]
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=cell_uuid, database_connection='fake:///db',
            transport_url='fake:///mq')
        cm.create()
        # create an instance mapping in this cell
        im = objects.InstanceMapping(
            context=ctxt, instance_uuid=uuidutils.generate_uuid(),
            cell_mapping=cm, project_id=uuidutils.generate_uuid())
        im.create()
        self.assertEqual(3, self.commands.delete_cell(cell_uuid))
        output = self.output.getvalue().strip()
        self.assertIn('There are existing instances mapped to cell', output)

    @mock.patch.object(objects.InstanceList, 'get_all',
                       return_value=[])
    def test_delete_cell_instance_mappings_exist_without_instances(
        self, mock_get_all):
        """Tests trying to delete a cell which has instance mappings."""
        cell_uuid = uuidutils.generate_uuid()
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=cell_uuid, database_connection='fake:///db',
            transport_url='fake:///mq')
        cm.create()
        # create an instance mapping in this cell
        im = objects.InstanceMapping(
            context=ctxt, instance_uuid=uuidutils.generate_uuid(),
            cell_mapping=cm, project_id=uuidutils.generate_uuid())
        im.create()
        self.assertEqual(4, self.commands.delete_cell(cell_uuid))
        output = self.output.getvalue().strip()
        self.assertIn('There are instance mappings to cell with uuid', output)
        self.assertIn('but all instances have been deleted in the cell.',
                      output)
        self.assertIn("So execute 'nova-manage db archive_deleted_rows' to "
                      "delete the instance mappings.", output)

    def test_delete_cell_success_without_host_mappings(self):
        """Tests trying to delete an empty cell."""
        cell_uuid = uuidutils.generate_uuid()
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=cell_uuid, database_connection='fake:///db',
            transport_url='fake:///mq')
        cm.create()
        self.assertEqual(0, self.commands.delete_cell(cell_uuid))
        output = self.output.getvalue().strip()
        self.assertEqual('', output)

    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.HostMapping, 'destroy')
    @mock.patch.object(objects.CellMapping, 'destroy')
    def test_delete_cell_success_with_host_mappings(self, mock_cell_destroy,
                                            mock_hm_destroy, mock_get_cn):
        """Tests trying to delete a cell with host."""
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm.create()
        # create a host mapping in this cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm)
        hm.create()
        mock_get_cn.return_value = []
        self.assertEqual(0, self.commands.delete_cell(uuidsentinel.cell1,
                                                      force=True))
        output = self.output.getvalue().strip()
        self.assertEqual('', output)
        mock_hm_destroy.assert_called_once_with()
        mock_cell_destroy.assert_called_once_with()

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects.InstanceMapping, 'destroy')
    @mock.patch.object(objects.HostMapping, 'destroy')
    @mock.patch.object(objects.CellMapping, 'destroy')
    def test_delete_cell_force_with_inst_mappings_of_deleted_instances(self,
                                        mock_cell_destroy, mock_hm_destroy,
                                        mock_im_destroy, mock_target_cell):

        # Test for verifying the deletion of instance_mappings
        # of deleted instances when using the --force option
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm.create()
        mock_target_cell.return_value.__enter__.return_value = ctxt
        # create a host mapping in this cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm)
        hm.create()
        # create an instance and its mapping.
        inst_uuid = uuidutils.generate_uuid()
        proj_uuid = uuidutils.generate_uuid()
        instance = objects.Instance(ctxt, project_id=proj_uuid,
                                    uuid=inst_uuid)
        instance.create()

        im = objects.InstanceMapping(ctxt, project_id=proj_uuid,
                                     cell_mapping=cm,
                                     instance_uuid=inst_uuid)
        im.create()

        res = self.commands.delete_cell(uuidsentinel.cell1, force=True)
        self.assertEqual(3, res)
        output = self.output.getvalue().strip()
        self.assertIn('There are existing instances mapped to cell', output)

        # delete the instance such that we now have only its mapping
        instance.destroy()

        res = self.commands.delete_cell(uuidsentinel.cell1, force=True)
        self.assertEqual(0, res)
        mock_hm_destroy.assert_called_once_with()
        mock_cell_destroy.assert_called_once_with()
        mock_im_destroy.assert_called_once_with()
        self.assertEqual(4, mock_target_cell.call_count)

    def test_update_cell_not_found(self):
        self.assertEqual(1, self.commands.update_cell(
            uuidsentinel.cell1, 'foo', 'fake://new', 'fake:///new'))
        self.assertIn('not found', self.output.getvalue())

    def test_update_cell_failed_if_non_unique_transport_db_urls(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq1',
                            database_connection='fake:///db1').create()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell2,
                            name='cell2',
                            transport_url='fake://mq2',
                            database_connection='fake:///db2').create()
        cell2_update1 = self.commands.update_cell(
            uuidsentinel.cell2, 'foo', 'fake://mq1', 'fake:///db1')
        self.assertEqual(3, cell2_update1)
        self.assertIn('exists', self.output.getvalue())

        cell2_update2 = self.commands.update_cell(
            uuidsentinel.cell2, 'foo', 'fake://mq1', 'fake:///db3')
        self.assertEqual(3, cell2_update2)
        self.assertIn('exists', self.output.getvalue())

        cell2_update3 = self.commands.update_cell(
            uuidsentinel.cell2, 'foo', 'fake://mq3', 'fake:///db1')
        self.assertEqual(3, cell2_update3)
        self.assertIn('exists', self.output.getvalue())

        cell2_update4 = self.commands.update_cell(
            uuidsentinel.cell2, 'foo', 'fake://mq3', 'fake:///db3')
        self.assertEqual(0, cell2_update4)

    def test_update_cell_failed(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        with mock.patch('nova.objects.CellMapping.save') as mock_save:
            mock_save.side_effect = Exception
            self.assertEqual(2, self.commands.update_cell(
                uuidsentinel.cell1, 'foo', 'fake://new', 'fake:///new'))
        self.assertIn('Unable to update', self.output.getvalue())

    def test_update_cell_success(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        self.assertEqual(0, self.commands.update_cell(
            uuidsentinel.cell1, 'foo', 'fake://new', 'fake:///new'))
        cm = objects.CellMapping.get_by_uuid(ctxt, uuidsentinel.cell1)
        self.assertEqual('foo', cm.name)
        self.assertEqual('fake://new', cm.transport_url)
        self.assertEqual('fake:///new', cm.database_connection)
        output = self.output.getvalue().strip()
        self.assertEqual('', output)

    def test_update_cell_success_defaults(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        self.assertEqual(0, self.commands.update_cell(uuidsentinel.cell1))
        cm = objects.CellMapping.get_by_uuid(ctxt, uuidsentinel.cell1)
        self.assertEqual('cell1', cm.name)
        expected_transport_url = CONF.transport_url or 'fake://mq'
        self.assertEqual(expected_transport_url, cm.transport_url)
        expected_db_connection = CONF.database.connection or 'fake:///db'
        self.assertEqual(expected_db_connection, cm.database_connection)
        output = self.output.getvalue().strip()
        lines = output.split('\n')
        self.assertIn('using the value [DEFAULT]/transport_url', lines[0])
        self.assertIn('using the value [database]/connection', lines[1])
        self.assertEqual(2, len(lines))

    def test_update_cell_disable_and_enable(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        self.assertEqual(4, self.commands.update_cell(uuidsentinel.cell1,
                                                      disable=True,
                                                      enable=True))
        output = self.output.getvalue().strip()
        self.assertIn('Cell cannot be disabled and enabled at the same '
                      'time.', output)

    def test_update_cell_disable_cell0(self):
        ctxt = context.get_admin_context()
        uuid0 = objects.CellMapping.CELL0_UUID
        objects.CellMapping(context=ctxt, uuid=uuid0, name='cell0',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        self.assertEqual(5, self.commands.update_cell(uuid0, disable=True))
        output = self.output.getvalue().strip()
        self.assertIn('Cell0 cannot be disabled.', output)

    def test_update_cell_disable_success(self):
        ctxt = context.get_admin_context()
        uuid = uuidsentinel.cell1
        objects.CellMapping(context=ctxt, uuid=uuid,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        cm = objects.CellMapping.get_by_uuid(ctxt, uuid)
        self.assertFalse(cm.disabled)
        self.assertEqual(0, self.commands.update_cell(uuid, disable=True))
        cm = objects.CellMapping.get_by_uuid(ctxt, uuid)
        self.assertTrue(cm.disabled)
        output = self.output.getvalue().strip()
        lines = output.split('\n')
        self.assertIn('using the value [DEFAULT]/transport_url', lines[0])
        self.assertIn('using the value [database]/connection', lines[1])
        self.assertEqual(2, len(lines))

    def test_update_cell_enable_success(self):
        ctxt = context.get_admin_context()
        uuid = uuidsentinel.cell1
        objects.CellMapping(context=ctxt, uuid=uuid,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db',
                            disabled=True).create()
        cm = objects.CellMapping.get_by_uuid(ctxt, uuid)
        self.assertTrue(cm.disabled)
        self.assertEqual(0, self.commands.update_cell(uuid, enable=True))
        cm = objects.CellMapping.get_by_uuid(ctxt, uuid)
        self.assertFalse(cm.disabled)
        output = self.output.getvalue().strip()
        lines = output.split('\n')
        self.assertIn('using the value [DEFAULT]/transport_url', lines[0])
        self.assertIn('using the value [database]/connection', lines[1])
        self.assertEqual(2, len(lines))

    def test_update_cell_disable_already_disabled(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db',
                            disabled=True).create()
        cm = objects.CellMapping.get_by_uuid(ctxt, uuidsentinel.cell1)
        self.assertTrue(cm.disabled)
        self.assertEqual(0, self.commands.update_cell(uuidsentinel.cell1,
                                                      disable=True))
        self.assertTrue(cm.disabled)
        output = self.output.getvalue().strip()
        self.assertIn('is already disabled', output)

    def test_update_cell_enable_already_enabled(self):
        ctxt = context.get_admin_context()
        objects.CellMapping(context=ctxt, uuid=uuidsentinel.cell1,
                            name='cell1',
                            transport_url='fake://mq',
                            database_connection='fake:///db').create()
        cm = objects.CellMapping.get_by_uuid(ctxt, uuidsentinel.cell1)
        self.assertFalse(cm.disabled)
        self.assertEqual(0, self.commands.update_cell(uuidsentinel.cell1,
                                                      enable=True))
        self.assertFalse(cm.disabled)
        output = self.output.getvalue().strip()
        self.assertIn('is already enabled', output)

    def test_list_hosts(self):
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map0, name='london',
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        cm2 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map1, name='dallas',
            database_connection='fake:///db', transport_url='fake:///mq')
        cm2.create()
        # create a host mapping in another cell
        hm1 = objects.HostMapping(
            context=ctxt, host='fake-host-1', cell_mapping=cm1)
        hm1.create()
        hm2 = objects.HostMapping(
            context=ctxt, host='fake-host-2', cell_mapping=cm2)
        hm2.create()
        self.assertEqual(0, self.commands.list_hosts())
        output = self.output.getvalue().strip()
        self.assertEqual('''\
+-----------+--------------------------------------+-------------+
| Cell Name |              Cell UUID               |   Hostname  |
+-----------+--------------------------------------+-------------+
|   london  | %(uuid_map0)s | fake-host-1 |
|   dallas  | %(uuid_map1)s | fake-host-2 |
+-----------+--------------------------------------+-------------+''' %
                {"uuid_map0": uuidsentinel.map0,
                 "uuid_map1": uuidsentinel.map1},
                output)

    def test_list_hosts_in_cell(self):
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map0, name='london',
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        cm2 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.map1, name='dallas',
            database_connection='fake:///db', transport_url='fake:///mq')
        cm2.create()
        # create a host mapping in another cell
        hm1 = objects.HostMapping(
            context=ctxt, host='fake-host-1', cell_mapping=cm1)
        hm1.create()
        hm2 = objects.HostMapping(
            context=ctxt, host='fake-host-2', cell_mapping=cm2)
        hm2.create()
        self.assertEqual(0, self.commands.list_hosts(
            cell_uuid=uuidsentinel.map0))
        output = self.output.getvalue().strip()
        self.assertEqual('''\
+-----------+--------------------------------------+-------------+
| Cell Name |              Cell UUID               |   Hostname  |
+-----------+--------------------------------------+-------------+
|   london  | %(uuid_map0)s | fake-host-1 |
+-----------+--------------------------------------+-------------+''' %
                {"uuid_map0": uuidsentinel.map0},
                output)

    def test_list_hosts_cell_not_found(self):
        """Tests trying to delete a host but a specified cell is not found."""
        self.assertEqual(1, self.commands.list_hosts(
            cell_uuid=uuidsentinel.cell1))
        output = self.output.getvalue().strip()
        self.assertEqual(
            'Cell with uuid %s was not found.' % uuidsentinel.cell1, output)

    def test_delete_host_cell_not_found(self):
        """Tests trying to delete a host but a specified cell is not found."""
        self.assertEqual(1, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual(
            'Cell with uuid %s was not found.' % uuidsentinel.cell1, output)

    def test_delete_host_host_not_found(self):
        """Tests trying to delete a host but the host is not found."""
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm.create()
        self.assertEqual(2, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual('The host fake-host was not found.', output)

    def test_delete_host_host_not_in_cell(self):
        """Tests trying to delete a host
        but the host does not belongs to a specified cell.
        """
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        cm2 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell2,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm2.create()
        # create a host mapping in another cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm2)
        hm.create()
        self.assertEqual(3, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual(('The host fake-host was not found in the cell %s.' %
                          uuidsentinel.cell1), output)

    @mock.patch.object(objects.InstanceList, 'get_by_host')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_delete_host_instances_exist(self, mock_get_cn, mock_get_by_host):
        """Tests trying to delete a host but the host has instances."""
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        # create a host mapping in the cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm1)
        hm.create()
        mock_get_by_host.return_value = [objects.Instance(
            ctxt, uuid=uuidsentinel.instance)]
        mock_get_cn.return_value = []
        self.assertEqual(4, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual('There are instances on the host fake-host.', output)
        mock_get_by_host.assert_called_once_with(
            test.MatchType(context.RequestContext), 'fake-host')

    @mock.patch.object(objects.InstanceList, 'get_by_host',
                       return_value=[])
    @mock.patch.object(objects.HostMapping, 'destroy')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host')
    def test_delete_host_success(self, mock_get_cn, mock_destroy,
                                 mock_get_by_host):
        """Tests trying to delete a host that has no instances."""
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        # create a host mapping in the cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm1)
        hm.create()

        mock_get_cn.return_value = [mock.MagicMock(), mock.MagicMock()]

        self.assertEqual(0, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual('', output)
        mock_get_by_host.assert_called_once_with(
            test.MatchType(context.RequestContext), 'fake-host')
        mock_destroy.assert_called_once_with()
        for node in mock_get_cn.return_value:
            self.assertEqual(0, node.mapped)
            node.save.assert_called_once_with()

    @mock.patch.object(objects.InstanceList, 'get_by_host',
                       return_value=[])
    @mock.patch.object(objects.HostMapping, 'destroy')
    @mock.patch.object(objects.ComputeNodeList, 'get_all_by_host',
        side_effect=exception.ComputeHostNotFound(host='fake-host'))
    def test_delete_host_success_compute_host_not_found(self, mock_get_cn,
                                                        mock_destroy,
                                                        mock_get_by_host):
        """Tests trying to delete a host that has no instances, but cannot
           be found by ComputeNodeList.get_all_by_host.
        """
        ctxt = context.get_admin_context()
        # create the cell mapping
        cm1 = objects.CellMapping(
            context=ctxt, uuid=uuidsentinel.cell1,
            database_connection='fake:///db', transport_url='fake:///mq')
        cm1.create()
        # create a host mapping in the cell
        hm = objects.HostMapping(
            context=ctxt, host='fake-host', cell_mapping=cm1)
        hm.create()

        self.assertEqual(0, self.commands.delete_host(uuidsentinel.cell1,
                                                      'fake-host'))
        output = self.output.getvalue().strip()
        self.assertEqual('', output)
        mock_get_by_host.assert_called_once_with(
            test.MatchType(context.RequestContext), 'fake-host')
        mock_destroy.assert_called_once_with()
        mock_get_cn.assert_called_once_with(
            test.MatchType(context.RequestContext), 'fake-host')


@ddt.ddt
class TestNovaManagePlacement(test.NoDBTestCase):
    """Unit tests for the nova-manage placement commands.

    Tests in this class should be simple and can rely on mock, so they
    are usually restricted to negative or side-effect type tests.

    For more involved functional scenarios, use
    nova.tests.functional.test_nova_manage.
    """
    def setUp(self):
        super(TestNovaManagePlacement, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.cli = manage.PlacementCommands()
        self.useFixture(fixtures.MockPatch('nova.network.neutron.get_client'))

    def test_heal_allocations_with_cell_instance_id(self):
        """Test heal allocation with both cell id and instance id"""
        cell_uuid = uuidutils.generate_uuid()
        instance_uuid = uuidutils.generate_uuid()
        self.assertEqual(127, self.cli.heal_allocations(
                        instance_uuid=instance_uuid,
                        cell_uuid=cell_uuid))
        self.assertIn('The --cell and --instance options',
        self.output.getvalue())

    @mock.patch('nova.objects.CellMapping.get_by_uuid',
                side_effect=exception.CellMappingNotFound(uuid='fake'))
    def test_heal_allocations_with_cell_id_not_found(self, mock_get):
        """Test the case where cell_id is not found"""
        self.assertEqual(127, self.cli.heal_allocations(cell_uuid='fake'))
        output = self.output.getvalue().strip()
        self.assertEqual('Cell with uuid fake was not found.', output)

    @ddt.data(-1, 0, "one")
    def test_heal_allocations_invalid_max_count(self, max_count):
        self.assertEqual(127, self.cli.heal_allocations(max_count=max_count))

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList())
    def test_heal_allocations_no_cells(self, mock_get_all_cells):
        self.assertEqual(4, self.cli.heal_allocations(verbose=True))
        self.assertIn('No cells to process', self.output.getvalue())

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)]))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                return_value=objects.InstanceList())
    def test_heal_allocations_no_instances(
            self, mock_get_instances, mock_get_all_cells):
        self.assertEqual(4, self.cli.heal_allocations(verbose=True))
        self.assertIn('Processed 0 instances.', self.output.getvalue())

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)]))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                return_value=objects.InstanceList(objects=[
                    objects.Instance(
                        uuid=uuidsentinel.instance, host='fake', node='fake',
                        task_state=None)]))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer', return_value={})
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename',
                side_effect=exception.ComputeHostNotFound(host='fake'))
    def test_heal_allocations_compute_host_not_found(
            self, mock_get_compute_node, mock_get_allocs, mock_get_instances,
            mock_get_all_cells):
        self.assertEqual(2, self.cli.heal_allocations())
        self.assertIn('Compute host fake could not be found.',
                      self.output.getvalue())

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)]))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                return_value=objects.InstanceList(objects=[
                    objects.Instance(
                        uuid=uuidsentinel.instance, host='fake', node='fake',
                        task_state=None, flavor=objects.Flavor(),
                        project_id='fake-project', user_id='fake-user')]))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer', return_value={})
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename',
                return_value=objects.ComputeNode(uuid=uuidsentinel.node))
    @mock.patch('nova.scheduler.utils.resources_from_flavor',
                return_value={'VCPU': 1})
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put',
                return_value=fake_requests.FakeResponse(
                    500, content=jsonutils.dumps({"errors": [{"code": ""}]})))
    def test_heal_allocations_put_allocations_fails(
            self, mock_put_allocations, mock_res_from_flavor,
            mock_get_compute_node, mock_get_allocs, mock_get_instances,
            mock_get_all_cells):
        self.assertEqual(3, self.cli.heal_allocations())
        self.assertIn('Failed to update allocations for consumer',
                      self.output.getvalue())
        instance = mock_get_instances.return_value[0]
        mock_res_from_flavor.assert_called_once_with(
            instance, instance.flavor)

        expected_payload = {
            'allocations': {
                uuidsentinel.node: {
                    'resources': {'VCPU': 1}
                }
            },
            'user_id': 'fake-user',
            'project_id': 'fake-project',
            'consumer_generation': None
        }
        mock_put_allocations.assert_called_once_with(
            '/allocations/%s' % instance.uuid, expected_payload,
            global_request_id=mock.ANY, version='1.28')

    @mock.patch('nova.objects.CellMappingList.get_all',
                new=mock.Mock(return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)])))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                new=mock.Mock(return_value=objects.InstanceList(objects=[
                    objects.Instance(
                        uuid=uuidsentinel.instance, host='fake', node='fake',
                        task_state=None, flavor=objects.Flavor(),
                        project_id='fake-project', user_id='fake-user')])))
    def test_heal_allocations_get_allocs_placement_fails(self):
        self.assertEqual(3, self.cli.heal_allocations())
        output = self.output.getvalue()
        self.assertIn('Allocation retrieval failed', output)
        # Having not mocked get_allocs_for_consumer, we get MissingAuthPlugin.
        self.assertIn('An auth plugin is required', output)

    @mock.patch('nova.objects.CellMappingList.get_all',
                new=mock.Mock(return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)])))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                side_effect=[
                    objects.InstanceList(objects=[objects.Instance(
                        uuid=uuidsentinel.instance, host='fake', node='fake',
                        task_state=None, flavor=objects.Flavor(),
                        project_id='fake-project', user_id='fake-user')]),
                    objects.InstanceList(objects=[])])
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer',
                new=mock.Mock(
                    side_effect=exception.ConsumerAllocationRetrievalFailed(
                        consumer_uuid='CONSUMER', error='ERROR')))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put',
                new_callable=mock.NonCallableMagicMock)
    def test_heal_allocations_get_allocs_retrieval_fails(self, mock_put,
                                                         mock_getinst):
        self.assertEqual(3, self.cli.heal_allocations())

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)]))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                # Called twice, first returns 1 instance, second returns []
                side_effect=(
                    objects.InstanceList(objects=[
                        objects.Instance(
                            uuid=uuidsentinel.instance, host='fake',
                            node='fake', task_state=None,
                            project_id='fake-project', user_id='fake-user')]),
                    objects.InstanceList()))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer')
    @mock.patch('nova.objects.ComputeNode.get_by_host_and_nodename',
                new_callable=mock.NonCallableMock)  # assert not called
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put',
                return_value=fake_requests.FakeResponse(204))
    def test_heal_allocations(
            self, mock_put, mock_get_compute_node, mock_get_allocs,
            mock_get_instances, mock_get_all_cells):
        """Tests the scenario that there are allocations created using
        placement API microversion < 1.8 where project/user weren't provided.
        The allocations will be re-put with the instance project_id/user_id
        values. Note that GET /allocations/{consumer_id} since commit f44965010
        will create the missing consumer record using the config option
        sentinels for project and user, so we won't get null back for the
        consumer project/user.
        """
        mock_get_allocs.return_value = {
            "allocations": {
                "92637880-2d79-43c6-afab-d860886c6391": {
                    "generation": 2,
                    "resources": {
                        "DISK_GB": 50,
                        "MEMORY_MB": 512,
                        "VCPU": 2
                    }
                }
            },
            "project_id": uuidsentinel.project_id,
            "user_id": uuidsentinel.user_id,
            "consumer_generation": 12,
        }
        self.assertEqual(0, self.cli.heal_allocations(verbose=True))
        self.assertIn('Processed 1 instances.', self.output.getvalue())
        mock_get_allocs.assert_called_once_with(
            test.MatchType(context.RequestContext), uuidsentinel.instance)
        expected_put_data = mock_get_allocs.return_value
        expected_put_data['project_id'] = 'fake-project'
        expected_put_data['user_id'] = 'fake-user'
        mock_put.assert_called_once_with(
            '/allocations/%s' % uuidsentinel.instance, expected_put_data,
            global_request_id=mock.ANY, version='1.28')

    @mock.patch('nova.objects.CellMappingList.get_all',
                return_value=objects.CellMappingList(objects=[
                    objects.CellMapping(name='cell1',
                                        uuid=uuidsentinel.cell1)]))
    @mock.patch('nova.objects.InstanceList.get_by_filters',
                return_value=objects.InstanceList(objects=[
                    objects.Instance(
                        uuid=uuidsentinel.instance, host='fake', node='fake',
                        task_state=None, project_id='fake-project',
                        user_id='fake-user')]))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.put',
                return_value=fake_requests.FakeResponse(
                    409,
                    content=jsonutils.dumps(
                        {"errors": [
                            {"code": "placement.concurrent_update",
                             "detail": "consumer generation conflict"}]})))
    def test_heal_allocations_put_fails(
            self, mock_put, mock_get_allocs, mock_get_instances,
            mock_get_all_cells):
        """Tests the scenario that there are allocations created using
        placement API microversion < 1.8 where project/user weren't provided
        and there was no consumer. The allocations will be re-put with the
        instance project_id/user_id values but that fails with a 409 so a
        return code of 3 is expected from the command.
        """
        mock_get_allocs.return_value = {
            "allocations": {
                "92637880-2d79-43c6-afab-d860886c6391": {
                    "generation": 2,
                    "resources": {
                        "DISK_GB": 50,
                        "MEMORY_MB": 512,
                        "VCPU": 2
                    }
                }
            },
            "project_id": uuidsentinel.project_id,
            "user_id": uuidsentinel.user_id
        }
        self.assertEqual(3, self.cli.heal_allocations(verbose=True))
        self.assertIn(
            'consumer generation conflict', self.output.getvalue())
        mock_get_allocs.assert_called_once_with(
            test.MatchType(context.RequestContext), uuidsentinel.instance)
        expected_put_data = mock_get_allocs.return_value
        expected_put_data['project_id'] = 'fake-project'
        expected_put_data['user_id'] = 'fake-user'
        mock_put.assert_called_once_with(
            '/allocations/%s' % uuidsentinel.instance, expected_put_data,
            global_request_id=mock.ANY, version='1.28')

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'])]))
    @mock.patch('nova.objects.HostMapping.get_by_host',
                side_effect=exception.HostMappingNotFound(name='host1'))
    def test_sync_aggregates_host_mapping_not_found(
            self, mock_get_host_mapping, mock_get_aggs):
        """Tests that we handle HostMappingNotFound."""
        result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(4, result)
        self.assertIn('The following hosts were found in nova host aggregates '
                      'but no host mappings were found in the nova API DB. '
                      'Run "nova-manage cell_v2 discover_hosts" and then '
                      'retry. Missing: host1', self.output.getvalue())

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'])]))
    @mock.patch('nova.objects.HostMapping.get_by_host',
                return_value=objects.HostMapping(
                    host='host1', cell_mapping=objects.CellMapping()))
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host',
                return_value=objects.ComputeNodeList(objects=[
                    objects.ComputeNode(hypervisor_hostname='node1'),
                    objects.ComputeNode(hypervisor_hostname='node2')]))
    @mock.patch('nova.context.target_cell')
    def test_sync_aggregates_too_many_computes_for_host(
            self, mock_target_cell, mock_get_nodes, mock_get_host_mapping,
            mock_get_aggs):
        """Tests the scenario that a host in an aggregate has more than one
        compute node so the command does not know which compute node uuid to
        use for the placement resource provider aggregate and fails.
        """
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(1, result)
        self.assertIn('Unexpected number of compute node records '
                      '(2) found for host host1. There should '
                      'only be a one-to-one mapping.', self.output.getvalue())
        mock_get_nodes.assert_called_once_with(
            mock.sentinel.cell_context, 'host1')

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'])]))
    @mock.patch('nova.objects.HostMapping.get_by_host',
                return_value=objects.HostMapping(
                    host='host1', cell_mapping=objects.CellMapping()))
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host',
                side_effect=exception.ComputeHostNotFound(host='host1'))
    @mock.patch('nova.context.target_cell')
    def test_sync_aggregates_compute_not_found(
            self, mock_target_cell, mock_get_nodes, mock_get_host_mapping,
            mock_get_aggs):
        """Tests the scenario that no compute node record is found for a given
        host in an aggregate.
        """
        mock_target_cell.return_value.__enter__.return_value = (
            mock.sentinel.cell_context)
        result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(5, result)
        self.assertIn('Unable to find matching compute_nodes record entries '
                      'in the cell database for the following hosts; does the '
                      'nova-compute service on each host need to be '
                      'restarted? Missing: host1', self.output.getvalue())
        mock_get_nodes.assert_called_once_with(
            mock.sentinel.cell_context, 'host1')

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                new=mock.Mock(return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'],
                                      uuid=uuidsentinel.aggregate)])))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    def test_sync_aggregates_get_provider_aggs_placement_server_error(
            self, mock_agg_add):
        """Tests the scenario that placement returns an unexpected server
        error when getting aggregates for a given resource provider.
        """
        mock_agg_add.side_effect = (
            exception.ResourceProviderAggregateRetrievalFailed(
                uuid=uuidsentinel.rp_uuid))
        with mock.patch.object(self.cli, '_get_rp_uuid_for_host',
                               return_value=uuidsentinel.rp_uuid):
            result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(2, result)
        self.assertIn('Failed to get aggregates for resource provider with '
                      'UUID %s' % uuidsentinel.rp_uuid,
                      self.output.getvalue())

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                new=mock.Mock(return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'],
                                      uuid=uuidsentinel.aggregate)])))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    def test_sync_aggregates_put_aggregates_fails_provider_not_found(
            self, mock_agg_add):
        """Tests the scenario that we are trying to add a provider to an
        aggregate in placement but the
        PUT /resource_providers/{rp_uuid}/aggregates call fails with a 404
        because the provider is not found.
        """
        mock_agg_add.side_effect = exception.ResourceProviderNotFound(
            name_or_uuid=uuidsentinel.rp_uuid)
        with mock.patch.object(self.cli, '_get_rp_uuid_for_host',
                               return_value=uuidsentinel.rp_uuid):
            result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(6, result)
        self.assertIn('Unable to find matching resource provider record in '
                      'placement with uuid for the following hosts: '
                      '(host1=%s)' % uuidsentinel.rp_uuid,
                      self.output.getvalue())
        mock_agg_add.assert_called_once_with(
            mock.ANY, uuidsentinel.aggregate, rp_uuid=uuidsentinel.rp_uuid)

    @mock.patch('nova.compute.api.AggregateAPI.get_aggregate_list',
                new=mock.Mock(return_value=objects.AggregateList(objects=[
                    objects.Aggregate(name='foo', hosts=['host1'],
                                      uuid=uuidsentinel.aggregate)])))
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'aggregate_add_host')
    def test_sync_aggregates_put_aggregates_fails_generation_conflict(
            self, mock_agg_add):
        """Tests the scenario that we are trying to add a provider to an
        aggregate in placement but the
        PUT /resource_providers/{rp_uuid}/aggregates call fails with a 409
        generation conflict (even after retries).
        """
        mock_agg_add.side_effect = exception.ResourceProviderUpdateConflict(
            uuid=uuidsentinel.rp_uuid, generation=1, error="Conflict!")
        with mock.patch.object(self.cli, '_get_rp_uuid_for_host',
                               return_value=uuidsentinel.rp_uuid):
            result = self.cli.sync_aggregates(verbose=True)
        self.assertEqual(3, result)
        self.assertIn("Failed updating provider aggregates for "
                      "host (host1), provider (%s) and aggregate "
                      "(%s)." % (uuidsentinel.rp_uuid, uuidsentinel.aggregate),
                      self.output.getvalue())
        self.assertIn("Conflict!", self.output.getvalue())

    def test_has_request_but_no_allocation(self):
        # False because there is a full resource_request and allocation set.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.healed,
                    'resource_request': {
                        'resources': {
                            'NET_BW_EGR_KILOBIT_PER_SEC': 1000,
                        },
                        'required': [
                            'CUSTOM_VNIC_TYPE_NORMAL'
                        ]
                    },
                    'binding:profile': {'allocation': uuidsentinel.rp1}
                }))
        # True because there is a full resource_request but no allocation set.
        self.assertTrue(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.needs_healing,
                    'resource_request': {
                        'resources': {
                            'NET_BW_EGR_KILOBIT_PER_SEC': 1000,
                        },
                        'required': [
                            'CUSTOM_VNIC_TYPE_NORMAL'
                        ]
                    },
                    'binding:profile': {}
                }))
        # True because there is a full resource_request but no allocation set.
        self.assertTrue(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.needs_healing_null_profile,
                    'resource_request': {
                        'resources': {
                            'NET_BW_EGR_KILOBIT_PER_SEC': 1000,
                        },
                        'required': [
                            'CUSTOM_VNIC_TYPE_NORMAL'
                        ]
                    },
                    'binding:profile': None,
                }))
        # False because there are no resources in the resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.empty_resources,
                    'resource_request': {
                        'resources': {},
                        'required': [
                            'CUSTOM_VNIC_TYPE_NORMAL'
                        ]
                    },
                    'binding:profile': {}
                }))
        # False because there are no resources in the resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.missing_resources,
                    'resource_request': {
                        'required': [
                            'CUSTOM_VNIC_TYPE_NORMAL'
                        ]
                    },
                    'binding:profile': {}
                }))
        # False because there are no required traits in the resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.empty_required,
                    'resource_request': {
                        'resources': {
                            'NET_BW_EGR_KILOBIT_PER_SEC': 1000,
                        },
                        'required': []
                    },
                    'binding:profile': {}
                }))
        # False because there are no required traits in the resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.missing_required,
                    'resource_request': {
                        'resources': {
                            'NET_BW_EGR_KILOBIT_PER_SEC': 1000,
                        },
                    },
                    'binding:profile': {}
                }))
        # False because there are no resources or required traits in the
        # resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.empty_resource_request,
                    'resource_request': {},
                    'binding:profile': {}
                }))
        # False because there is no resource_request.
        self.assertFalse(
            self.cli._has_request_but_no_allocation(
                {
                    'id': uuidsentinel.missing_resource_request,
                    'binding:profile': {}
                }))

    def test_update_ports_only_updates_binding_profile(self):
        """Simple test to make sure that only the port's binding:profile is
        updated based on the provided port dict's binding:profile and not
        just the binding:profile allocation key or other fields on the port.
        """
        neutron = mock.Mock()
        output = mock.Mock()
        binding_profile = {
            'allocation': uuidsentinel.rp_uuid,
            'foo': 'bar'
        }
        ports_to_update = [{
            'id': uuidsentinel.port_id,
            'binding:profile': binding_profile,
            'bar': 'baz'
        }]
        self.cli._update_ports(neutron, ports_to_update, output)
        expected_update_body = {
            'port': {
                'binding:profile': binding_profile
            }
        }
        neutron.update_port.assert_called_once_with(
            uuidsentinel.port_id, body=expected_update_body)

    def test_audit_with_wrong_provider_uuid(self):
        with mock.patch.object(
                self.cli, '_get_resource_provider',
                side_effect=exception.ResourceProviderNotFound(
                    name_or_uuid=uuidsentinel.fake_uuid)):
            ret = self.cli.audit(
                provider_uuid=uuidsentinel.fake_uuid)
        self.assertEqual(127, ret)
        output = self.output.getvalue()
        self.assertIn(
            'Resource provider with UUID %s' % uuidsentinel.fake_uuid,
            output)

    @mock.patch.object(manage.PlacementCommands,
                       '_check_orphaned_allocations_for_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.get')
    def _test_audit(self, get_resource_providers, check_orphaned_allocs,
                     verbose=False, delete=False, errors=False, found=False):
        rps = [
              {"generation": 1,
               "uuid": uuidsentinel.rp1,
               "links": None,
               "name": "rp1",
               "parent_provider_uuid": None,
               "root_provider_uuid": uuidsentinel.rp1},
              {"generation": 1,
               "uuid": uuidsentinel.rp2,
               "links": None,
               "name": "rp2",
               "parent_provider_uuid": None,
               "root_provider_uuid": uuidsentinel.rp2},
              ]
        get_resource_providers.return_value = fake_requests.FakeResponse(
            200, content=jsonutils.dumps({"resource_providers": rps}))

        if errors:
            # We found one orphaned allocation per RP but RP1 got a fault
            check_orphaned_allocs.side_effect = ((1, 1), (1, 0))
        elif found:
            # we found one orphaned allocation per RP and we had no faults
            check_orphaned_allocs.side_effect = ((1, 0), (1, 0))
        else:
            # No orphaned allocations are found for all the RPs
            check_orphaned_allocs.side_effect = ((0, 0), (0, 0))

        ret = self.cli.audit(verbose=verbose, delete=delete)
        if errors:
            # Any fault stops the audit and provides a return code equals to 1
            expected_ret = 1
        elif found and delete:
            # We found orphaned allocations and deleted them
            expected_ret = 4
        elif found and not delete:
            # We found orphaned allocations but we left them
            expected_ret = 3
        else:
            # Nothing was found
            expected_ret = 0
        self.assertEqual(expected_ret, ret)

        call1 = mock.call(mock.ANY, mock.ANY, mock.ANY, rps[0], delete)
        call2 = mock.call(mock.ANY, mock.ANY, mock.ANY, rps[1], delete)
        if errors:
            # We stop checking other RPs once we got a fault
            check_orphaned_allocs.assert_has_calls([call1])
        else:
            # All the RPs are checked
            check_orphaned_allocs.assert_has_calls([call1, call2])

        if verbose and found:
            output = self.output.getvalue()
            self.assertIn('Processed 2 allocations', output)
        if errors:
            output = self.output.getvalue()
            self.assertIn(
                'The Resource Provider %s had problems' % rps[0]["uuid"],
                output)

    def test_audit_not_found_orphaned_allocs(self):
        self._test_audit(found=False)

    def test_audit_found_orphaned_allocs_not_verbose(self):
        self._test_audit(found=True)

    def test_audit_found_orphaned_allocs_verbose(self):
        self._test_audit(found=True, verbose=True)

    def test_audit_found_orphaned_allocs_and_deleted_them(self):
        self._test_audit(found=True, delete=True)

    def test_audit_found_orphaned_allocs_but_got_errors(self):
        self._test_audit(errors=True)

    @mock.patch.object(manage.PlacementCommands,
                       '_delete_allocations_from_consumer')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocations_for_resource_provider')
    @mock.patch.object(manage.PlacementCommands,
                       '_get_instances_and_current_migrations')
    def test_check_orphaned_allocations_for_provider(self,
                                                     get_insts_and_migs,
                                                     get_allocs_for_rp,
                                                     delete_allocs):
        provider = {"generation": 1,
                    "uuid": uuidsentinel.rp1,
                    "links": None,
                    "name": "rp1",
                    "parent_provider_uuid": None,
                    "root_provider_uuid": uuidsentinel.rp1}
        compute_resources = {'VCPU': 1, 'MEMORY_MB': 2048, 'DISK_GB': 20}
        allocations = {
            # Some orphaned compute allocation
            uuidsentinel.orphaned_alloc1: {'resources': compute_resources},
            # Some existing instance allocation
            uuidsentinel.inst1: {'resources': compute_resources},
            # Some existing migration allocation
            uuidsentinel.mig1: {'resources': compute_resources},
            # Some other allocation not related to Nova
            uuidsentinel.other_alloc1: {'resources': {'CUSTOM_GOO'}},
        }

        get_insts_and_migs.return_value = (
            [uuidsentinel.inst1],
            [uuidsentinel.mig1])
        get_allocs_for_rp.return_value = report.ProviderAllocInfo(allocations)

        ctxt = context.RequestContext()
        placement = report.SchedulerReportClient()
        ret = self.cli._check_orphaned_allocations_for_provider(
            ctxt, placement, lambda x: x, provider, True)
        get_allocs_for_rp.assert_called_once_with(ctxt, uuidsentinel.rp1)
        delete_allocs.assert_called_once_with(ctxt, placement, provider,
                                              uuidsentinel.orphaned_alloc1,
                                              'instance')
        self.assertEqual((1, 0), ret)


class TestNovaManageMain(test.NoDBTestCase):
    """Tests the nova-manage:main() setup code."""

    def setUp(self):
        super(TestNovaManageMain, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))

    @mock.patch.object(manage.config, 'parse_args')
    @mock.patch.object(manage, 'CONF')
    def test_error_traceback(self, mock_conf, mock_parse_args):
        with mock.patch.object(manage.cmd_common, 'get_action_fn',
                               side_effect=test.TestingException('oops')):
            mock_conf.post_mortem = False
            self.assertEqual(255, manage.main())
            # assert the traceback is dumped to stdout
            output = self.output.getvalue()
            self.assertIn('An error has occurred', output)
            self.assertIn('Traceback', output)
            self.assertIn('oops', output)

    @mock.patch('pdb.post_mortem')
    @mock.patch.object(manage.config, 'parse_args')
    @mock.patch.object(manage, 'CONF')
    def test_error_post_mortem(self, mock_conf, mock_parse_args, mock_pm):
        with mock.patch.object(manage.cmd_common, 'get_action_fn',
                               side_effect=test.TestingException('oops')):
            mock_conf.post_mortem = True
            self.assertEqual(255, manage.main())
            self.assertTrue(mock_pm.called)

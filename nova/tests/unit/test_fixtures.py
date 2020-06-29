# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
import datetime
import io

import fixtures as fx
import futurist
import mock
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_utils import uuidutils
from oslotest import output
import sqlalchemy
import testtools

from nova.compute import rpcapi as compute_rpcapi
from nova import conductor
from nova import context
from nova.db.sqlalchemy import api as session
from nova import exception
from nova.network import neutron as neutron_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import service as service_obj
from nova import test
from nova.tests import fixtures
from nova.tests.unit import conf_fixture
from nova.tests.unit import fake_instance
from nova import utils

CONF = cfg.CONF


class TestLogging(testtools.TestCase):
    def test_default_logging(self):
        stdlog = self.useFixture(fixtures.StandardLogging())
        root = logging.getLogger()
        # there should be a null handler as well at DEBUG
        self.assertEqual(2, len(root.handlers), root.handlers)
        log = logging.getLogger(__name__)
        log.info("at info")
        log.debug("at debug")
        self.assertIn("at info", stdlog.logger.output)
        self.assertNotIn("at debug", stdlog.logger.output)

        # broken debug messages should still explode, even though we
        # aren't logging them in the regular handler
        self.assertRaises(TypeError, log.debug, "this is broken %s %s", "foo")

        # and, ensure that one of the terrible log messages isn't
        # output at info
        warn_log = logging.getLogger('migrate.versioning.api')
        warn_log.info("warn_log at info, should be skipped")
        warn_log.error("warn_log at error")
        self.assertIn("warn_log at error", stdlog.logger.output)
        self.assertNotIn("warn_log at info", stdlog.logger.output)

    def test_debug_logging(self):
        self.useFixture(fx.EnvironmentVariable('OS_DEBUG', '1'))

        stdlog = self.useFixture(fixtures.StandardLogging())
        root = logging.getLogger()
        # there should no longer be a null handler
        self.assertEqual(1, len(root.handlers), root.handlers)
        log = logging.getLogger(__name__)
        log.info("at info")
        log.debug("at debug")
        self.assertIn("at info", stdlog.logger.output)
        self.assertIn("at debug", stdlog.logger.output)


class TestOSAPIFixture(testtools.TestCase):
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.objects.Service.create')
    @mock.patch('nova.utils.raise_if_old_compute', new=mock.Mock())
    def test_responds_to_version(self, mock_service_create, mock_get):
        """Ensure the OSAPI server responds to calls sensibly."""
        self.useFixture(output.CaptureOutput())
        self.useFixture(fixtures.StandardLogging())
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.RPCFixture('nova.test'))
        api = self.useFixture(fixtures.OSAPIFixture()).api

        # request the API root, which provides us the versions of the API
        resp = api.api_request('/', strip_version=True)
        self.assertEqual(200, resp.status_code, resp.content)

        # request a bad root url, should be a 404
        #
        # NOTE(sdague): this currently fails, as it falls into the 300
        # dispatcher instead. This is a bug. The test case is left in
        # here, commented out until we can address it.
        #
        # resp = api.api_request('/foo', strip_version=True)
        # self.assertEqual(resp.status_code, 400, resp.content)

        # request a known bad url, and we should get a 404
        resp = api.api_request('/foo')
        self.assertEqual(404, resp.status_code, resp.content)


class TestDatabaseFixture(testtools.TestCase):
    def test_fixture_reset(self):
        # because this sets up reasonable db connection strings
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database())
        engine = session.get_engine()
        conn = engine.connect()
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(0, len(rows), "Rows %s" % rows)

        # insert a 6th instance type, column 5 below is an int id
        # which has a constraint on it, so if new standard instance
        # types are added you have to bump it.
        conn.execute("insert into instance_types VALUES "
                     "(NULL, NULL, NULL, 't1.test', 6, 4096, 2, 0, NULL, '87'"
                     ", 1.0, 40, 0, 0, 1, 0)")
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(1, len(rows), "Rows %s" % rows)

        # reset by invoking the fixture again
        #
        # NOTE(sdague): it's important to reestablish the db
        # connection because otherwise we have a reference to the old
        # in mem db.
        self.useFixture(fixtures.Database())
        conn = engine.connect()
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(0, len(rows), "Rows %s" % rows)

    def test_api_fixture_reset(self):
        # This sets up reasonable db connection strings
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database(database='api'))
        engine = session.get_api_engine()
        conn = engine.connect()
        result = conn.execute("select * from cell_mappings")
        rows = result.fetchall()
        self.assertEqual(0, len(rows), "Rows %s" % rows)

        uuid = uuidutils.generate_uuid()
        conn.execute("insert into cell_mappings (uuid, name) VALUES "
                     "('%s', 'fake-cell')" % (uuid,))
        result = conn.execute("select * from cell_mappings")
        rows = result.fetchall()
        self.assertEqual(1, len(rows), "Rows %s" % rows)

        # reset by invoking the fixture again
        #
        # NOTE(sdague): it's important to reestablish the db
        # connection because otherwise we have a reference to the old
        # in mem db.
        self.useFixture(fixtures.Database(database='api'))
        conn = engine.connect()
        result = conn.execute("select * from cell_mappings")
        rows = result.fetchall()
        self.assertEqual(0, len(rows), "Rows %s" % rows)

    def test_fixture_cleanup(self):
        # because this sets up reasonable db connection strings
        self.useFixture(conf_fixture.ConfFixture())
        fix = fixtures.Database()
        self.useFixture(fix)

        # manually do the cleanup that addCleanup will do
        fix.cleanup()

        # ensure the db contains nothing
        engine = session.get_engine()
        conn = engine.connect()
        schema = "".join(line for line in conn.connection.iterdump())
        self.assertEqual(schema, "BEGIN TRANSACTION;COMMIT;")

    def test_api_fixture_cleanup(self):
        # This sets up reasonable db connection strings
        self.useFixture(conf_fixture.ConfFixture())
        fix = fixtures.Database(database='api')
        self.useFixture(fix)

        # No data inserted by migrations so we need to add a row
        engine = session.get_api_engine()
        conn = engine.connect()
        uuid = uuidutils.generate_uuid()
        conn.execute("insert into cell_mappings (uuid, name) VALUES "
                     "('%s', 'fake-cell')" % (uuid,))
        result = conn.execute("select * from cell_mappings")
        rows = result.fetchall()
        self.assertEqual(1, len(rows), "Rows %s" % rows)

        # Manually do the cleanup that addCleanup will do
        fix.cleanup()

        # Ensure the db contains nothing
        engine = session.get_api_engine()
        conn = engine.connect()
        schema = "".join(line for line in conn.connection.iterdump())
        self.assertEqual("BEGIN TRANSACTION;COMMIT;", schema)

    def test_fixture_schema_version(self):
        self.useFixture(conf_fixture.ConfFixture())

        # In/after 317 aggregates did have uuid
        self.useFixture(fixtures.Database(version=318))
        engine = session.get_engine()
        engine.connect()
        meta = sqlalchemy.MetaData(engine)
        aggregate = sqlalchemy.Table('aggregates', meta, autoload=True)
        self.assertTrue(hasattr(aggregate.c, 'uuid'))

        # Before 317, aggregates had no uuid
        self.useFixture(fixtures.Database(version=316))
        engine = session.get_engine()
        engine.connect()
        meta = sqlalchemy.MetaData(engine)
        aggregate = sqlalchemy.Table('aggregates', meta, autoload=True)
        self.assertFalse(hasattr(aggregate.c, 'uuid'))
        engine.dispose()

    def test_fixture_after_database_fixture(self):
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(version=318))


class TestDefaultFlavorsFixture(testtools.TestCase):
    @mock.patch("nova.objects.flavor.Flavor._send_notification")
    def test_flavors(self, mock_send_notification):
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))

        engine = session.get_api_engine()
        conn = engine.connect()
        result = conn.execute("select * from flavors")
        rows = result.fetchall()
        self.assertEqual(0, len(rows), "Rows %s" % rows)

        self.useFixture(fixtures.DefaultFlavorsFixture())

        result = conn.execute("select * from flavors")
        rows = result.fetchall()
        self.assertEqual(6, len(rows), "Rows %s" % rows)


class TestIndirectionAPIFixture(testtools.TestCase):
    def test_indirection_api(self):
        # Should initially be None
        self.assertIsNone(obj_base.NovaObject.indirection_api)

        # make sure the fixture correctly sets the value
        fix = fixtures.IndirectionAPIFixture('foo')
        self.useFixture(fix)
        self.assertEqual('foo', obj_base.NovaObject.indirection_api)

        # manually do the cleanup that addCleanup will do
        fix.cleanup()

        # ensure the initial value is restored
        self.assertIsNone(obj_base.NovaObject.indirection_api)


class TestSpawnIsSynchronousFixture(testtools.TestCase):
    def test_spawn_patch(self):
        orig_spawn = utils.spawn_n

        fix = fixtures.SpawnIsSynchronousFixture()
        self.useFixture(fix)
        self.assertNotEqual(orig_spawn, utils.spawn_n)

    def test_spawn_passes_through(self):
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        tester = mock.MagicMock()
        utils.spawn_n(tester.function, 'foo', bar='bar')
        tester.function.assert_called_once_with('foo', bar='bar')

    def test_spawn_return_has_wait(self):
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        gt = utils.spawn(lambda x: '%s' % x, 'foo')
        foo = gt.wait()
        self.assertEqual('foo', foo)

    def test_spawn_n_return_has_wait(self):
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        gt = utils.spawn_n(lambda x: '%s' % x, 'foo')
        foo = gt.wait()
        self.assertEqual('foo', foo)

    def test_spawn_has_link(self):
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        gt = utils.spawn(mock.MagicMock)
        passed_arg = 'test'
        call_count = []

        def fake(thread, param):
            self.assertEqual(gt, thread)
            self.assertEqual(passed_arg, param)
            call_count.append(1)

        gt.link(fake, passed_arg)
        self.assertEqual(1, len(call_count))

    def test_spawn_n_has_link(self):
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        gt = utils.spawn_n(mock.MagicMock)
        passed_arg = 'test'
        call_count = []

        def fake(thread, param):
            self.assertEqual(gt, thread)
            self.assertEqual(passed_arg, param)
            call_count.append(1)

        gt.link(fake, passed_arg)
        self.assertEqual(1, len(call_count))


class TestSynchronousThreadPoolExecutorFixture(testtools.TestCase):
    def test_submit_passes_through(self):
        self.useFixture(fixtures.SynchronousThreadPoolExecutorFixture())
        tester = mock.MagicMock()
        executor = futurist.GreenThreadPoolExecutor()
        future = executor.submit(tester.function, 'foo', bar='bar')
        tester.function.assert_called_once_with('foo', bar='bar')
        result = future.result()
        self.assertEqual(tester.function.return_value, result)


class TestBannedDBSchemaOperations(testtools.TestCase):
    def test_column(self):
        column = sqlalchemy.Column()
        with fixtures.BannedDBSchemaOperations(['Column']):
            self.assertRaises(exception.DBNotAllowed,
                              column.drop)
            self.assertRaises(exception.DBNotAllowed,
                              column.alter)

    def test_table(self):
        table = sqlalchemy.Table()
        with fixtures.BannedDBSchemaOperations(['Table']):
            self.assertRaises(exception.DBNotAllowed,
                              table.drop)
            self.assertRaises(exception.DBNotAllowed,
                              table.alter)


class TestAllServicesCurrentFixture(testtools.TestCase):
    @mock.patch('nova.objects.Service._db_service_get_minimum_version')
    def test_services_current(self, mock_db):
        mock_db.return_value = {'nova-compute': 123}
        self.assertEqual(123, service_obj.Service.get_minimum_version(
            None, 'nova-compute'))
        mock_db.assert_called_once_with(None, ['nova-compute'],
                                        use_slave=False)
        mock_db.reset_mock()
        compute_rpcapi.LAST_VERSION = 123
        self.useFixture(fixtures.AllServicesCurrent())
        self.assertIsNone(compute_rpcapi.LAST_VERSION)
        self.assertEqual(service_obj.SERVICE_VERSION,
                         service_obj.Service.get_minimum_version(
                             None, 'nova-compute'))
        self.assertFalse(mock_db.called)


class TestNoopConductorFixture(testtools.TestCase):
    @mock.patch('nova.conductor.api.ComputeTaskAPI.resize_instance')
    def test_task_api_not_called(self, mock_resize):
        self.useFixture(fixtures.NoopConductorFixture())
        conductor.ComputeTaskAPI().resize_instance()
        self.assertFalse(mock_resize.called)

    @mock.patch('nova.conductor.api.API.wait_until_ready')
    def test_api_not_called(self, mock_wait):
        self.useFixture(fixtures.NoopConductorFixture())
        conductor.API().wait_until_ready()
        self.assertFalse(mock_wait.called)


class TestSingleCellSimpleFixture(testtools.TestCase):
    def test_single_cell(self):
        self.useFixture(fixtures.SingleCellSimple())
        cml = objects.CellMappingList.get_all(None)
        self.assertEqual(1, len(cml))

    def test_target_cell(self):
        self.useFixture(fixtures.SingleCellSimple())
        with context.target_cell(mock.sentinel.context, None) as c:
            self.assertIs(mock.sentinel.context, c)


class TestWarningsFixture(test.TestCase):
    def test_invalid_uuid_errors(self):
        """Creating an oslo.versionedobject with an invalid UUID value for a
        UUIDField should raise an exception.
        """
        valid_migration_kwargs = {
                "created_at": timeutils.utcnow().replace(microsecond=0),
                "updated_at": None,
                "deleted_at": None,
                "deleted": False,
                "id": 123,
                "uuid": uuids.migration,
                "source_compute": "compute-source",
                "dest_compute": "compute-dest",
                "source_node": "node-source",
                "dest_node": "node-dest",
                "dest_host": "host-dest",
                "old_instance_type_id": 42,
                "new_instance_type_id": 84,
                "instance_uuid": "fake-uuid",
                "status": "migrating",
                "migration_type": "resize",
                "hidden": False,
                "memory_total": 123456,
                "memory_processed": 12345,
                "memory_remaining": 111111,
                "disk_total": 234567,
                "disk_processed": 23456,
                "disk_remaining": 211111,
                }

        # this shall not throw FutureWarning
        objects.migration.Migration(**valid_migration_kwargs)

        invalid_migration_kwargs = copy.deepcopy(valid_migration_kwargs)
        invalid_migration_kwargs["uuid"] = "fake_id"
        self.assertRaises(FutureWarning, objects.migration.Migration,
                          **invalid_migration_kwargs)


class TestDownCellFixture(test.TestCase):

    def test_fixture(self):
        # The test setup creates two cell mappings (cell0 and cell1) by
        # default. Let's first list servers across all cells while they are
        # "up" to make sure that works as expected. We'll create a single
        # instance in cell1.
        ctxt = context.get_admin_context()
        cell1 = self.cell_mappings[test.CELL1_NAME]
        with context.target_cell(ctxt, cell1) as cctxt:
            inst = fake_instance.fake_instance_obj(cctxt)
            if 'id' in inst:
                delattr(inst, 'id')
            inst.create()

        # Now list all instances from all cells (should get one back).
        results = context.scatter_gather_all_cells(
            ctxt, objects.InstanceList.get_all)
        self.assertEqual(2, len(results))
        self.assertEqual(0, len(results[objects.CellMapping.CELL0_UUID]))
        self.assertEqual(1, len(results[cell1.uuid]))

        # Now do the same but with the DownCellFixture which should result
        # in exception results from both cells.
        with fixtures.DownCellFixture():
            results = context.scatter_gather_all_cells(
                ctxt, objects.InstanceList.get_all)
            self.assertEqual(2, len(results))
            for result in results.values():
                self.assertIsInstance(result, db_exc.DBError)

    def test_fixture_when_explicitly_passing_down_cell_mappings(self):
        # The test setup creates two cell mappings (cell0 and cell1) by
        # default. We'll create one instance per cell and pass cell0 as
        # the down cell. We should thus get db_exc.DBError for cell0 and
        # correct InstanceList object from cell1.
        ctxt = context.get_admin_context()
        cell0 = self.cell_mappings['cell0']
        cell1 = self.cell_mappings['cell1']
        with context.target_cell(ctxt, cell0) as cctxt:
            inst1 = fake_instance.fake_instance_obj(cctxt)
            if 'id' in inst1:
                delattr(inst1, 'id')
            inst1.create()
        with context.target_cell(ctxt, cell1) as cctxt:
            inst2 = fake_instance.fake_instance_obj(cctxt)
            if 'id' in inst2:
                delattr(inst2, 'id')
            inst2.create()
        with fixtures.DownCellFixture([cell0]):
            results = context.scatter_gather_all_cells(
                ctxt, objects.InstanceList.get_all)
            self.assertEqual(2, len(results))
            for cell_uuid, result in results.items():
                if cell_uuid == cell0.uuid:
                    self.assertIsInstance(result, db_exc.DBError)
                else:
                    self.assertIsInstance(result, objects.InstanceList)
                    self.assertEqual(1, len(result))
                    self.assertEqual(inst2.uuid, result[0].uuid)

    def test_fixture_for_an_individual_down_cell_targeted_call(self):
        # We have cell0 and cell1 by default in the setup. We try targeting
        # both the cells. We should get a db error for the down cell and
        # the correct result for the up cell.
        ctxt = context.get_admin_context()
        cell0 = self.cell_mappings['cell0']
        cell1 = self.cell_mappings['cell1']
        with context.target_cell(ctxt, cell0) as cctxt:
            inst1 = fake_instance.fake_instance_obj(cctxt)
            if 'id' in inst1:
                delattr(inst1, 'id')
            inst1.create()
        with context.target_cell(ctxt, cell1) as cctxt:
            inst2 = fake_instance.fake_instance_obj(cctxt)
            if 'id' in inst2:
                delattr(inst2, 'id')
            inst2.create()

        def dummy_tester(ctxt, cell_mapping, uuid):
            with context.target_cell(ctxt, cell_mapping) as cctxt:
                return objects.Instance.get_by_uuid(cctxt, uuid)

        # Scenario A: We do not pass any down cells, fixture automatically
        # assumes the targeted cell is down whether its cell0 or cell1.
        with fixtures.DownCellFixture():
            self.assertRaises(
                db_exc.DBError, dummy_tester, ctxt, cell1, inst2.uuid)
        # Scenario B: We pass cell0 as the down cell.
        with fixtures.DownCellFixture([cell0]):
            self.assertRaises(
                db_exc.DBError, dummy_tester, ctxt, cell0, inst1.uuid)
            # Scenario C: We get the correct result from the up cell
            # when targeted.
            result = dummy_tester(ctxt, cell1, inst2.uuid)
            self.assertEqual(inst2.uuid, result.uuid)


class TestNeutronFixture(test.NoDBTestCase):

    def setUp(self):
        super(TestNeutronFixture, self).setUp()
        self.neutron = self.useFixture(fixtures.NeutronFixture(self))

    def test_list_ports_with_resource_request_non_admin_client(self):
        ctxt = context.get_context()
        client = neutron_api.get_client(ctxt)
        ports = client.list_ports(ctxt)['ports']
        port_id = self.neutron.port_with_resource_request['id']
        ports = [port for port in ports if port_id == port['id']]
        self.assertIsNone(ports[0]['resource_request'])

    def test_list_ports_with_resource_request_admin_client(self):
        ctxt = context.get_admin_context()
        client = neutron_api.get_client(ctxt)
        ports = client.list_ports(ctxt)['ports']
        port_id = self.neutron.port_with_resource_request['id']
        ports = [port for port in ports if port_id == port['id']]
        self.assertIsNotNone(ports[0]['resource_request'])


class TestGlanceFixture(test.NoDBTestCase):
    def setUp(self):
        super().setUp()
        self.image_service = self.useFixture(fixtures.GlanceFixture(self))
        self.context = context.get_admin_context()

    def test_detail(self):
        res = self.image_service.detail(self.context)
        for image in res:
            self.assertEqual(
                set(image.keys()),
                {
                    'id', 'name', 'created_at', 'updated_at', 'deleted_at',
                    'deleted', 'status', 'is_public', 'properties',
                    'disk_format', 'container_format', 'size', 'min_disk',
                    'min_ram', 'protected', 'tags', 'visibility',
                },
            )
            self.assertIsInstance(image['created_at'], datetime.datetime)
            self.assertIsInstance(image['updated_at'], datetime.datetime)

            if not (
                isinstance(image['deleted_at'], datetime.datetime) or
                image['deleted_at'] is None
            ):
                self.fail(
                    "image's 'deleted_at' attribute was neither a datetime "
                    "object nor None"
                )

            def check_is_bool(image, key):
                val = image.get('deleted')
                if not isinstance(val, bool):
                    self.fail(
                        "image's '%s' attribute wasn't a bool: %r" % (key, val)
                    )

            check_is_bool(image, 'deleted')
            check_is_bool(image, 'is_public')

    def test_show_raises_imagenotfound_for_invalid_id(self):
        self.assertRaises(
            exception.ImageNotFound,
            self.image_service.show,
            self.context, 'this image does not exist')

    def test_create_adds_id(self):
        index = self.image_service.detail(self.context)
        image_count = len(index)

        self.image_service.create(self.context, {})

        index = self.image_service.detail(self.context)
        self.assertEqual(len(index), image_count + 1)
        self.assertTrue(index[0]['id'])

    def test_create_keeps_id(self):
        self.image_service.create(self.context, {'id': '34'})
        self.image_service.show(self.context, '34')

    def test_create_rejects_duplicate_ids(self):
        self.image_service.create(self.context, {'id': '34'})
        self.assertRaises(
            exception.CouldNotUploadImage,
            self.image_service.create,
            self.context, {'id': '34'})

        # Make sure there's still one left
        self.image_service.show(self.context, '34')

    def test_update(self):
        self.image_service.create(
            self.context, {'id': '34', 'foo': 'bar'})

        self.image_service.update(
            self.context, '34', {'id': '34', 'foo': 'baz'})

        img = self.image_service.show(self.context, '34')
        self.assertEqual(img['foo'], 'baz')

    def test_delete(self):
        self.image_service.create(self.context, {'id': '34', 'foo': 'bar'})
        self.image_service.delete(self.context, '34')
        self.assertRaises(
            exception.NotFound,
            self.image_service.show,
            self.context, '34')

    def test_create_then_get(self):
        blob = 'some data'
        s1 = io.StringIO(blob)
        self.image_service.create(
            self.context, {'id': '32', 'foo': 'bar'}, data=s1)
        s2 = io.StringIO()
        self.image_service.download(self.context, '32', data=s2)
        self.assertEqual(s2.getvalue(), blob, 'Did not get blob back intact')

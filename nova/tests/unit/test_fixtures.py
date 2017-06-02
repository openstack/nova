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

import sys

import fixtures as fx
import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils
import sqlalchemy
import testtools

from nova.compute import rpcapi as compute_rpcapi
from nova import conductor
from nova import context
from nova.db.sqlalchemy import api as session
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import service as service_obj
from nova.tests import fixtures
from nova.tests.unit import conf_fixture
from nova import utils

CONF = cfg.CONF


class TestConfFixture(testtools.TestCase):
    """Test the Conf fixtures in Nova.

    This is a basic test that this fixture works like we expect.

    Expectations:

    1. before using the fixture, a default value (api_paste_config)
       comes through untouched.

    2. before using the fixture, a known default value that we
       override is correct.

    3. after using the fixture a known value that we override is the
       new value.

    4. after using the fixture we can set a default value to something
       random, and it will be reset once we are done.

    There are 2 copies of this test so that you can verify they do the
    right thing with:

       tox -e py27 test_fixtures -- --concurrency=1

    As regardless of run order, their initial asserts would be
    impacted if the reset behavior isn't working correctly.

    """
    def _test_override(self):
        self.assertEqual('api-paste.ini', CONF.wsgi.api_paste_config)
        self.assertFalse(CONF.fake_network)
        self.useFixture(conf_fixture.ConfFixture())
        CONF.set_default('api_paste_config', 'foo', group='wsgi')
        self.assertTrue(CONF.fake_network)

    def test_override1(self):
        self._test_override()

    def test_override2(self):
        self._test_override()


class TestOutputStream(testtools.TestCase):
    """Ensure Output Stream capture works as expected.

    This has the added benefit of providing a code example of how you
    can manipulate the output stream in your own tests.
    """
    def test_output(self):
        self.useFixture(fx.EnvironmentVariable('OS_STDOUT_CAPTURE', '1'))
        self.useFixture(fx.EnvironmentVariable('OS_STDERR_CAPTURE', '1'))

        out = self.useFixture(fixtures.OutputStreamCapture())
        sys.stdout.write("foo")
        sys.stderr.write("bar")
        self.assertEqual("foo", out.stdout)
        self.assertEqual("bar", out.stderr)
        # TODO(sdague): nuke the out and err buffers so it doesn't
        # make it to testr


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


class TestTimeout(testtools.TestCase):
    """Tests for our timeout fixture.

    Testing the actual timeout mechanism is beyond the scope of this
    test, because it's a pretty clear pass through to fixtures'
    timeout fixture, which tested in their tree.

    """
    def test_scaling(self):
        # a bad scaling factor
        self.assertRaises(ValueError, fixtures.Timeout, 1, 0.5)

        # various things that should work.
        timeout = fixtures.Timeout(10)
        self.assertEqual(10, timeout.test_timeout)
        timeout = fixtures.Timeout("10")
        self.assertEqual(10, timeout.test_timeout)
        timeout = fixtures.Timeout("10", 2)
        self.assertEqual(20, timeout.test_timeout)


class TestOSAPIFixture(testtools.TestCase):
    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.objects.Service.create')
    def test_responds_to_version(self, mock_service_create, mock_get):
        """Ensure the OSAPI server responds to calls sensibly."""
        self.useFixture(fixtures.OutputStreamCapture())
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


class TestDatabaseAtVersionFixture(testtools.TestCase):
    def test_fixture_schema_version(self):
        self.useFixture(conf_fixture.ConfFixture())

        # In/after 317 aggregates did have uuid
        self.useFixture(fixtures.DatabaseAtVersion(318))
        engine = session.get_engine()
        engine.connect()
        meta = sqlalchemy.MetaData(engine)
        aggregate = sqlalchemy.Table('aggregates', meta, autoload=True)
        self.assertTrue(hasattr(aggregate.c, 'uuid'))

        # Before 317, aggregates had no uuid
        self.useFixture(fixtures.DatabaseAtVersion(316))
        engine = session.get_engine()
        engine.connect()
        meta = sqlalchemy.MetaData(engine)
        aggregate = sqlalchemy.Table('aggregates', meta, autoload=True)
        self.assertFalse(hasattr(aggregate.c, 'uuid'))
        engine.dispose()

    def test_fixture_after_database_fixture(self):
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.DatabaseAtVersion(318))


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


class TestPlacementFixture(testtools.TestCase):
    def test_responds_to_version(self):
        """Ensure the Placement server responds to calls sensibly."""
        placement_fixture = self.useFixture(fixtures.PlacementFixture())

        # request the API root, which provides us the versions of the API
        resp = placement_fixture._fake_get(None, '/')
        self.assertEqual(200, resp.status_code)

        # request a known bad url, and we should get a 404
        resp = placement_fixture._fake_get(None, '/foo')
        self.assertEqual(404, resp.status_code)

        # unsets the token so we fake missing it
        placement_fixture.token = None
        resp = placement_fixture._fake_get(None, '/foo')
        self.assertEqual(401, resp.status_code)

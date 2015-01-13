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

import logging
import sys

import fixtures as fx
from oslo.config import cfg
import testtools

from nova.db.sqlalchemy import api as session
from nova.tests import fixtures
from nova.tests.unit import conf_fixture

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
        self.assertEqual(CONF.api_paste_config, 'api-paste.ini')
        self.assertEqual(CONF.fake_network, False)
        self.useFixture(conf_fixture.ConfFixture())
        CONF.set_default('api_paste_config', 'foo')
        self.assertEqual(CONF.fake_network, True)

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
        self.assertEqual(out.stdout, "foo")
        self.assertEqual(out.stderr, "bar")
        # TODO(sdague): nuke the out and err buffers so it doesn't
        # make it to testr


class TestLogging(testtools.TestCase):
    def test_default_logging(self):
        stdlog = self.useFixture(fixtures.StandardLogging())
        root = logging.getLogger()
        # there should be a null handler as well at DEBUG
        self.assertEqual(len(root.handlers), 2, root.handlers)
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
        self.assertEqual(len(root.handlers), 1, root.handlers)
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
        self.assertEqual(timeout.test_timeout, 10)
        timeout = fixtures.Timeout("10")
        self.assertEqual(timeout.test_timeout, 10)
        timeout = fixtures.Timeout("10", 2)
        self.assertEqual(timeout.test_timeout, 20)


class TestDatabaseFixture(testtools.TestCase):
    def test_fixture_reset(self):
        # because this sets up reasonable db connection strings
        self.useFixture(conf_fixture.ConfFixture())
        self.useFixture(fixtures.Database())
        engine = session.get_engine()
        conn = engine.connect()
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(len(rows), 5, "Rows %s" % rows)

        # insert a 6th instance type, column 5 below is an int id
        # which has a constraint on it, so if new standard instance
        # types are added you have to bump it.
        conn.execute("insert into instance_types VALUES "
                     "(NULL, NULL, NULL, 't1.test', 6, 4096, 2, 0, NULL, '87'"
                     ", 1.0, 40, 0, 0, 1, 0)")
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(len(rows), 6, "Rows %s" % rows)

        # reset by invoking the fixture again
        #
        # NOTE(sdague): it's important to reestablish the db
        # connection because otherwise we have a reference to the old
        # in mem db.
        self.useFixture(fixtures.Database())
        conn = engine.connect()
        result = conn.execute("select * from instance_types")
        rows = result.fetchall()
        self.assertEqual(len(rows), 5, "Rows %s" % rows)

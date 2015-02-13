# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""Fixtures for Nova tests."""
from __future__ import absolute_import

import gettext
import logging
import os
import uuid
import warnings

import fixtures
from oslo_config import cfg
from oslo_messaging import conffixture as messaging_conffixture

from nova.db import migration
from nova.db.sqlalchemy import api as session
from nova import rpc
from nova import service

_TRUE_VALUES = ('True', 'true', '1', 'yes')

CONF = cfg.CONF
DB_SCHEMA = ""


class ServiceFixture(fixtures.Fixture):
    """Run a service as a test fixture."""

    def __init__(self, name, host=None, **kwargs):
        name = name
        host = host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        self.kwargs = kwargs

    def setUp(self):
        super(ServiceFixture, self).setUp()
        self.service = service.Service.create(**self.kwargs)
        self.service.start()
        self.addCleanup(self.service.kill)


class TranslationFixture(fixtures.Fixture):
    """Use gettext NullTranslation objects in tests."""

    def setUp(self):
        super(TranslationFixture, self).setUp()
        nulltrans = gettext.NullTranslations()
        gettext_fixture = fixtures.MonkeyPatch('gettext.translation',
                                               lambda *x, **y: nulltrans)
        self.gettext_patcher = self.useFixture(gettext_fixture)


class NullHandler(logging.Handler):
    """custom default NullHandler to attempt to format the record.

    Used in conjunction with
    log_fixture.get_logging_handle_error_fixture to detect formatting errors in
    debug level logs without saving the logs.
    """
    def handle(self, record):
        self.format(record)

    def emit(self, record):
        pass

    def createLock(self):
        self.lock = None


class StandardLogging(fixtures.Fixture):
    """Setup Logging redirection for tests.

    There are a number of things we want to handle with logging in tests:

    * Redirect the logging to somewhere that we can test or dump it later.

    * Ensure that as many DEBUG messages as possible are actually
       executed, to ensure they are actually syntactically valid (they
       often have not been).

    * Ensure that we create useful output for tests that doesn't
      overwhelm the testing system (which means we can't capture the
      100 MB of debug logging on every run).

    To do this we create a logger fixture at the root level, which
    defaults to INFO and create a Null Logger at DEBUG which lets
    us execute log messages at DEBUG but not keep the output.

    To support local debugging OS_DEBUG=True can be set in the
    environment, which will print out the full debug logging.

    There are also a set of overrides for particularly verbose
    modules to be even less than INFO.

    """

    def setUp(self):
        super(StandardLogging, self).setUp()

        # set root logger to debug
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        # supports collecting debug level for local runs
        if os.environ.get('OS_DEBUG') in _TRUE_VALUES:
            level = logging.DEBUG
        else:
            level = logging.INFO

        # Collect logs
        fs = '%(asctime)s %(levelname)s [%(name)s] %(message)s'
        self.logger = self.useFixture(
            fixtures.FakeLogger(format=fs, level=None))
        # TODO(sdague): why can't we send level through the fake
        # logger? Tests prove that it breaks, but it's worth getting
        # to the bottom of.
        root.handlers[0].setLevel(level)

        if level > logging.DEBUG:
            # Just attempt to format debug level logs, but don't save them
            handler = NullHandler()
            self.useFixture(fixtures.LogHandler(handler, nuke_handlers=False))
            handler.setLevel(logging.DEBUG)

            # Don't log every single DB migration step
            logging.getLogger(
                'migrate.versioning.api').setLevel(logging.WARNING)


class OutputStreamCapture(fixtures.Fixture):
    """Capture output streams during tests.

    This fixture captures errant printing to stderr / stdout during
    the tests and lets us see those streams at the end of the test
    runs instead. Useful to see what was happening during failed
    tests.
    """
    def setUp(self):
        super(OutputStreamCapture, self).setUp()
        if os.environ.get('OS_STDOUT_CAPTURE') in _TRUE_VALUES:
            self.out = self.useFixture(fixtures.StringStream('stdout'))
            self.useFixture(
                fixtures.MonkeyPatch('sys.stdout', self.out.stream))
        if os.environ.get('OS_STDERR_CAPTURE') in _TRUE_VALUES:
            self.err = self.useFixture(fixtures.StringStream('stderr'))
            self.useFixture(
                fixtures.MonkeyPatch('sys.stderr', self.err.stream))

    @property
    def stderr(self):
        return self.err._details["stderr"].as_text()

    @property
    def stdout(self):
        return self.out._details["stdout"].as_text()


class Timeout(fixtures.Fixture):
    """Setup per test timeouts.

    In order to avoid test deadlocks we support setting up a test
    timeout parameter read from the environment. In almost all
    cases where the timeout is reached this means a deadlock.

    A class level TIMEOUT_SCALING_FACTOR also exists, which allows
    extremely long tests to specify they need more time.
    """

    def __init__(self, timeout, scaling=1):
        super(Timeout, self).__init__()
        try:
            self.test_timeout = int(timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            self.test_timeout = 0
        if scaling >= 1:
            self.test_timeout *= scaling
        else:
            raise ValueError('scaling value must be >= 1')

    def setUp(self):
        super(Timeout, self).setUp()
        if self.test_timeout > 0:
            self.useFixture(fixtures.Timeout(self.test_timeout, gentle=True))


class Database(fixtures.Fixture):
    def _cache_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA:
            engine = session.get_engine()
            conn = engine.connect()
            migration.db_sync()
            DB_SCHEMA = "".join(line for line in conn.connection.iterdump())
            engine.dispose()

    def reset(self):
        self._cache_schema()
        engine = session.get_engine()
        engine.dispose()
        conn = engine.connect()
        conn.connection.executescript(DB_SCHEMA)

    def setUp(self):
        super(Database, self).setUp()
        self.reset()


class RPCFixture(fixtures.Fixture):
    def __init__(self, *exmods):
        super(RPCFixture, self).__init__()
        self.exmods = []
        self.exmods.extend(exmods)

    def setUp(self):
        super(RPCFixture, self).setUp()
        self.addCleanup(rpc.cleanup)
        rpc.add_extra_exmods(*self.exmods)
        self.addCleanup(rpc.clear_extra_exmods)
        self.messaging_conf = messaging_conffixture.ConfFixture(CONF)
        self.messaging_conf.transport_driver = 'fake'
        self.useFixture(self.messaging_conf)
        rpc.init(CONF)


class WarningsFixture(fixtures.Fixture):
    """Filters out warnings during test runs."""

    def setUp(self):
        super(WarningsFixture, self).setUp()
        # NOTE(sdague): Make deprecation warnings only happen once. Otherwise
        # this gets kind of crazy given the way that upstream python libs use
        # this.
        warnings.simplefilter("once", DeprecationWarning)
        warnings.filterwarnings('ignore',
                                message='With-statements now directly support'
                                        ' multiple context managers')

        self.addCleanup(warnings.resetwarnings)


class PoisonFunctions(fixtures.Fixture):
    """Poison functions so they explode if we touch them.

    When running under a non full stack test harness there are parts
    of the code that you don't want to go anywhere near. These include
    things like code that spins up extra threads, which just
    introduces races.

    """

    def setUp(self):
        super(PoisonFunctions, self).setUp()

        # The nova libvirt driver starts an event thread which only
        # causes trouble in tests. Make sure that if tests don't
        # properly patch it the test explodes.

        # explicit import because MonkeyPatch doesn't magic import
        # correctly if we are patching a method on a class in a
        # module.
        import nova.virt.libvirt.host  # noqa

        def evloop(*args, **kwargs):
            import sys
            warnings.warn("Forgot to disable libvirt event thread")
            sys.exit(1)

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.host.Host._init_events',
            evloop))

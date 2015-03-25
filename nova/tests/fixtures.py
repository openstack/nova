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

import logging as std_logging
import os
import uuid
import warnings

import fixtures
from oslo_config import cfg
from oslo_messaging import conffixture as messaging_conffixture

from nova.db import migration
from nova.db.sqlalchemy import api as session
from nova.objects import base as obj_base
from nova import rpc
from nova import service
from nova.tests.functional.api import client

_TRUE_VALUES = ('True', 'true', '1', 'yes')

CONF = cfg.CONF
DB_SCHEMA = {'main': "", 'api': ""}


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


class NullHandler(std_logging.Handler):
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
        root = std_logging.getLogger()
        root.setLevel(std_logging.DEBUG)

        # supports collecting debug level for local runs
        if os.environ.get('OS_DEBUG') in _TRUE_VALUES:
            level = std_logging.DEBUG
        else:
            level = std_logging.INFO

        # Collect logs
        fs = '%(asctime)s %(levelname)s [%(name)s] %(message)s'
        self.logger = self.useFixture(
            fixtures.FakeLogger(format=fs, level=None))
        # TODO(sdague): why can't we send level through the fake
        # logger? Tests prove that it breaks, but it's worth getting
        # to the bottom of.
        root.handlers[0].setLevel(level)

        if level > std_logging.DEBUG:
            # Just attempt to format debug level logs, but don't save them
            handler = NullHandler()
            self.useFixture(fixtures.LogHandler(handler, nuke_handlers=False))
            handler.setLevel(std_logging.DEBUG)

            # Don't log every single DB migration step
            std_logging.getLogger(
                'migrate.versioning.api').setLevel(std_logging.WARNING)


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
    def __init__(self, database='main'):
        super(Database, self).__init__()
        self.database = database
        if database == 'main':
            self.get_engine = session.get_engine
        elif database == 'api':
            self.get_engine = session.get_api_engine

    def _cache_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA[self.database]:
            engine = self.get_engine()
            conn = engine.connect()
            migration.db_sync(database=self.database)
            DB_SCHEMA[self.database] = "".join(line for line
                                               in conn.connection.iterdump())
            engine.dispose()

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()

    def reset(self):
        self._cache_schema()
        engine = self.get_engine()
        engine.dispose()
        conn = engine.connect()
        conn.connection.executescript(DB_SCHEMA[self.database])

    def setUp(self):
        super(Database, self).setUp()
        self.reset()
        self.addCleanup(self.cleanup)


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


class ConfPatcher(fixtures.Fixture):
    """Fixture to patch and restore global CONF.

    This also resets overrides for everything that is patched during
    it's teardown.

    """

    def __init__(self, **kwargs):
        """Constructor

        :params group: if specified all config options apply to that group.

        :params **kwargs: the rest of the kwargs are processed as a
        set of key/value pairs to be set as configuration override.

        """
        super(ConfPatcher, self).__init__()
        self.group = kwargs.pop('group', None)
        self.args = kwargs

    def setUp(self):
        super(ConfPatcher, self).setUp()
        for k, v in self.args.iteritems():
            self.addCleanup(CONF.clear_override, k, self.group)
            CONF.set_override(k, v, self.group)


class OSAPIFixture(fixtures.Fixture):
    """Create an OS API server as a fixture.

    This spawns an OS API server as a fixture in a new greenthread in
    the current test. The fixture has a .api paramenter with is a
    simple rest client that can communicate with it.

    This fixture is extremely useful for testing REST responses
    through the WSGI stack easily in functional tests.

    Usage:

        api = self.useFixture(fixtures.OSAPIFixture()).api
        resp = api.api_request('/someurl')
        self.assertEqual(200, resp.status_code)
        resp = api.api_request('/otherurl', method='POST', body='{foo}')

    The resp is a requests library response. Common attributes that
    you'll want to use are:

    - resp.status_code - integer HTTP status code returned by the request
    - resp.content - the body of the response
    - resp.headers - dictionary of HTTP headers returned

    """

    def __init__(self, api_version='v2'):
        """Constructor

        :param api_version: the API version that we're interested in
        using. Currently this expects 'v2' or 'v2.1' as possible
        options.

        """
        super(OSAPIFixture, self).__init__()
        self.api_version = api_version

    def setUp(self):
        super(OSAPIFixture, self).setUp()
        # in order to run these in tests we need to bind only to local
        # host, and dynamically allocate ports
        conf_overrides = {
            'ec2_listen': '127.0.0.1',
            'osapi_compute_listen': '127.0.0.1',
            'metadata_listen': '127.0.0.1',
            'ec2_listen_port': 0,
            'osapi_compute_listen_port': 0,
            'metadata_listen_port': 0,
            'verbose': True,
            'debug': True
        }
        self.useFixture(ConfPatcher(**conf_overrides))
        osapi = service.WSGIService("osapi_compute")
        osapi.start()
        self.addCleanup(osapi.stop)
        self.auth_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': osapi.host, 'port': osapi.port,
            'api_version': self.api_version})
        self.api = client.TestOpenStackClient('fake', 'fake', self.auth_url)
        self.admin_api = client.TestOpenStackClient(
            'admin', 'admin', self.auth_url)


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


class IndirectionAPIFixture(fixtures.Fixture):
    """Patch and restore the global NovaObject indirection api."""

    def __init__(self, indirection_api):
        """Constructor

        :param indirection_api: the indirection API to be used for tests.

        """
        super(IndirectionAPIFixture, self).__init__()
        self.indirection_api = indirection_api

    def cleanup(self):
        obj_base.NovaObject.indirection_api = self.orig_indirection_api

    def setUp(self):
        super(IndirectionAPIFixture, self).setUp()
        self.orig_indirection_api = obj_base.NovaObject.indirection_api
        obj_base.NovaObject.indirection_api = self.indirection_api
        self.addCleanup(self.cleanup)

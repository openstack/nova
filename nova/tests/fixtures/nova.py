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

import collections
import contextlib
from contextlib import contextmanager
import functools
from importlib.abc import MetaPathFinder
import logging as std_logging
import os
import sys
import time
from unittest import mock
import warnings

import eventlet
import fixtures
import futurist
from openstack import service_description
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures as db_fixtures
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_messaging import conffixture as messaging_conffixture
from oslo_privsep import daemon as privsep_daemon
from oslo_utils.fixture import uuidsentinel
from oslo_utils import strutils
from requests import adapters
from sqlalchemy import exc as sqla_exc
from wsgi_intercept import interceptor

from nova.api.openstack import wsgi_app
from nova.api import wsgi
from nova.compute import multi_cell_list
from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova.db import migration
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import service as service_obj
import nova.privsep
from nova import quota as nova_quota
from nova import rpc
from nova.scheduler import weights
from nova import service
from nova.tests.functional.api import client
from nova import utils
from nova.virt import node

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

DB_SCHEMA = collections.defaultdict(str)
PROJECT_ID = '6f70656e737461636b20342065766572'


class ServiceFixture(fixtures.Fixture):
    """Run a service as a test fixture."""

    def __init__(self, name, host=None, cell=None, **kwargs):
        name = name
        # If not otherwise specified, the host will default to the
        # name of the service. Some things like aggregates care that
        # this is stable.
        host = host or name
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        self.cell = cell
        self.kwargs = kwargs

    def setUp(self):
        super(ServiceFixture, self).setUp()
        self.ctxt = context.get_admin_context()
        if self.cell:
            context.set_target_cell(self.ctxt, self.cell)

        with mock.patch('nova.context.get_admin_context',
                        return_value=self.ctxt):
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
        if os.environ.get('OS_DEBUG') in ('True', 'true', '1', 'yes'):
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
            # Or alembic for model comparisons.
            std_logging.getLogger('alembic').setLevel(std_logging.WARNING)
            # Or oslo_db provisioning steps
            std_logging.getLogger('oslo_db.sqlalchemy').setLevel(
                std_logging.WARNING)

        # At times we end up calling back into main() functions in
        # testing. This has the possibility of calling logging.setup
        # again, which completely unwinds the logging capture we've
        # created here. Once we've setup the logging the way we want,
        # disable the ability for the test to change this.
        def fake_logging_setup(*args):
            pass

        self.useFixture(
            fixtures.MonkeyPatch('oslo_log.log.setup', fake_logging_setup))

    def delete_stored_logs(self):
        # NOTE(gibi): this depends on the internals of the fixtures.FakeLogger.
        # This could be enhanced once the PR
        # https://github.com/testing-cabal/fixtures/pull/42 merges
        self.logger._output.truncate(0)


class DatabasePoisonFixture(fixtures.Fixture):
    def setUp(self):
        super(DatabasePoisonFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'oslo_db.sqlalchemy.enginefacade._TransactionFactory.'
            '_create_session',
            self._poison_configure))

        # NOTE(gibi): not just _create_session indicates a manipulation on the
        # DB but actually any operation that actually initializes (starts) a
        # transaction factory. If a test does this without using the Database
        # fixture then that test i) actually a database test and should declare
        # it so ii) actually manipulates a global state without proper cleanup
        # and test isolation. This could lead that later tests are failing with
        # the error: oslo_db.sqlalchemy.enginefacade.AlreadyStartedError: this
        # TransactionFactory is already started
        self.useFixture(fixtures.MonkeyPatch(
           'oslo_db.sqlalchemy.enginefacade._TransactionFactory._start',
           self._poison_configure))

    def _poison_configure(self, *a, **k):
        # If you encounter this error, you might be tempted to just not
        # inherit from NoDBTestCase. Bug #1568414 fixed a few hundred of these
        # errors, and not once was that the correct solution. Instead,
        # consider some of the following tips (when applicable):
        #
        # - mock at the object layer rather than the db layer, for example:
        #       nova.objects.instance.Instance.get
        #            vs.
        #       nova.db.instance_get
        #
        # - mock at the api layer rather than the object layer, for example:
        #       nova.api.openstack.common.get_instance
        #           vs.
        #       nova.objects.instance.Instance.get
        #
        # - mock code that requires the database but is otherwise tangential
        #   to the code you're testing (for example: EventReporterStub)
        #
        # - peruse some of the other database poison warning fixes here:
        #   https://review.opendev.org/#/q/topic:bug/1568414
        raise Exception('This test uses methods that set internal oslo_db '
                        'state, but it does not claim to use the database. '
                        'This will conflict with the setup of tests that '
                        'do use the database and cause failures later.')


class SingleCellSimple(fixtures.Fixture):
    """Setup the simplest cells environment possible

    This should be used when you do not care about multiple cells,
    or having a "real" environment for tests that should not care.
    This will give you a single cell, and map any and all accesses
    to that cell (even things that would go to cell0).

    If you need to distinguish between cell0 and cellN, then you
    should use the CellDatabases fixture.

    If instances should appear to still be in scheduling state, pass
    instances_created=False to init.
    """

    def __init__(
        self, instances_created=True, project_id=PROJECT_ID,
    ):
        self.instances_created = instances_created
        self.project_id = project_id

    def setUp(self):
        super(SingleCellSimple, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMappingList._get_all_from_db',
            self._fake_cell_list))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMappingList._get_by_project_id_from_db',
            self._fake_cell_list))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMapping._get_by_uuid_from_db',
            self._fake_cell_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.HostMapping._get_by_host_from_db',
            self._fake_hostmapping_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMapping._get_by_instance_uuid_from_db',
            self._fake_instancemapping_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMappingList._get_by_instance_uuids_from_db',
            self._fake_instancemapping_get_uuids))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMapping._save_in_db',
            self._fake_instancemapping_get_save))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell',
            self._fake_target_cell))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.set_target_cell',
            self._fake_set_target_cell))

    def _fake_hostmapping_get(self, *args):
        return {'id': 1,
                'updated_at': None,
                'created_at': None,
                'host': 'host1',
                'cell_mapping': self._fake_cell_list()[0]}

    def _fake_instancemapping_get_common(self, instance_uuid):
        return {
            'id': 1,
            'updated_at': None,
            'created_at': None,
            'instance_uuid': instance_uuid,
            'cell_id': (self.instances_created and 1 or None),
            'project_id': self.project_id,
            'cell_mapping': (
                self.instances_created and self._fake_cell_get() or None),
        }

    def _fake_instancemapping_get_save(self, *args):
        return self._fake_instancemapping_get_common(args[-2])

    def _fake_instancemapping_get(self, *args):
        return self._fake_instancemapping_get_common(args[-1])

    def _fake_instancemapping_get_uuids(self, *args):
        return [self._fake_instancemapping_get(uuid)
                for uuid in args[-1]]

    def _fake_cell_get(self, *args):
        return self._fake_cell_list()[0]

    def _fake_cell_list(self, *args):
        return [{'id': 1,
                 'updated_at': None,
                 'created_at': None,
                 'uuid': uuidsentinel.cell1,
                 'name': 'onlycell',
                 'transport_url': 'fake://nowhere/',
                 'database_connection': 'sqlite:///',
                 'disabled': False}]

    @contextmanager
    def _fake_target_cell(self, context, target_cell):
        # Just do something simple and set/unset the cell_uuid on the context.
        if target_cell:
            context.cell_uuid = getattr(target_cell, 'uuid',
                                        uuidsentinel.cell1)
        else:
            context.cell_uuid = None
        yield context

    def _fake_set_target_cell(self, context, cell_mapping):
        # Just do something simple and set/unset the cell_uuid on the context.
        if cell_mapping:
            context.cell_uuid = getattr(cell_mapping, 'uuid',
                                        uuidsentinel.cell1)
        else:
            context.cell_uuid = None


class CheatingSerializer(rpc.RequestContextSerializer):
    """A messaging.RequestContextSerializer that helps with cells.

    Our normal serializer does not pass in the context like db_connection
    and mq_connection, for good reason. We don't really want/need to
    force a remote RPC server to use our values for this. However,
    during unit and functional tests, since we're all in the same
    process, we want cell-targeted RPC calls to preserve these values.
    Unless we had per-service config and database layer state for
    the fake services we start, this is a reasonable cheat.
    """

    def serialize_context(self, context):
        """Serialize context with the db_connection inside."""
        values = super(CheatingSerializer, self).serialize_context(context)
        values['db_connection'] = context.db_connection
        values['mq_connection'] = context.mq_connection
        return values

    def deserialize_context(self, values):
        """Deserialize context and honor db_connection if present."""
        ctxt = super(CheatingSerializer, self).deserialize_context(values)
        ctxt.db_connection = values.pop('db_connection', None)
        ctxt.mq_connection = values.pop('mq_connection', None)
        return ctxt


class CellDatabases(fixtures.Fixture):
    """Create per-cell databases for testing.

    How to use::

      fix = CellDatabases()
      fix.add_cell_database('connection1')
      fix.add_cell_database('connection2', default=True)
      self.useFixture(fix)

    Passing default=True tells the fixture which database should
    be given to code that doesn't target a specific cell.
    """

    def __init__(self):
        self._ctxt_mgrs = {}
        self._last_ctxt_mgr = None
        self._default_ctxt_mgr = None

        # NOTE(danms): Use a ReaderWriterLock to synchronize our
        # global database muckery here. If we change global db state
        # to point to a cell, we need to take an exclusive lock to
        # prevent any other calls to get_context_manager() until we
        # reset to the default.
        self._cell_lock = ReaderWriterLock()

    def _cache_schema(self, connection_str):
        # NOTE(melwitt): See the regular Database fixture for why
        # we do this.
        global DB_SCHEMA
        if not DB_SCHEMA[('main', None)]:
            ctxt_mgr = self._ctxt_mgrs[connection_str]
            engine = ctxt_mgr.writer.get_engine()
            conn = engine.connect()
            migration.db_sync(database='main')
            DB_SCHEMA[('main', None)] = "".join(line for line
                                        in conn.connection.iterdump())
            engine.dispose()

    @contextmanager
    def _wrap_target_cell(self, context, cell_mapping):
        # NOTE(danms): This method is responsible for switching global
        # database state in a safe way such that code that doesn't
        # know anything about cell targeting (i.e. compute node code)
        # can continue to operate when called from something that has
        # targeted a specific cell. In order to make this safe from a
        # dining-philosopher-style deadlock, we need to be able to
        # support multiple threads talking to the same cell at the
        # same time and potentially recursion within the same thread
        # from code that would otherwise be running on separate nodes
        # in real life, but where we're actually recursing in the
        # tests.
        #
        # The basic logic here is:
        #  1. Grab a reader lock to see if the state is already pointing at
        #     the cell we want. If it is, we can yield and return without
        #     altering the global state further. The read lock ensures that
        #     global state won't change underneath us, and multiple threads
        #     can be working at the same time, as long as they are looking
        #     for the same cell.
        #  2. If we do need to change the global state, grab a writer lock
        #     to make that change, which assumes that nothing else is looking
        #     at a cell right now. We do only non-schedulable things while
        #     holding that lock to avoid the deadlock mentioned above.
        #  3. We then re-lock with a reader lock just as step #1 above and
        #     yield to do the actual work. We can do schedulable things
        #     here and not exclude other threads from making progress.
        #     If an exception is raised, we capture that and save it.
        #     Note that it is possible that another thread has changed the
        #     global state (step #2) after we released the writer lock but
        #     before we acquired the reader lock. If this happens, we will
        #     detect the global state change and retry step #2 a limited number
        #     of times. If we happen to race repeatedly with another thread and
        #     exceed our retry limit, we will give up and raise a RuntimeError,
        #     which will fail the test.
        #  4. If we changed state in #2, we need to change it back. So we grab
        #     a writer lock again and do that.
        #  5. Finally, if an exception was raised in #3 while state was
        #     changed, we raise it to the caller.

        if cell_mapping:
            desired = self._ctxt_mgrs[cell_mapping.database_connection]
        else:
            desired = self._default_ctxt_mgr

        with self._cell_lock.read_lock():
            if self._last_ctxt_mgr == desired:
                with self._real_target_cell(context, cell_mapping) as c:
                    yield c
                    return

        raised_exc = None

        def set_last_ctxt_mgr():
            with self._cell_lock.write_lock():
                if cell_mapping is not None:
                    # This assumes the next local DB access is the same cell
                    # that was targeted last time.
                    self._last_ctxt_mgr = desired

        # Set last context manager to the desired cell's context manager.
        set_last_ctxt_mgr()

        # Retry setting the last context manager if we detect that a writer
        # changed global DB state before we take the read lock.
        for retry_time in range(0, 3):
            try:
                with self._cell_lock.read_lock():
                    if self._last_ctxt_mgr != desired:
                        # NOTE(danms): This is unlikely to happen, but it's
                        # possible another waiting writer changed the state
                        # between us letting it go and re-acquiring as a
                        # reader. If lockutils supported upgrading and
                        # downgrading locks, this wouldn't be a problem.
                        # Regardless, assert that it is still as we left it
                        # here so we don't hit the wrong cell. If this becomes
                        # a problem, we just need to retry the write section
                        # above until we land here with the cell we want.
                        raise RuntimeError(
                            'Global DB state changed underneath us')
                    try:
                        with self._real_target_cell(
                            context, cell_mapping
                        ) as ccontext:
                            yield ccontext
                    except Exception as exc:
                        raised_exc = exc
                    # Leave the retry loop after calling target_cell
                    break
            except RuntimeError:
                # Give other threads a chance to make progress, increasing the
                # wait time between attempts.
                time.sleep(retry_time)
                set_last_ctxt_mgr()

        with self._cell_lock.write_lock():
            # Once we have returned from the context, we need
            # to restore the default context manager for any
            # subsequent calls
            self._last_ctxt_mgr = self._default_ctxt_mgr

        if raised_exc:
            raise raised_exc

    def _wrap_create_context_manager(self, connection=None):
        ctxt_mgr = self._ctxt_mgrs[connection]
        return ctxt_mgr

    def _wrap_get_context_manager(self, context):
        try:
            # If already targeted, we can proceed without a lock
            if context.db_connection:
                return context.db_connection
        except AttributeError:
            # Unit tests with None, FakeContext, etc
            pass

        # NOTE(melwitt): This is a hack to try to deal with
        # local accesses i.e. non target_cell accesses.
        with self._cell_lock.read_lock():
            # FIXME(mriedem): This is actually misleading and means we don't
            # catch things like bug 1717000 where a context should be targeted
            # to a cell but it's not, and the fixture here just returns the
            # last targeted context that was used.
            return self._last_ctxt_mgr

    def _wrap_get_server(self, target, endpoints, serializer=None):
        """Mirror rpc.get_server() but with our special sauce."""
        serializer = CheatingSerializer(serializer)
        return messaging.get_rpc_server(rpc.TRANSPORT,
                                        target,
                                        endpoints,
                                        executor='eventlet',
                                        serializer=serializer)

    def _wrap_get_client(self, target, version_cap=None, serializer=None,
                         call_monitor_timeout=None):
        """Mirror rpc.get_client() but with our special sauce."""
        serializer = CheatingSerializer(serializer)
        return messaging.get_rpc_client(rpc.TRANSPORT, target,
            version_cap=version_cap,
            serializer=serializer,
            call_monitor_timeout=call_monitor_timeout)

    def add_cell_database(self, connection_str, default=False):
        """Add a cell database to the fixture.

        :param connection_str: An identifier used to represent the connection
        string for this database. It should match the database_connection field
        in the corresponding CellMapping.
        """

        # NOTE(danms): Create a new context manager for the cell, which
        # will house the sqlite:// connection for this cell's in-memory
        # database. Store/index it by the connection string, which is
        # how we identify cells in CellMapping.
        ctxt_mgr = main_db_api.create_context_manager()
        self._ctxt_mgrs[connection_str] = ctxt_mgr

        # NOTE(melwitt): The first DB access through service start is
        # local so this initializes _last_ctxt_mgr for that and needs
        # to be a compute cell.
        self._last_ctxt_mgr = ctxt_mgr

        # NOTE(danms): Record which context manager should be the default
        # so we can restore it when we return from target-cell contexts.
        # If none has been provided yet, store the current one in case
        # no default is ever specified.
        if self._default_ctxt_mgr is None or default:
            self._default_ctxt_mgr = ctxt_mgr

        def get_context_manager(context):
            return ctxt_mgr

        # NOTE(danms): This is a temporary MonkeyPatch just to get
        # a new database created with the schema we need and the
        # context manager for it stashed.
        with fixtures.MonkeyPatch(
            'nova.db.main.api.get_context_manager',
            get_context_manager,
        ):
            engine = ctxt_mgr.writer.get_engine()
            engine.dispose()
            self._cache_schema(connection_str)
            conn = engine.connect()
            conn.connection.executescript(DB_SCHEMA[('main', None)])

    def setUp(self):
        super(CellDatabases, self).setUp()
        self.addCleanup(self.cleanup)
        self._real_target_cell = context.target_cell

        # NOTE(danms): These context managers are in place for the
        # duration of the test (unlike the temporary ones above) and
        # provide the actual "runtime" switching of connections for us.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.main.api.create_context_manager',
            self._wrap_create_context_manager))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.main.api.get_context_manager',
            self._wrap_get_context_manager))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell',
            self._wrap_target_cell))

        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.get_server',
            self._wrap_get_server))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.get_client',
            self._wrap_get_client))

    def cleanup(self):
        for ctxt_mgr in self._ctxt_mgrs.values():
            engine = ctxt_mgr.writer.get_engine()
            engine.dispose()


class Database(fixtures.Fixture):

    # TODO(stephenfin): The 'version' argument is unused and can be removed
    def __init__(self, database='main', version=None, connection=None):
        """Create a database fixture.

        :param database: The type of database, 'main', or 'api'
        :param connection: The connection string to use
        """
        super().__init__()

        assert database in {'main', 'api'}, f'Unrecognized database {database}'
        if database == 'api':
            assert connection is None, 'Not supported for the API database'

        self.database = database
        self.version = version
        self.connection = connection

    def setUp(self):
        super().setUp()

        if self.database == 'main':

            if self.connection is not None:
                ctxt_mgr = main_db_api.create_context_manager(
                    connection=self.connection)
                self.get_engine = ctxt_mgr.writer.get_engine
            else:
                # NOTE(gibi): this injects a new factory for each test and
                # cleans it up at then end of the test case. This way we can
                # let each test configure the factory so we can avoid having a
                # global flag guarding against factory re-configuration
                new_engine = enginefacade.transaction_context()
                self.useFixture(
                    db_fixtures.ReplaceEngineFacadeFixture(
                        main_db_api.context_manager, new_engine))
                main_db_api.configure(CONF)

                self.get_engine = main_db_api.get_engine
        elif self.database == 'api':
            # NOTE(gibi): similar note applies here as for the main_db_api
            # above
            new_engine = enginefacade.transaction_context()
            self.useFixture(
                db_fixtures.ReplaceEngineFacadeFixture(
                    api_db_api.context_manager, new_engine))
            api_db_api.configure(CONF)

            self.get_engine = api_db_api.get_engine

        self._apply_schema()

        self.addCleanup(self.cleanup)

    def _apply_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA[(self.database, self.version)]:
            # apply and cache schema
            engine = self.get_engine()
            conn = engine.connect()
            migration.db_sync(database=self.database, version=self.version)
            DB_SCHEMA[(self.database, self.version)] = "".join(
                line for line in conn.connection.iterdump())
        else:
            # apply the cached schema
            engine = self.get_engine()
            conn = engine.connect()
            conn.connection.executescript(
                DB_SCHEMA[(self.database, self.version)])

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()


class DefaultFlavorsFixture(fixtures.Fixture):
    def setUp(self):
        super(DefaultFlavorsFixture, self).setUp()
        ctxt = context.get_admin_context()
        defaults = {'rxtx_factor': 1.0, 'disabled': False, 'is_public': True,
                    'ephemeral_gb': 0, 'swap': 0}
        extra_specs = {
            "hw:numa_nodes": "1"
        }
        default_flavors = [
            objects.Flavor(context=ctxt, memory_mb=512, vcpus=1,
                           root_gb=1, flavorid='1', name='m1.tiny',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=2048, vcpus=1,
                           root_gb=20, flavorid='2', name='m1.small',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=4096, vcpus=2,
                           root_gb=40, flavorid='3', name='m1.medium',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=8192, vcpus=4,
                           root_gb=80, flavorid='4', name='m1.large',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=16384, vcpus=8,
                           root_gb=160, flavorid='5', name='m1.xlarge',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=512, vcpus=1,
                           root_gb=1, flavorid='6', name='m1.tiny.specs',
                           extra_specs=extra_specs, **defaults),
            ]
        # Sending out notifications results in loading all projects
        # which is relatively expensive for the setup of each unit test
        with mock.patch.object(objects.Flavor, '_send_notification'):
            for flavor in default_flavors:
                flavor.create()


class RPCFixture(fixtures.Fixture):
    def __init__(self, *exmods):
        super(RPCFixture, self).__init__()
        self.exmods = []
        self.exmods.extend(exmods)
        self._buses = {}

    def _fake_create_transport(self, url):
        # FIXME(danms): Right now, collapse all connections
        # to a single bus. This is how our tests expect things
        # to work. When the tests are fixed, this fixture can
        # support simulating multiple independent buses, and this
        # hack should be removed.
        url = None

        # NOTE(danms): This will be called with a non-None url by
        # cells-aware code that is requesting to contact something on
        # one of the many transports we're multplexing here.
        if url not in self._buses:
            exmods = rpc.get_allowed_exmods()
            self._buses[url] = messaging.get_rpc_transport(
                CONF,
                url=url,
                allowed_remote_exmods=exmods)
        return self._buses[url]

    def setUp(self):
        super(RPCFixture, self).setUp()
        self.addCleanup(rpc.cleanup)
        rpc.add_extra_exmods(*self.exmods)
        self.addCleanup(rpc.clear_extra_exmods)
        self.messaging_conf = messaging_conffixture.ConfFixture(CONF)
        self.messaging_conf.transport_url = 'fake:/'
        self.useFixture(self.messaging_conf)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.create_transport', self._fake_create_transport))
        # NOTE(danms): Execute the init with get_transport_url() as None,
        # instead of the parsed TransportURL(None) so that we can cache
        # it as it will be called later if the default is requested by
        # one of our mq-switching methods.
        with mock.patch('nova.rpc.get_transport_url') as mock_gtu:
            mock_gtu.return_value = None
            rpc.init(CONF)

        def cleanup_in_flight_rpc_messages():
            messaging._drivers.impl_fake.FakeExchangeManager._exchanges = {}

        self.addCleanup(cleanup_in_flight_rpc_messages)


class WarningsFixture(fixtures.Fixture):
    """Filters out warnings during test runs."""

    def setUp(self):
        super().setUp()

        self._original_warning_filters = warnings.filters[:]

        # NOTE(sdague): Make deprecation warnings only happen once. Otherwise
        # this gets kind of crazy given the way that upstream python libs use
        # this.
        warnings.simplefilter("once", DeprecationWarning)

        # NOTE(sdague): this remains an unresolved item around the way
        # forward on is_admin, the deprecation is definitely really premature.
        warnings.filterwarnings(
            'ignore',
            message=(
                'Policy enforcement is depending on the value of is_admin. '
                'This key is deprecated. Please update your policy '
                'file to use the standard policy values.'
            ),
        )

        # NOTE(mriedem): Ignore scope check UserWarnings from oslo.policy.
        warnings.filterwarnings(
            'ignore',
            message="Policy .* failed scope check",
            category=UserWarning,
        )

        # NOTE(gibi): The UUIDFields emits a warning if the value is not a
        # valid UUID. Let's escalate that to an exception in the test to
        # prevent adding violations.
        warnings.filterwarnings('error', message=".*invalid UUID.*")

        # NOTE(mriedem): Avoid adding anything which tries to convert an
        # object to a primitive which jsonutils.to_primitive() does not know
        # how to handle (or isn't given a fallback callback).
        warnings.filterwarnings(
            'error',
            message=(
                'Cannot convert <oslo_db.sqlalchemy.enginefacade._Default '
                'object at '
            ),
            category=UserWarning,
        )

        # Enable deprecation warnings for nova itself to capture upcoming
        # SQLAlchemy changes

        warnings.filterwarnings(
            'ignore',
            category=sqla_exc.SADeprecationWarning,
        )

        warnings.filterwarnings(
            'error',
            module='nova',
            category=sqla_exc.SADeprecationWarning,
        )

        # Enable general SQLAlchemy warnings also to ensure we're not doing
        # silly stuff. It's possible that we'll need to filter things out here
        # with future SQLAlchemy versions, but that's a good thing

        warnings.filterwarnings(
            'error',
            module='nova',
            category=sqla_exc.SAWarning,
        )

        self.addCleanup(self._reset_warning_filters)

    def _reset_warning_filters(self):
        warnings.filters[:] = self._original_warning_filters


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
        for k, v in self.args.items():
            self.addCleanup(CONF.clear_override, k, self.group)
            CONF.set_override(k, v, self.group)


class OSAPIFixture(fixtures.Fixture):
    """Create an OS API server as a fixture.

    This spawns an OS API server as a fixture in a new greenthread in
    the current test. The fixture has a .api parameter with is a
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

    This fixture also has the following clients with various differences:

        self.admin_api - Project user with is_admin=True and the "admin" role
        self.reader_api - Project user with only the "reader" role
        self.other_api - Project user with only the "other" role
    """

    def __init__(
        self, api_version='v2', project_id=PROJECT_ID,
        use_project_id_in_urls=False, stub_keystone=True,
    ):
        """Constructor

        :param api_version: the API version that we're interested in
        using. Currently this expects 'v2' or 'v2.1' as possible
        options.
        :param project_id: the project id to use on the API.
        :param use_project_id_in_urls: If True, act like the "endpoint" in the
            "service catalog" has the legacy format including the project_id.
        :param stub_keystone: If True, stub keystonemiddleware and
            NovaKeystoneContext to simulate (but not perform) real auth.
        """
        super(OSAPIFixture, self).__init__()
        self.api_version = api_version
        self.project_id = project_id
        self.use_project_id_in_urls = use_project_id_in_urls
        self.stub_keystone = stub_keystone

    def setUp(self):
        super(OSAPIFixture, self).setUp()
        # A unique hostname for the wsgi-intercept.
        hostname = uuidsentinel.osapi_host
        port = 80
        service_name = 'osapi_compute'
        endpoint = 'http://%s:%s/' % (hostname, port)
        conf_overrides = {
            'osapi_compute_listen': hostname,
            'osapi_compute_listen_port': port,
            'debug': True,
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        if self.stub_keystone:
            self._stub_keystone()

        # Turn off manipulation of socket_options in TCPKeepAliveAdapter
        # to keep wsgi-intercept happy. Replace it with the method
        # from its superclass.
        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.TCPKeepAliveAdapter.init_poolmanager',
                adapters.HTTPAdapter.init_poolmanager))

        loader = wsgi.Loader().load_app(service_name)
        app = lambda: loader

        # re-use service setup code from wsgi_app to register
        # service, which is looked for in some tests
        wsgi_app._setup_service(CONF.host, service_name)
        intercept = interceptor.RequestsInterceptor(app, url=endpoint)
        intercept.install_intercept()
        self.addCleanup(intercept.uninstall_intercept)

        base_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': hostname, 'port': port, 'api_version': self.api_version})
        if self.use_project_id_in_urls:
            base_url += '/' + self.project_id

        self.api = client.TestOpenStackClient(
            'fake', base_url, project_id=self.project_id,
            roles=['reader', 'member'])
        self.alternative_api = client.TestOpenStackClient(
            'fake', base_url, project_id=self.project_id,
            roles=['reader', 'member'])
        self.admin_api = client.TestOpenStackClient(
            'admin', base_url, project_id=self.project_id,
            roles=['reader', 'member', 'admin'])
        self.alternative_admin_api = client.TestOpenStackClient(
            'admin', base_url, project_id=self.project_id,
            roles=['reader', 'member', 'admin'])
        self.reader_api = client.TestOpenStackClient(
            'reader', base_url, project_id=self.project_id,
            roles=['reader'])
        self.other_api = client.TestOpenStackClient(
            'other', base_url, project_id=self.project_id,
            roles=['other'])
        # Provide a way to access the wsgi application to tests using
        # the fixture.
        self.app = app

    def _stub_keystone(self):
        # Stub out authentication middleware
        # TODO(efried): Use keystonemiddleware.fixtures.AuthTokenFixture
        self.useFixture(fixtures.MockPatch(
            'keystonemiddleware.auth_token.filter_factory',
            return_value=lambda _app: _app))

        # Stub out context middleware
        def fake_ctx(env, **kwargs):
            user_id = env['HTTP_X_AUTH_USER']
            project_id = env['HTTP_X_AUTH_PROJECT_ID']
            is_admin = user_id == 'admin'
            roles = env['HTTP_X_ROLES'].split(',')
            return context.RequestContext(
                user_id, project_id, is_admin=is_admin, roles=roles, **kwargs)

        self.useFixture(fixtures.MonkeyPatch(
            'nova.api.auth.NovaKeystoneContext._create_context', fake_ctx))


class OSMetadataServer(fixtures.Fixture):
    """Create an OS Metadata API server as a fixture.

    This spawns an OS Metadata API server as a fixture in a new
    greenthread in the current test.

    TODO(sdague): ideally for testing we'd have something like the
    test client which acts like requests, but connects any of the
    interactions needed.

    """

    def setUp(self):
        super(OSMetadataServer, self).setUp()
        # in order to run these in tests we need to bind only to local
        # host, and dynamically allocate ports
        conf_overrides = {
            'metadata_listen': '127.0.0.1',
            'metadata_listen_port': 0,
            'debug': True
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        self.metadata = service.WSGIService("metadata")
        self.metadata.start()
        self.addCleanup(self.metadata.stop)
        self.md_url = "http://%s:%s/" % (
            conf_overrides['metadata_listen'],
            self.metadata.port)


class PoisonFunctions(fixtures.Fixture):
    """Poison functions so they explode if we touch them.

    When running under a non full stack test harness there are parts
    of the code that you don't want to go anywhere near. These include
    things like code that spins up extra threads, which just
    introduces races.

    """

    def setUp(self):
        super(PoisonFunctions, self).setUp()

        try:
            self._poison_libvirt_driver()
        except ImportError:
            # The libvirt driver uses modules that are not available
            # on Windows.
            if os.name != 'nt':
                raise

    def _poison_libvirt_driver(self):
        # The nova libvirt driver starts an event thread which only
        # causes trouble in tests. Make sure that if tests don't
        # properly patch it the test explodes.

        def evloop(*args, **kwargs):
            import sys
            warnings.warn("Forgot to disable libvirt event thread")
            sys.exit(1)

        # Don't poison the function if it's already mocked
        import nova.virt.libvirt.host
        if not isinstance(nova.virt.libvirt.host.Host._init_events, mock.Mock):
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


class IsolatedGreenPoolFixture(fixtures.Fixture):
    """isolate each test to a dedicated greenpool.

    Replace the default shared greenpool with a pre test greenpool
    and wait for all greenthreads to finish in test cleanup.
    """

    def __init__(self, test):
        self.test_case_id = test

    def _setUp(self):
        self.greenpool = eventlet.greenpool.GreenPool()

        def _get_default_green_pool():
            return self.greenpool
        # NOTE(sean-k-mooney): greenpools use eventlet.spawn and
        # eventlet.spawn_n so we can't stub out all calls to those functions.
        # Instead since nova only creates greenthreads directly via nova.utils
        # we stub out the default green pool. This will not capture
        # Greenthreads created via the standard lib threading module.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils._get_default_green_pool', _get_default_green_pool))
        self.addCleanup(self.do_cleanup)

    def do_cleanup(self):
        running = self.greenpool.running()
        if running:
            # kill all greenthreads in the pool before raising to prevent
            # them from interfering with other tests.
            for gt in list(self.greenpool.coroutines_running):
                if isinstance(gt, eventlet.greenthread.GreenThread):
                    gt.kill()
            # reset the global greenpool just in case.
            utils.DEFAULT_GREEN_POOL = eventlet.greenpool.GreenPool()
            if any(
                isinstance(gt, eventlet.greenthread.GreenThread)
                for gt in self.greenpool.coroutines_running
            ):
                raise RuntimeError(
                    f'detected leaked greenthreads in {self.test_case_id}')
            elif (len(self.greenpool.coroutines_running) > 0 and
                  strutils.bool_from_string(os.getenv(
                    "NOVA_RAISE_ON_GREENLET_LEAK", "0")
            )):
                raise RuntimeError(
                    f'detected leaked greenlets in {self.test_case_id}')
            else:
                self.addDetail(
                    'IsolatedGreenPoolFixture',
                    f'no leaked greenthreads detected in {self.test_case_id} '
                    'but some greenlets were running when the test finished.'
                    'They cannot be killed so they may interact with '
                    'other tests if they raise exceptions. '
                    'These greenlets were likely created by spawn_n and'
                    'and therefore are not expected to return or raise.'
                )


class _FakeGreenThread(object):
    def __init__(self, func, *args, **kwargs):
        self._result = func(*args, **kwargs)

    def cancel(self, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def kill(self, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def link(self, func, *args, **kwargs):
        func(self, *args, **kwargs)

    def unlink(self, func, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def wait(self):
        return self._result


class SpawnIsSynchronousFixture(fixtures.Fixture):
    """Patch and restore the spawn_n utility method to be synchronous"""

    def setUp(self):
        super(SpawnIsSynchronousFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.spawn_n', _FakeGreenThread))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.spawn', _FakeGreenThread))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.PoolProxy.spawn_n', _FakeGreenThread))


class _FakeExecutor(futurist.SynchronousExecutor):
    def __init__(self, *args, **kwargs):
        # Ignore kwargs (example: max_workers) that SynchronousExecutor
        # does not support.
        super(_FakeExecutor, self).__init__()


class SynchronousThreadPoolExecutorFixture(fixtures.Fixture):
    """Make GreenThreadPoolExecutor synchronous.

    Replace the GreenThreadPoolExecutor with the SynchronousExecutor.
    """

    def setUp(self):
        super(SynchronousThreadPoolExecutorFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'futurist.GreenThreadPoolExecutor', _FakeExecutor))


class BannedDBSchemaOperations(fixtures.Fixture):
    """Ban some operations for migrations"""

    def __init__(self, banned_resources=None):
        super(BannedDBSchemaOperations, self).__init__()
        self._banned_resources = banned_resources or []

    @staticmethod
    def _explode(resource, op):
        raise exception.DBNotAllowed(
            'Operation %s.%s() is not allowed in a database migration' % (
                resource, op))

    def setUp(self):
        super(BannedDBSchemaOperations, self).setUp()
        for thing in self._banned_resources:
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.drop' % thing,
                lambda *a, **k: self._explode(thing, 'drop')))
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.alter' % thing,
                lambda *a, **k: self._explode(thing, 'alter')))


class ForbidNewLegacyNotificationFixture(fixtures.Fixture):
    """Make sure the test fails if new legacy notification is added"""

    def __init__(self):
        super(ForbidNewLegacyNotificationFixture, self).__init__()
        self.notifier = rpc.LegacyValidatingNotifier

    def setUp(self):
        super(ForbidNewLegacyNotificationFixture, self).setUp()
        self.notifier.fatal = True

        # allow the special test value used in
        # nova.tests.unit.test_notifications.NotificationsTestCase
        self.notifier.allowed_legacy_notification_event_types.append(
                '_decorated_function')

        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.notifier.fatal = False
        self.notifier.allowed_legacy_notification_event_types.remove(
                '_decorated_function')


class AllServicesCurrent(fixtures.Fixture):
    def setUp(self):
        super(AllServicesCurrent, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.Service.get_minimum_version_multi',
            self._fake_minimum))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.service.get_minimum_version_all_cells',
            lambda *a, **k: service_obj.SERVICE_VERSION))
        compute_rpcapi.LAST_VERSION = None

    def _fake_minimum(self, *args, **kwargs):
        return service_obj.SERVICE_VERSION


class _NoopConductor(object):
    def __getattr__(self, key):
        def _noop_rpc(*args, **kwargs):
            return None
        return _noop_rpc


class NoopConductorFixture(fixtures.Fixture):
    """Stub out the conductor API to do nothing"""

    def setUp(self):
        super(NoopConductorFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.conductor.ComputeTaskAPI', _NoopConductor))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.conductor.API', _NoopConductor))


class EventReporterStub(fixtures.Fixture):

    def setUp(self):
        super(EventReporterStub, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.compute.utils.EventReporter',
            lambda *args, **kwargs: mock.MagicMock()))


class UnHelperfulClientChannel(privsep_daemon._ClientChannel):
    def __init__(self, context):
        raise Exception('You have attempted to start a privsep helper. '
                        'This is not allowed in the gate, and '
                        'indicates a failure to have mocked your tests.')


class PrivsepNoHelperFixture(fixtures.Fixture):
    """A fixture to catch failures to mock privsep's rootwrap helper.

    If you fail to mock away a privsep'd method in a unit test, then
    you may well end up accidentally running the privsep rootwrap
    helper. This will fail in the gate, but it fails in a way which
    doesn't identify which test is missing a mock. Instead, we
    raise an exception so that you at least know where you've missed
    something.
    """

    def setUp(self):
        super(PrivsepNoHelperFixture, self).setUp()

        self.useFixture(fixtures.MonkeyPatch(
            'oslo_privsep.daemon.RootwrapClientChannel',
            UnHelperfulClientChannel))


class PrivsepFixture(fixtures.Fixture):
    """Disable real privsep checking so we can test the guts of methods
    decorated with sys_admin_pctxt.
    """

    def setUp(self):
        super(PrivsepFixture, self).setUp()
        self.useFixture(fixtures.MockPatchObject(
            nova.privsep.sys_admin_pctxt, 'client_mode', False))


class CGroupsFixture(fixtures.Fixture):
    """Mocks checks made for available subsystems on the host's control group.

    The fixture mocks all calls made on the host to verify the capabilities
    provided by its kernel. Through this, one can simulate the underlying
    system hosts work on top of and have tests react to expected outcomes from
    such.

    Use sample:
    >>> cgroups = self.useFixture(CGroupsFixture())
    >>> cgroups = self.useFixture(CGroupsFixture(version=2))
    >>> cgroups = self.useFixture(CGroupsFixture())
    ... cgroups.version = 2

    :attr version: Arranges mocks to simulate the host interact with nova
                   following the given version of cgroups.
                   Available values are:
                        - 0: All checks related to cgroups will return False.
                        - 1: Checks related to cgroups v1 will return True.
                        - 2: Checks related to cgroups v2 will return True.
                   Defaults to 1.
    """

    def __init__(self, version=1):
        self._cpuv1 = None
        self._cpuv2 = None

        self._version = version

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        self._version = value
        self._update_mocks()

    def setUp(self):
        super().setUp()
        self._cpuv1 = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._has_cgroupsv1_cpu_controller')).mock
        self._cpuv2 = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._has_cgroupsv2_cpu_controller')).mock
        self._update_mocks()

    def _update_mocks(self):
        if not self._cpuv1:
            return

        if not self._cpuv2:
            return

        if self.version == 0:
            self._cpuv1.return_value = False
            self._cpuv2.return_value = False
            return

        if self.version == 1:
            self._cpuv1.return_value = True
            self._cpuv2.return_value = False
            return

        if self.version == 2:
            self._cpuv1.return_value = False
            self._cpuv2.return_value = True
            return

        raise ValueError(f"Unknown cgroups version: '{self.version}'.")


class NoopQuotaDriverFixture(fixtures.Fixture):
    """A fixture to run tests using the NoopQuotaDriver.

    We can't simply set self.flags to the NoopQuotaDriver in tests to use the
    NoopQuotaDriver because the QuotaEngine object is global. Concurrently
    running tests will fail intermittently because they might get the
    NoopQuotaDriver globally when they expected the default DbQuotaDriver
    behavior. So instead, we can patch the _driver property of the QuotaEngine
    class on a per-test basis.
    """

    def setUp(self):
        super(NoopQuotaDriverFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch('nova.quota.QuotaEngine._driver',
                        nova_quota.NoopQuotaDriver()))
        # Set the config option just so that code checking for the presence of
        # the NoopQuotaDriver setting will see it as expected.
        # For some reason, this does *not* work when TestCase.flags is used.
        # When using self.flags, the concurrent test failures returned.
        CONF.set_override('driver', 'nova.quota.NoopQuotaDriver', 'quota')
        self.addCleanup(CONF.clear_override, 'driver', 'quota')


class DownCellFixture(fixtures.Fixture):
    """A fixture to simulate when a cell is down either due to error or timeout

    This fixture will stub out the scatter_gather_cells routine and target_cell
    used in various cells-related API operations like listing/showing server
    details to return a ``oslo_db.exception.DBError`` per cell in the results.
    Therefore it is best used with a test scenario like this:

    1. Create a server successfully.
    2. Using the fixture, list/show servers. Depending on the microversion
       used, the API should either return minimal results or by default skip
       the results from down cells.

    Example usage::

        with nova_fixtures.DownCellFixture():
            # List servers with down cells.
            self.api.get_servers()
            # Show a server in a down cell.
            self.api.get_server(server['id'])
            # List services with down cells.
            self.admin_api.api_get('/os-services')
    """

    def __init__(self, down_cell_mappings=None):
        self.down_cell_mappings = down_cell_mappings

    def setUp(self):
        super(DownCellFixture, self).setUp()

        def stub_scatter_gather_cells(ctxt, cell_mappings, timeout, fn, *args,
                                      **kwargs):
            # Return a dict with an entry per cell mapping where the results
            # are some kind of exception.
            up_cell_mappings = objects.CellMappingList()
            if not self.down_cell_mappings:
                # User has not passed any down cells explicitly, so all cells
                # are considered as down cells.
                self.down_cell_mappings = cell_mappings
            else:
                # User has passed down cell mappings, so the rest of the cells
                # should be up meaning we should return the right results.
                # We assume that down cells will be a subset of the
                # cell_mappings.
                down_cell_uuids = [cell.uuid
                    for cell in self.down_cell_mappings]
                up_cell_mappings.objects = [cell
                    for cell in cell_mappings
                        if cell.uuid not in down_cell_uuids]

            def wrap(cell_uuid, thing):
                # We should embed the cell_uuid into the context before
                # wrapping since its used to calcualte the cells_timed_out and
                # cells_failed properties in the object.
                ctxt.cell_uuid = cell_uuid
                return multi_cell_list.RecordWrapper(ctxt, sort_ctx, thing)

            if fn is multi_cell_list.query_wrapper:
                # If the function called through scatter-gather utility is the
                # multi_cell_list.query_wrapper, we should wrap the exception
                # object into the multi_cell_list.RecordWrapper. This is
                # because unlike the other functions where the exception object
                # is returned directly, the query_wrapper wraps this into the
                # RecordWrapper object format. So if we do not wrap it will
                # blow up at the point of generating results from heapq further
                # down the stack.
                sort_ctx = multi_cell_list.RecordSortContext([], [])
                ret1 = {
                    cell_mapping.uuid: [wrap(cell_mapping.uuid,
                        db_exc.DBError())]
                    for cell_mapping in self.down_cell_mappings
                }
            else:
                ret1 = {
                    cell_mapping.uuid: db_exc.DBError()
                    for cell_mapping in self.down_cell_mappings
                }
            ret2 = {}
            for cell in up_cell_mappings:
                ctxt.cell_uuid = cell.uuid
                cctxt = context.RequestContext.from_dict(ctxt.to_dict())
                context.set_target_cell(cctxt, cell)
                result = fn(cctxt, *args, **kwargs)
                ret2[cell.uuid] = result
            return dict(list(ret1.items()) + list(ret2.items()))

        @contextmanager
        def stub_target_cell(ctxt, cell_mapping):
            # This is to give the freedom to simulate down cells for each
            # individual cell targeted function calls.
            if not self.down_cell_mappings:
                # User has not passed any down cells explicitly, so all cells
                # are considered as down cells.
                self.down_cell_mappings = [cell_mapping]
                raise db_exc.DBError()
            else:
                # if down_cell_mappings are passed, then check if this cell
                # is down or up.
                down_cell_uuids = [cell.uuid
                    for cell in self.down_cell_mappings]
                if cell_mapping.uuid in down_cell_uuids:
                    # its a down cell raise the exception straight away
                    raise db_exc.DBError()
                else:
                    # its an up cell, so yield its context
                    cctxt = context.RequestContext.from_dict(ctxt.to_dict())
                    context.set_target_cell(cctxt, cell_mapping)
                    yield cctxt

        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.scatter_gather_cells', stub_scatter_gather_cells))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell', stub_target_cell))


class AvailabilityZoneFixture(fixtures.Fixture):
    """Fixture to stub out the nova.availability_zones module

    The list of ``zones`` provided to the fixture are what get returned from
    ``get_availability_zones``.

    ``get_instance_availability_zone`` will return the availability_zone
    requested when creating a server otherwise the instance.availability_zone
    or default_availability_zone is returned.
    """

    def __init__(self, zones):
        self.zones = zones

    def setUp(self):
        super(AvailabilityZoneFixture, self).setUp()

        def fake_get_availability_zones(
                ctxt, hostapi, get_only_available=False,
                with_hosts=False, services=None):
            # A 2-item tuple is returned if get_only_available=False.
            if not get_only_available:
                return self.zones, []
            return self.zones
        self.useFixture(fixtures.MonkeyPatch(
            'nova.availability_zones.get_availability_zones',
            fake_get_availability_zones))

        def fake_get_instance_availability_zone(ctxt, instance):
            # If the server was created with a specific AZ, return it.
            reqspec = objects.RequestSpec.get_by_instance_uuid(
                ctxt, instance.uuid)
            requested_az = reqspec.availability_zone
            if requested_az:
                return requested_az
            # Otherwise return the instance.availability_zone if set else
            # the default AZ.
            return instance.availability_zone or CONF.default_availability_zone
        self.useFixture(fixtures.MonkeyPatch(
            'nova.availability_zones.get_instance_availability_zone',
            fake_get_instance_availability_zone))


class KSAFixture(fixtures.Fixture):
    """Lets us initialize an openstack.connection.Connection by stubbing the
    auth plugin.
    """

    def setUp(self):
        super(KSAFixture, self).setUp()
        self.mock_load_auth = self.useFixture(fixtures.MockPatch(
            'keystoneauth1.loading.load_auth_from_conf_options')).mock
        self.mock_load_sess = self.useFixture(fixtures.MockPatch(
            'keystoneauth1.loading.load_session_from_conf_options')).mock
        # For convenience, an attribute for the "Session" itself
        self.mock_session = self.mock_load_sess.return_value


class OpenStackSDKFixture(fixtures.Fixture):
    # This satisfies tests that happen to run through get_sdk_adapter but don't
    # care about the adapter itself (default mocks are fine).
    # TODO(efried): Get rid of this and use fixtures from openstacksdk once
    # https://storyboard.openstack.org/#!/story/2005475 is resolved.
    def setUp(self):
        super(OpenStackSDKFixture, self).setUp()
        self.useFixture(fixtures.MockPatch(
            'openstack.proxy.Proxy.get_endpoint'))
        real_make_proxy = service_description.ServiceDescription._make_proxy
        _stub_service_types = {'placement'}

        def fake_make_proxy(self, instance):
            if self.service_type in _stub_service_types:
                return instance.config.get_session_client(
                    self.service_type,
                    allow_version_hack=True,
                )
            return real_make_proxy(self, instance)
        self.useFixture(fixtures.MockPatchObject(
            service_description.ServiceDescription, '_make_proxy',
            fake_make_proxy))


class HostNameWeigher(weights.BaseHostWeigher):
    """Weigher to make the scheduler host selection deterministic.

    Note that this weigher is supposed to be used via
    HostNameWeigherFixture and will fail to instantiate if used without that
    fixture.
    """

    def __init__(self):
        self.weights = self.get_weights()

    def get_weights(self):
        raise NotImplementedError()

    def _weigh_object(self, host_state, weight_properties):
        # Any unspecified host gets no weight.
        return self.weights.get(host_state.host, 0)


class HostNameWeigherFixture(fixtures.Fixture):
    """Fixture to make the scheduler host selection deterministic.

    Note that this fixture needs to be used before the scheduler service is
    started as it changes the scheduler configuration.
    """

    def __init__(self, weights=None):
        """Create the fixture
        :param weights: A dict of weights keyed by host names. Defaulted to
            {'host1': 100, 'host2': 50, 'host3': 10}"
        """
        if weights:
            self.weights = weights
        else:
            # default weights good for most of the functional tests
            self.weights = {'host1': 100, 'host2': 50, 'host3': 10}

    def setUp(self):
        super(HostNameWeigherFixture, self).setUp()
        # Make sure that when the scheduler instantiate the HostNameWeigher it
        # is initialized with the weights that is configured in this fixture
        self.useFixture(fixtures.MockPatchObject(
            HostNameWeigher, 'get_weights', return_value=self.weights))
        # Make sure that the scheduler loads the HostNameWeigher and only that
        self.useFixture(ConfPatcher(
            weight_classes=[__name__ + '.HostNameWeigher'],
            group='filter_scheduler'))


class GenericPoisonFixture(fixtures.Fixture):
    POISON_THESE = (
        (
            'netifaces.interfaces',
            'tests should not be inspecting real interfaces on the test node',
        ),
        (
            'os.uname',
            'tests should not be inspecting host information on the test node',
        ),
    )

    def setUp(self):
        def poison_configure(method, reason):
            def fail(*a, **k):
                raise Exception('This test invokes %s, which is bad (%s); you '
                                'should mock it.' % (method, reason))
            return fail

        super(GenericPoisonFixture, self).setUp()
        for meth, why in self.POISON_THESE:
            # attempt to mock only if not already mocked
            location, attribute = meth.rsplit('.', 1)
            components = location.split('.')
            try:
                current = __import__(components[0], {}, {})
                for component in components[1:]:
                    current = getattr(current, component)

                # NOTE(stephenfin): There are a couple of mock libraries in use
                # (including mocked versions of mock from oslotest) so we can't
                # use isinstance checks here
                if 'mock' not in str(type(getattr(current, attribute))):
                    self.useFixture(fixtures.MonkeyPatch(
                        meth, poison_configure(meth, why)))
            except ImportError:
                self.useFixture(fixtures.MonkeyPatch(
                    meth, poison_configure(meth, why)))


class PropagateTestCaseIdToChildEventlets(fixtures.Fixture):
    """A fixture that adds the currently running test case id to each spawned
    eventlet. This information then later used by the NotificationFixture to
    detect if a notification was emitted by an eventlet that was spawned by a
    previous test case so such late notification can be ignored. For more
    background about what issues this can prevent see
    https://bugs.launchpad.net/nova/+bug/1946339

    """

    def __init__(self, test_case_id):
        self.test_case_id = test_case_id

    def setUp(self):
        super().setUp()

        # set the id on the main eventlet
        c = eventlet.getcurrent()
        c.test_case_id = self.test_case_id

        orig_spawn = utils.spawn

        def wrapped_spawn(func, *args, **kwargs):
            # This is still runs before the eventlet.spawn so read the id for
            # propagation
            caller = eventlet.getcurrent()
            # If there is no id set on us that means we were spawned with other
            # than nova.utils.spawn or spawn_n so the id propagation chain got
            # broken. We fall back to self.test_case_id from the fixture which
            # is good enough
            caller_test_case_id = getattr(
                caller, 'test_case_id', None) or self.test_case_id

            @functools.wraps(func)
            def test_case_id_wrapper(*args, **kwargs):
                # This runs after the eventlet.spawn in the new child.
                # Propagate the id from our caller eventlet
                current = eventlet.getcurrent()
                current.test_case_id = caller_test_case_id
                return func(*args, **kwargs)

            # call the original spawn to create the child but with our
            # new wrapper around its target
            return orig_spawn(test_case_id_wrapper, *args, **kwargs)

        # let's replace nova.utils.spawn with the wrapped one that injects
        # our initialization to the child eventlet
        self.useFixture(
            fixtures.MonkeyPatch('nova.utils.spawn', wrapped_spawn))

        # now do the same with spawn_n
        orig_spawn_n = utils.spawn_n

        def wrapped_spawn_n(func, *args, **kwargs):
            # This is still runs before the eventlet.spawn so read the id for
            # propagation
            caller = eventlet.getcurrent()
            # If there is no id set on us that means we were spawned with other
            # than nova.utils.spawn or spawn_n so the id propagation chain got
            # broken. We fall back to self.test_case_id from the fixture which
            # is good enough
            caller_test_case_id = getattr(
                caller, 'test_case_id', None) or self.test_case_id

            @functools.wraps(func)
            def test_case_id_wrapper(*args, **kwargs):
                # This runs after the eventlet.spawn in the new child.
                # Propagate the id from our caller eventlet
                current = eventlet.getcurrent()
                current.test_case_id = caller_test_case_id
                return func(*args, **kwargs)

            # call the original spawn_n to create the child but with our
            # new wrapper around its target
            return orig_spawn_n(test_case_id_wrapper, *args, **kwargs)

        # let's replace nova.utils.spawn_n with the wrapped one that injects
        # our initialization to the child eventlet
        self.useFixture(
            fixtures.MonkeyPatch('nova.utils.spawn_n', wrapped_spawn_n))


class ReaderWriterLock(lockutils.ReaderWriterLock):
    """Wrap oslo.concurrency lockutils.ReaderWriterLock to support eventlet.

    As of fasteners >= 0.15, the workaround code to use eventlet.getcurrent()
    if eventlet patching is detected has been removed and
    threading.current_thread is being used instead. Although we are running in
    a greenlet in our test environment, we are not running in a greenlet of
    type GreenThread. A GreenThread is created by calling eventlet.spawn() and
    spawn() is not used to run our tests. At the time of this writing, the
    eventlet patched threading.current_thread() method falls back to the
    original unpatched current_thread() method if it is not called from a
    GreenThead [1] and that breaks our tests involving this fixture.

    We can work around this by patching threading.current_thread() with
    eventlet.getcurrent() during creation of the lock object, if we detect we
    are eventlet patched. If we are not eventlet patched, we use a no-op
    context manager.

    Note: this wrapper should be used for any ReaderWriterLock because any lock
    may possibly be running inside a plain greenlet created by spawn_n().

    See https://github.com/eventlet/eventlet/issues/731 for details.

    [1] https://github.com/eventlet/eventlet/blob/v0.32.0/eventlet/green/threading.py#L128  # noqa
    """

    def __init__(self, *a, **kw):
        eventlet_patched = eventlet.patcher.is_monkey_patched('thread')
        mpatch = fixtures.MonkeyPatch(
            'threading.current_thread', eventlet.getcurrent)
        with mpatch if eventlet_patched else contextlib.ExitStack():
            super().__init__(*a, **kw)


class SysFsPoisonFixture(fixtures.Fixture):

    def inject_poison(self, module_name, function_name):
        import importlib
        mod = importlib.import_module(module_name)
        orig_f = getattr(mod, function_name)
        if (
            isinstance(orig_f, mock.Mock) or
            # FIXME(gibi): Is this a bug in unittest.mock? If I remove this
            # then LibvirtReportSevTraitsTests fails as builtins.open is mocked
            # there at import time via @test.patch_open. That injects a
            # MagicMock instance to builtins.open which we check here against
            # Mock (or even MagicMock) via isinstance and that check says it is
            # not a mock. More interestingly I cannot reproduce the same
            # issue with @test.patch_open and isinstance in a simple python
            # interpreter. So to make progress I'm checking the class name
            # here instead as that works.
            orig_f.__class__.__name__ == "MagicMock"
        ):
            # the target is already mocked, probably via a decorator run at
            # import time, so we don't need to inject our poison
            return

        full_name = module_name + "." + function_name

        def toxic_wrapper(*args, **kwargs):
            path = args[0]
            if isinstance(path, bytes):
                pattern = b'/sys'
            elif isinstance(path, str):
                pattern = '/sys'
            else:
                # we ignore the rest of the potential pathlike types for now
                pattern = None

            if pattern and path.startswith(pattern):
                raise Exception(
                    'This test invokes %s on %s. It is bad, you '
                    'should mock it.'
                    % (full_name, path)
                )
            else:
                return orig_f(*args, **kwargs)

        self.useFixture(fixtures.MonkeyPatch(full_name, toxic_wrapper))

    def setUp(self):
        super().setUp()
        self.inject_poison("os.path", "isdir")
        self.inject_poison("builtins", "open")
        self.inject_poison("glob", "iglob")
        self.inject_poison("os", "listdir")
        self.inject_poison("glob", "glob")
        # TODO(gibi): Would be good to poison these too but that makes
        # a bunch of test to fail
        # self.inject_poison("os.path", "exists")
        # self.inject_poison("os", "stat")


class ImportModulePoisonFixture(fixtures.Fixture):
    """Poison imports of modules unsuitable for the test environment.

    Examples are guestfs and libvirt. Ordinarily, these would not be installed
    in the test environment but if they _are_ present, it can result in
    actual calls to libvirt, for example, which could cause tests to fail.

    This fixture will inspect module imports and if they are in the disallowed
    list, it will fail the test with a helpful message about mocking needed in
    the test.
    """

    class ForbiddenModules(MetaPathFinder):
        def __init__(self, test, modules):
            super().__init__()
            self.test = test
            self.modules = modules

        def find_spec(self, fullname, path, target=None):
            if fullname in self.modules:
                self.test.fail_message = (
                    f"This test imports the '{fullname}' module, which it "
                    f'should not in the test environment. Please add '
                    f'appropriate mocking to this test.'
                )
                raise ImportError(fullname)

    def __init__(self, module_names):
        self.module_names = module_names
        self.fail_message = ''
        if isinstance(module_names, str):
            self.module_names = {module_names}
        self.meta_path_finder = self.ForbiddenModules(self, self.module_names)

    def setUp(self):
        super().setUp()
        self.addCleanup(self.cleanup)
        sys.meta_path.insert(0, self.meta_path_finder)

    def cleanup(self):
        sys.meta_path.remove(self.meta_path_finder)
        # We use a flag and check it during the cleanup phase to fail the test
        # if needed. This is done because some module imports occur inside of a
        # try-except block that ignores all exceptions, so raising an exception
        # there (which is also what self.assert* and self.fail() do underneath)
        # will not work to cause a failure in the test.
        if self.fail_message:
            raise ImportError(self.fail_message)


class ComputeNodeIdFixture(fixtures.Fixture):
    def setUp(self):
        super().setUp()

        node.LOCAL_NODE_UUID = None
        self.useFixture(fixtures.MockPatch(
            'nova.virt.node.read_local_node_uuid',
            lambda: None))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.node.write_local_node_uuid',
            lambda uuid: None))
        self.useFixture(fixtures.MockPatch(
            'nova.compute.manager.ComputeManager.'
            '_ensure_existing_node_identity',
            mock.DEFAULT))


class GreenThreadPoolShutdownWait(fixtures.Fixture):
    """Always wait for greenlets in greenpool to finish.

    We use the futurist.GreenThreadPoolExecutor, for example, in compute
    manager to run live migration jobs. It runs those jobs in bare greenlets
    created by eventlet.spawn_n(). Bare greenlets cannot be killed the same
    way as GreenThreads created by eventlet.spawn().

    Because they cannot be killed, in the test environment we must either let
    them run to completion or move on while they are still running (which can
    cause test failures as the leaked greenlets attempt to access structures
    that have already been torn down).

    When a compute service is stopped by Service.stop(), the compute manager's
    cleanup_host() method is called and while cleaning up, the compute manager
    calls the GreenThreadPoolExecutor.shutdown() method with wait=False. This
    means that a test running GreenThreadPoolExecutor jobs will not wait for
    the bare greenlets to finish running -- it will instead move on immediately
    while greenlets are still running.

    This fixture will ensure GreenThreadPoolExecutor.shutdown() is always
    called with wait=True in an effort to reduce the number of leaked bare
    greenlets.

    See https://bugs.launchpad.net/nova/+bug/1946339 for details.
    """

    def setUp(self):
        super().setUp()
        real_shutdown = futurist.GreenThreadPoolExecutor.shutdown
        self.useFixture(fixtures.MockPatch(
            'futurist.GreenThreadPoolExecutor.shutdown',
            lambda self, wait: real_shutdown(self, wait=True)))


class UnifiedLimitsFixture(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.mock_sdk_adapter = mock.Mock()
        real_get_sdk_adapter = utils.get_sdk_adapter

        def fake_get_sdk_adapter(service_type, **kwargs):
            if service_type == 'identity':
                return self.mock_sdk_adapter
            return real_get_sdk_adapter(service_type, **kwargs)

        self.useFixture(fixtures.MockPatch(
            'nova.utils.get_sdk_adapter', fake_get_sdk_adapter))

        self.mock_sdk_adapter.registered_limits.side_effect = (
            self.registered_limits)
        self.mock_sdk_adapter.limits.side_effect = self.limits
        self.mock_sdk_adapter.create_registered_limit.side_effect = (
            self.create_registered_limit)
        self.mock_sdk_adapter.create_limit.side_effect = self.create_limit

        self.registered_limits_list = []
        self.limits_list = []

    def registered_limits(self, region_id=None):
        if region_id:
            return [rl for rl in self.registered_limits_list
                    if rl.region_id == region_id]
        return self.registered_limits_list

    def limits(self, project_id=None, region_id=None):
        limits_list = self.limits_list
        if project_id:
            limits_list = [pl for pl in limits_list
                           if pl.project_id == project_id]
        if region_id:
            limits_list = [pl for pl in limits_list
                           if pl.region_id == region_id]
        return limits_list

    def create_registered_limit(self, **attrs):
        rl = collections.namedtuple(
            'RegisteredLimit',
            ['resource_name', 'default_limit', 'region_id', 'service_id'])
        rl.resource_name = attrs.get('resource_name')
        rl.default_limit = attrs.get('default_limit')
        rl.region_id = attrs.get('region_id')
        rl.service_id = attrs.get('service_id')
        self.registered_limits_list.append(rl)

    def create_limit(self, **attrs):
        pl = collections.namedtuple(
            'Limit',
            ['resource_name', 'resource_limit', 'project_id', 'region_id',
             'service_id'])
        pl.resource_name = attrs.get('resource_name')
        pl.resource_limit = attrs.get('resource_limit')
        pl.project_id = attrs.get('project_id')
        pl.region_id = attrs.get('region_id')
        pl.service_id = attrs.get('service_id')
        self.limits_list.append(pl)

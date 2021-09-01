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
from contextlib import contextmanager
import logging as std_logging
import os
import warnings

import fixtures
import futurist
import mock
from openstack import service_description
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_messaging import conffixture as messaging_conffixture
from oslo_privsep import daemon as privsep_daemon
from oslo_utils.fixture import uuidsentinel
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

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

DB_SCHEMA = collections.defaultdict(str)
SESSION_CONFIGURED = False
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
        self._cell_lock = lockutils.ReaderWriterLock()

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

        with self._cell_lock.write_lock():
            if cell_mapping is not None:
                # This assumes the next local DB access is the same cell that
                # was targeted last time.
                self._last_ctxt_mgr = desired

        with self._cell_lock.read_lock():
            if self._last_ctxt_mgr != desired:
                # NOTE(danms): This is unlikely to happen, but it's possible
                # another waiting writer changed the state between us letting
                # it go and re-acquiring as a reader. If lockutils supported
                # upgrading and downgrading locks, this wouldn't be a problem.
                # Regardless, assert that it is still as we left it here
                # so we don't hit the wrong cell. If this becomes a problem,
                # we just need to retry the write section above until we land
                # here with the cell we want.
                raise RuntimeError('Global DB state changed underneath us')

            try:
                with self._real_target_cell(context, cell_mapping) as ccontext:
                    yield ccontext
            except Exception as exc:
                raised_exc = exc

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
        return messaging.RPCClient(rpc.TRANSPORT,
                                   target,
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

        # NOTE(pkholkin): oslo_db.enginefacade is configured in tests the
        # same way as it is done for any other service that uses DB
        global SESSION_CONFIGURED
        if not SESSION_CONFIGURED:
            main_db_api.configure(CONF)
            api_db_api.configure(CONF)
            SESSION_CONFIGURED = True

        assert database in {'main', 'api'}, f'Unrecognized database {database}'

        self.database = database
        self.version = version

        if database == 'main':
            if connection is not None:
                ctxt_mgr = main_db_api.create_context_manager(
                    connection=connection)
                self.get_engine = ctxt_mgr.writer.get_engine
            else:
                self.get_engine = main_db_api.get_engine
        elif database == 'api':
            assert connection is None, 'Not supported for the API database'

            self.get_engine = api_db_api.get_engine

    def setUp(self):
        super(Database, self).setUp()
        self.reset()
        self.addCleanup(self.cleanup)

    def _cache_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA[(self.database, self.version)]:
            engine = self.get_engine()
            conn = engine.connect()
            migration.db_sync(database=self.database, version=self.version)
            DB_SCHEMA[(self.database, self.version)] = "".join(
                line for line in conn.connection.iterdump())
            engine.dispose()

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()

    def reset(self):
        engine = self.get_engine()
        engine.dispose()
        self._cache_schema()
        conn = engine.connect()
        conn.connection.executescript(
            DB_SCHEMA[(self.database, self.version)])


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
        super(WarningsFixture, self).setUp()
        # NOTE(sdague): Make deprecation warnings only happen once. Otherwise
        # this gets kind of crazy given the way that upstream python libs use
        # this.
        warnings.simplefilter("once", DeprecationWarning)

        # NOTE(sdague): this remains an unresolved item around the way
        # forward on is_admin, the deprecation is definitely really premature.
        warnings.filterwarnings(
            'ignore',
            message='Policy enforcement is depending on the value of is_admin.'
                    ' This key is deprecated. Please update your policy '
                    'file to use the standard policy values.')

        # NOTE(mriedem): Ignore scope check UserWarnings from oslo.policy.
        warnings.filterwarnings(
            'ignore',
            message="Policy .* failed scope check",
            category=UserWarning)

        # NOTE(gibi): The UUIDFields emits a warning if the value is not a
        # valid UUID. Let's escalate that to an exception in the test to
        # prevent adding violations.
        warnings.filterwarnings('error', message=".*invalid UUID.*")

        # NOTE(mriedem): Avoid adding anything which tries to convert an
        # object to a primitive which jsonutils.to_primitive() does not know
        # how to handle (or isn't given a fallback callback).
        warnings.filterwarnings(
            'error',
            message="Cannot convert <oslo_db.sqlalchemy.enginefacade"
                    "._Default object at ",
            category=UserWarning)

        warnings.filterwarnings(
            'error', message='Evaluating non-mapped column expression',
            category=sqla_exc.SAWarning)

        # Enable deprecation warnings to capture upcoming SQLAlchemy changes

        warnings.filterwarnings(
            'error',
            module='nova',
            category=sqla_exc.SADeprecationWarning)

        # TODO(stephenfin): Remove once we fix this is oslo.db 10.0.1 or so
        warnings.filterwarnings(
            'ignore',
            message=r'Invoking and_\(\) without arguments is deprecated, .*',
            category=sqla_exc.SADeprecationWarning)

        # TODO(stephenfin): Remove once we fix this in placement 5.0.2 or 6.0.0
        warnings.filterwarnings(
            'ignore',
            message='Implicit coercion of SELECT and textual SELECT .*',
            category=sqla_exc.SADeprecationWarning)

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
            'fake', base_url, project_id=self.project_id)
        self.admin_api = client.TestOpenStackClient(
            'admin', base_url, project_id=self.project_id)
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
            return context.RequestContext(
                user_id, project_id, is_admin=is_admin, **kwargs)

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
            self.useFixture(fixtures.MockPatch(
                'nova.virt.libvirt.host.Host._init_events',
                side_effect=evloop))


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
    requested when creating a server otherwise the instance.availabilty_zone
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
                if not isinstance(getattr(current, attribute), mock.Mock):
                    self.useFixture(fixtures.MonkeyPatch(
                        meth, poison_configure(meth, why)))
            except ImportError:
                self.useFixture(fixtures.MonkeyPatch(
                    meth, poison_configure(meth, why)))

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

import collections
import logging as std_logging
import os
import warnings

import fixtures
import mock
from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade
from oslo_messaging import conffixture as messaging_conffixture
import six

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova.db import migration
from nova.db.sqlalchemy import api as session
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import service as service_obj
from nova import rpc
from nova import service
from nova.tests.functional.api import client

_TRUE_VALUES = ('True', 'true', '1', 'yes')

CONF = cfg.CONF
DB_SCHEMA = {'main': "", 'api': ""}
SESSION_CONFIGURED = False


class ServiceFixture(fixtures.Fixture):
    """Run a service as a test fixture."""

    def __init__(self, name, host=None, **kwargs):
        name = name
        # If not otherwise specified, the host will default to the
        # name of the service. Some things like aggregates care that
        # this is stable.
        host = host or name
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


class DatabasePoisonFixture(fixtures.Fixture):
    def setUp(self):
        super(DatabasePoisonFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'oslo_db.sqlalchemy.enginefacade._TransactionFactory.'
            '_create_session',
            self._poison_configure))

    def _poison_configure(self, *a, **k):
        warnings.warn('This test uses methods that set internal oslo_db '
                      'state, but it does not claim to use the database. '
                      'This will conflict with the setup of tests that '
                      'do use the database and cause failures later.')
        return mock.MagicMock()


class Database(fixtures.Fixture):
    def __init__(self, database='main', connection=None):
        """Create a database fixture.

        :param database: The type of database, 'main' or 'api'
        :param connection: The connection string to use
        """
        super(Database, self).__init__()
        # NOTE(pkholkin): oslo_db.enginefacade is configured in tests the same
        # way as it is done for any other service that uses db
        global SESSION_CONFIGURED
        if not SESSION_CONFIGURED:
            session.configure(CONF)
            SESSION_CONFIGURED = True
        self.database = database
        if database == 'main':
            if connection is not None:
                ctxt_mgr = session.create_context_manager(
                        connection=connection)
                facade = ctxt_mgr.get_legacy_facade()
                self.get_engine = facade.get_engine
            else:
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


class DatabaseAtVersion(fixtures.Fixture):
    def __init__(self, version, database='main'):
        """Create a database fixture.

        :param version: Max version to sync to (or None for current)
        :param database: The type of database, 'main' or 'api'
        """
        super(DatabaseAtVersion, self).__init__()
        self.database = database
        self.version = version
        if database == 'main':
            self.get_engine = session.get_engine
        elif database == 'api':
            self.get_engine = session.get_api_engine

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()

    def reset(self):
        engine = self.get_engine()
        engine.dispose()
        engine.connect()
        migration.db_sync(version=self.version, database=self.database)

    def setUp(self):
        super(DatabaseAtVersion, self).setUp()
        self.reset()
        self.addCleanup(self.cleanup)


class DefaultFlavorsFixture(fixtures.Fixture):
    def setUp(self):
        super(DefaultFlavorsFixture, self).setUp()
        ctxt = context.get_admin_context()
        defaults = {'rxtx_factor': 1.0, 'disabled': False, 'is_public': True,
                    'ephemeral_gb': 0, 'swap': 0}
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
            ]
        for flavor in default_flavors:
            flavor.create()


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
        for k, v in six.iteritems(self.args):
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

    def __init__(self, api_version='v2',
                 project_id='6f70656e737461636b20342065766572'):
        """Constructor

        :param api_version: the API version that we're interested in
        using. Currently this expects 'v2' or 'v2.1' as possible
        options.
        :param project_id: the project id to use on the API.

        """
        super(OSAPIFixture, self).__init__()
        self.api_version = api_version
        self.project_id = project_id

    def setUp(self):
        super(OSAPIFixture, self).setUp()
        # in order to run these in tests we need to bind only to local
        # host, and dynamically allocate ports
        conf_overrides = {
            'osapi_compute_listen': '127.0.0.1',
            'osapi_compute_listen_port': 0,
            'verbose': True,
            'debug': True,
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        self.osapi = service.WSGIService("osapi_compute")
        self.osapi.start()
        self.addCleanup(self.osapi.stop)

        self.auth_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': self.osapi.host, 'port': self.osapi.port,
            'api_version': self.api_version})
        self.api = client.TestOpenStackClient('fake', 'fake', self.auth_url,
                                              self.project_id)
        self.admin_api = client.TestOpenStackClient(
            'admin', 'admin', self.auth_url, self.project_id)


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
            'verbose': True,
            'debug': True
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        # NOTE(mikal): we don't have root to manipulate iptables, so just
        # zero that bit out.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.network.linux_net.IptablesManager._apply',
            lambda _: None))

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


class EngineFacadeFixture(fixtures.Fixture):
    """Fixture to isolation EngineFacade during tests.

    Because many elements of EngineFacade are based on globals, once
    an engine facade has been initialized, all future code goes
    through it. This means that the initialization of sqlite in
    databases in our Database fixture will drive all connections to
    sqlite. While that's fine in a production environment, during
    testing this means we can't test againts multiple backends in the
    same test run.

    oslo.db does not yet support a reset mechanism here. This builds a
    custom in tree engine facade fixture to handle this. Eventually
    this will be added to oslo.db and this can be removed. Tracked by
    https://bugs.launchpad.net/oslo.db/+bug/1548960

    """
    def __init__(self, ctx_manager, engine, sessionmaker):
        super(EngineFacadeFixture, self).__init__()
        self._ctx_manager = ctx_manager
        self._engine = engine
        self._sessionmaker = sessionmaker

    def setUp(self):
        super(EngineFacadeFixture, self).setUp()

        self._existing_factory = self._ctx_manager._root_factory
        self._ctx_manager._root_factory = enginefacade._TestTransactionFactory(
            self._engine, self._sessionmaker, apply_global=False,
            synchronous_reader=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self._ctx_manager._root_factory = self._existing_factory


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
        compute_rpcapi.LAST_VERSION = None

    def _fake_minimum(self, *args, **kwargs):
        return service_obj.SERVICE_VERSION


class NeutronFixture(fixtures.Fixture):
    """A fixture to boot instances with neutron ports"""

    # the default project_id in OsaAPIFixtures
    tenant_id = '6f70656e737461636b20342065766572'
    network_1 = {
        'status': 'ACTIVE',
        'subnets': [],
        'name': 'private-network',
        'admin_state_up': True,
        'tenant_id': tenant_id,
        'id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
    }
    subnet_1 = {
        'name': 'private-subnet',
        'enable_dhcp': True,
        'network_id': network_1['id'],
        'tenant_id': tenant_id,
        'dns_nameservers': [],
        'allocation_pools': [
            {
                'start': '192.168.1.1',
                'end': '192.168.1.254'
            }
        ],
        'host_routes': [],
        'ip_version': 4,
        'gateway_ip': '192.168.1.1',
        'cidr': '192.168.1.1/24',
        'id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef'
    }
    network_1['subnets'] = [subnet_1['id']]

    port_1 = {
        'id': 'ce531f90-199f-48c0-816c-13e38010b442',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:30',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.3',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id
    }

    def __init__(self, test):
        super(NeutronFixture, self).__init__()
        self.test = test

    def setUp(self):
        super(NeutronFixture, self).setUp()

        self.test.stub_out(
            'nova.network.neutronv2.api.API.'
            'validate_networks',
            lambda *args, **kwargs: 1)
        self.test.stub_out(
            'nova.network.neutronv2.api.API.'
            'create_pci_requests_for_sriov_ports',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.network.security_group.neutron_driver.SecurityGroupAPI.'
            'get_instances_security_groups_bindings',
            lambda *args, **kwargs: {})

        mock_neutron_client = mock.Mock()
        mock_neutron_client.list_extensions.return_value = {'extensions': []}
        mock_neutron_client.show_port.return_value = {
            'port': NeutronFixture.port_1}
        mock_neutron_client.list_networks.return_value = {
            'networks': [NeutronFixture.network_1]}
        mock_neutron_client.list_ports.return_value = {
            'ports': [NeutronFixture.port_1]}
        mock_neutron_client.list_subnets.return_value = {
            'subnets': [NeutronFixture.subnet_1]}
        mock_neutron_client.list_floatingips.return_value = {'floatingips': []}
        mock_neutron_client.update_port.return_value = {
            'port': NeutronFixture.port_1}

        self.test.stub_out(
            'nova.network.neutronv2.api.get_client',
            lambda *args, **kwargs: mock_neutron_client)


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


class CinderFixture(fixtures.Fixture):
    """A fixture to volume operations"""

    # the default project_id in OSAPIFixtures
    tenant_id = '6f70656e737461636b20342065766572'

    SWAP_OLD_VOL = 'a07f71dc-8151-4e7d-a0cc-cd24a3f11113'
    SWAP_NEW_VOL = '227cc671-f30b-4488-96fd-7d0bf13648d8'
    SWAP_ERR_OLD_VOL = '828419fa-3efb-4533-b458-4267ca5fe9b1'
    SWAP_ERR_NEW_VOL = '9c6d9c2d-7a8f-4c80-938d-3bf062b8d489'

    # This represents a bootable image-backed volume to test
    # boot-from-volume scenarios.
    IMAGE_BACKED_VOL = '6ca404f3-d844-4169-bb96-bc792f37de98'

    def __init__(self, test):
        super(CinderFixture, self).__init__()
        self.test = test
        self.swap_error = False
        self.swap_volume_instance_uuid = None
        self.swap_volume_instance_error_uuid = None
        # This is a map of instance UUIDs mapped to a list of volume IDs.
        # This map gets updated on attach/detach operations.
        self.attachments = collections.defaultdict(list)

    def setUp(self):
        super(CinderFixture, self).setUp()

        def fake_get(self_api, context, volume_id):
            # Check for the special swap volumes.
            if volume_id in (CinderFixture.SWAP_OLD_VOL,
                             CinderFixture.SWAP_ERR_OLD_VOL):
                volume = {
                             'status': 'available',
                             'display_name': 'TEST1',
                             'attach_status': 'detached',
                             'id': volume_id,
                             'size': 1
                         }
                if ((self.swap_volume_instance_uuid and
                     volume_id == CinderFixture.SWAP_OLD_VOL) or
                    (self.swap_volume_instance_error_uuid and
                     volume_id == CinderFixture.SWAP_ERR_OLD_VOL)):
                    instance_uuid = (self.swap_volume_instance_uuid
                        if volume_id == CinderFixture.SWAP_OLD_VOL
                        else self.swap_volume_instance_error_uuid)

                    volume.update({
                        'status': 'in-use',
                        'attachments': {
                            instance_uuid: {
                                'mountpoint': '/dev/vdb',
                                'attachment_id': volume_id
                            }
                        },
                        'attach_status': 'attached'
                    })
                return volume

            # Check to see if the volume is attached.
            for instance_uuid, volumes in self.attachments.items():
                if volume_id in volumes:
                    # The volume is attached.
                    volume = {
                        'status': 'in-use',
                        'display_name': volume_id,
                        'attach_status': 'attached',
                        'id': volume_id,
                        'size': 1,
                        'attachments': {
                            instance_uuid: {
                                'attachment_id': volume_id,
                                'mountpoint': '/dev/vdb'
                            }
                        }
                    }
                    break
            else:
                # This is a test that does not care about the actual details.
                volume = {
                    'status': 'available',
                    'display_name': 'TEST2',
                    'attach_status': 'detached',
                    'id': volume_id,
                    'size': 1
                }

            # update the status based on existing attachments
            has_attachment = any(
                [volume['id'] in attachments
                 for attachments in self.attachments.values()])
            volume['status'] = 'attached' if has_attachment else 'detached'

            # Check for our special image-backed volume.
            if volume_id == self.IMAGE_BACKED_VOL:
                # Make it a bootable volume.
                volume['bootable'] = True
                # Add the image_id metadata.
                volume['volume_image_metadata'] = {
                    # There would normally be more image metadata in here...
                    'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
                }

            return volume

        def fake_initialize_connection(self, context, volume_id, connector):
            if volume_id == CinderFixture.SWAP_ERR_NEW_VOL:
                # Return a tuple in order to raise an exception.
                return ()
            return {}

        def fake_migrate_volume_completion(self, context, old_volume_id,
                                           new_volume_id, error):
            return {'save_volume_id': new_volume_id}

        def fake_unreserve_volume(self_api, context, volume_id):
            # Signaling that swap_volume has encountered the error
            # from initialize_connection and is working on rolling back
            # the reservation on SWAP_ERR_NEW_VOL.
            self.swap_error = True

        def fake_attach(_self, context, volume_id, instance_uuid,
                        mountpoint, mode='rw'):
            # Check to see if the volume is already attached to any server.
            for instance, volumes in self.attachments.items():
                if volume_id in volumes:
                    raise exception.InvalidInput(
                        reason='Volume %s is already attached to '
                               'instance %s' % (volume_id, instance))
            # It's not attached so let's "attach" it.
            self.attachments[instance_uuid].append(volume_id)

        self.test.stub_out('nova.volume.cinder.API.attach',
                           fake_attach)

        def fake_detach(_self, context, volume_id, instance_uuid=None,
                        attachment_id=None):
            if instance_uuid is not None:
                # If the volume isn't attached to this instance it will
                # result in a ValueError which indicates a broken test or
                # code, so we just let that raise up.
                self.attachments[instance_uuid].remove(volume_id)
            else:
                for instance, volumes in self.attachments.items():
                    if volume_id in volumes:
                        volumes.remove(volume_id)
                        break

        self.test.stub_out('nova.volume.cinder.API.detach', fake_detach)

        self.test.stub_out('nova.volume.cinder.API.begin_detaching',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.check_attach',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.check_detach',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.get',
                           fake_get)
        self.test.stub_out('nova.volume.cinder.API.initialize_connection',
                           fake_initialize_connection)
        self.test.stub_out(
            'nova.volume.cinder.API.migrate_volume_completion',
            fake_migrate_volume_completion)
        self.test.stub_out('nova.volume.cinder.API.reserve_volume',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.roll_detaching',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.terminate_connection',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.unreserve_volume',
                           fake_unreserve_volume)

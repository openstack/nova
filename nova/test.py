# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Base classes for our unit tests.

Allows overriding of flags for use of fakes, and some black magic for
inline callbacks.

"""

import os
import shutil
import sys
import uuid

import eventlet
import fixtures
import mox
import stubout
import testtools

from nova import context
from nova import db
from nova.db import migration
from nova.db.sqlalchemy import session
from nova.network import manager as network_manager
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import service
from nova.tests import conf_fixture
from nova.tests import policy_fixture


test_opts = [
    cfg.StrOpt('sqlite_clean_db',
               default='clean.sqlite',
               help='File name of clean sqlite db'),
    ]

CONF = cfg.CONF
CONF.register_opts(test_opts)
CONF.import_opt('sql_connection', 'nova.db.sqlalchemy.session')
CONF.import_opt('sqlite_db', 'nova.db.sqlalchemy.session')
CONF.import_opt('state_path', 'nova.config')
CONF.set_override('use_stderr', False)

logging.setup('nova')
LOG = logging.getLogger(__name__)

eventlet.monkey_patch(os=False)

_DB_CACHE = None


class Database(fixtures.Fixture):

    def __init__(self, db_session, db_migrate, sql_connection,
                    sqlite_db, sqlite_clean_db):
        self.sql_connection = sql_connection
        self.sqlite_db = sqlite_db
        self.sqlite_clean_db = sqlite_clean_db

        self.engine = db_session.get_engine()
        self.engine.dispose()
        conn = self.engine.connect()
        if sql_connection == "sqlite://":
            if db_migrate.db_version() > db_migrate.INIT_VERSION:
                return
        else:
            testdb = os.path.join(CONF.state_path, sqlite_db)
            if os.path.exists(testdb):
                return
        db_migrate.db_sync()
        self.post_migrations()
        if sql_connection == "sqlite://":
            conn = self.engine.connect()
            self._DB = "".join(line for line in conn.connection.iterdump())
            self.engine.dispose()
        else:
            cleandb = os.path.join(CONF.state_path, sqlite_clean_db)
            shutil.copyfile(testdb, cleandb)

    def setUp(self):
        super(Database, self).setUp()

        if self.sql_connection == "sqlite://":
            conn = self.engine.connect()
            conn.connection.executescript(self._DB)
            self.addCleanup(self.engine.dispose)
        else:
            shutil.copyfile(os.path.join(CONF.state_path,
                                         self.sqlite_clean_db),
                            os.path.join(CONF.state_path,
                                         self.sqlite_db))

    def post_migrations(self):
        """Any addition steps that are needed outside of the migrations."""
        ctxt = context.get_admin_context()
        network = network_manager.VlanManager()
        bridge_interface = CONF.flat_interface or CONF.vlan_interface
        network.create_networks(ctxt,
                                label='test',
                                cidr=CONF.fixed_range,
                                multi_host=CONF.multi_host,
                                num_networks=CONF.num_networks,
                                network_size=CONF.network_size,
                                cidr_v6=CONF.fixed_range_v6,
                                gateway=CONF.gateway,
                                gateway_v6=CONF.gateway_v6,
                                bridge=CONF.flat_network_bridge,
                                bridge_interface=bridge_interface,
                                vpn_start=CONF.vpn_start,
                                vlan_start=CONF.vlan_start,
                                dns1=CONF.flat_network_dns)
        for net in db.network_get_all(ctxt):
            network.set_network_host(ctxt, net)


class ReplaceModule(fixtures.Fixture):
    """Replace a module with a fake module."""

    def __init__(self, name, new_value):
        self.name = name
        self.new_value = new_value

    def _restore(self, old_value):
        sys.modules[self.name] = old_value

    def setUp(self):
        super(ReplaceModule, self).setUp()
        old_value = sys.modules.get(self.name)
        sys.modules[self.name] = self.new_value
        self.addCleanup(self._restore, old_value)


class ServiceFixture(fixtures.Fixture):
    """Run a service as a test fixture."""

    def __init__(self, name, host=None, **kwargs):
        name = name
        host = host and host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        self.kwargs = kwargs

    def setUp(self):
        super(ServiceFixture, self).setUp()
        self.service = service.Service.create(**self.kwargs)
        self.service.start()
        self.addCleanup(self.service.kill)


class MoxStubout(fixtures.Fixture):
    """Deal with code around mox and stubout as a fixture."""

    def setUp(self):
        super(MoxStubout, self).setUp()
        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.addCleanup(self.mox.UnsetStubs)
        self.addCleanup(self.stubs.UnsetAll)
        self.addCleanup(self.stubs.SmartUnsetAll)
        self.addCleanup(self.mox.VerifyAll)


class TestingException(Exception):
    pass


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())

        if (os.environ.get('OS_STDOUT_NOCAPTURE') != 'True' and
                os.environ.get('OS_STDOUT_NOCAPTURE') != '1'):
            stdout = self.useFixture(fixtures.StringStream('stdout')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stdout', stdout))
        if (os.environ.get('OS_STDERR_NOCAPTURE') != 'True' and
                os.environ.get('OS_STDERR_NOCAPTURE') != '1'):
            stderr = self.useFixture(fixtures.StringStream('stderr')).stream
            self.useFixture(fixtures.MonkeyPatch('sys.stderr', stderr))

        self.log_fixture = self.useFixture(fixtures.FakeLogger('nova'))
        self.useFixture(conf_fixture.ConfFixture(CONF))

        global _DB_CACHE
        if not _DB_CACHE:
            _DB_CACHE = Database(session, migration,
                                    sql_connection=CONF.sql_connection,
                                    sqlite_db=CONF.sqlite_db,
                                    sqlite_clean_db=CONF.sqlite_clean_db)
        self.useFixture(_DB_CACHE)

        mox_fixture = self.useFixture(MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs
        self.addCleanup(self._clear_attrs)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

    def _clear_attrs(self):
        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__.keys() if k[0] != '_']:
            del self.__dict__[key]

    def flags(self, **kw):
        """Override flag variables for a test."""
        group = kw.pop('group', None)
        for k, v in kw.iteritems():
            CONF.set_override(k, v, group)

    def start_service(self, name, host=None, **kwargs):
        svc = self.useFixture(ServiceFixture(name, host, **kwargs))
        return svc.service


class APICoverage(object):

    cover_api = None

    def test_api_methods(self):
        self.assertTrue(self.cover_api is not None)
        api_methods = [x for x in dir(self.cover_api)
                       if not x.startswith('_')]
        test_methods = [x[5:] for x in dir(self)
                        if x.startswith('test_')]
        self.assertThat(
            test_methods,
            testtools.matchers.ContainsAll(api_methods))


class TimeOverride(fixtures.Fixture):
    """Fixture to start and remove time override."""

    def setUp(self):
        super(TimeOverride, self).setUp()
        timeutils.set_time_override()
        self.addCleanup(timeutils.clear_time_override)

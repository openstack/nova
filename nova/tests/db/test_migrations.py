# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack Foundation
# Copyright 2012-2013 IBM Corp.
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

"""
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly both upgrading and downgrading, and that no data loss occurs
if possible.

There are also "opportunistic" tests for both mysql and postgresql in here,
which allows testing against all 3 databases (sqlite in memory, mysql, pg) in
a properly configured unit test environment.

For the opportunistic testing you need to set up a db named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost.
The test will then use that db and u/p combo to run the tests.

For postgres on Ubuntu this can be done with the following commands:

sudo -u postgres psql
postgres=# create user openstack_citest with createdb login password
      'openstack_citest';
postgres=# create database openstack_citest with owner openstack_citest;
postgres=# create database openstack_baremetal_citest with owner
            openstack_citest;

"""

import ConfigParser
import datetime
import glob
import os
import urlparse

from migrate.versioning import repository
import sqlalchemy
import sqlalchemy.exc

import nova.db.sqlalchemy.migrate_repo
from nova.db.sqlalchemy import utils as db_utils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import matchers
from nova import utils
import nova.virt.baremetal.db.sqlalchemy.migrate_repo


LOG = logging.getLogger(__name__)


def _get_connect_string(backend, user, passwd, database):
    """
    Try to get a connection with a very specific set of values, if we get
    these then we'll run the tests, otherwise they are skipped
    """
    if backend == "postgres":
        backend = "postgresql+psycopg2"
    elif backend == "mysql":
        backend = "mysql+mysqldb"
    else:
        raise Exception("Unrecognized backend: '%s'" % backend)

    return ("%s://%s:%s@localhost/%s" % (backend, user, passwd, database))


def _is_backend_avail(backend, user, passwd, database):
    try:
        connect_uri = _get_connect_string(backend, user, passwd, database)
        engine = sqlalchemy.create_engine(connect_uri)
        connection = engine.connect()
    except Exception:
        # intentionally catch all to handle exceptions even if we don't
        # have any backend code loaded.
        return False
    else:
        connection.close()
        engine.dispose()
        return True


def _have_mysql(user, passwd, database):
    present = os.environ.get('NOVA_TEST_MYSQL_PRESENT')
    if present is None:
        return _is_backend_avail('mysql', user, passwd, database)
    return present.lower() in ('', 'true')


def _have_postgresql(user, passwd, database):
    present = os.environ.get('NOVA_TEST_POSTGRESQL_PRESENT')
    if present is None:
        return _is_backend_avail('postgres', user, passwd, database)
    return present.lower() in ('', 'true')


def get_mysql_connection_info(conn_pieces):
    database = conn_pieces.path.strip('/')
    loc_pieces = conn_pieces.netloc.split('@')
    host = loc_pieces[1]
    auth_pieces = loc_pieces[0].split(':')
    user = auth_pieces[0]
    password = ""
    if len(auth_pieces) > 1:
        if auth_pieces[1].strip():
            password = "-p\"%s\"" % auth_pieces[1]

    return (user, password, database, host)


def get_pgsql_connection_info(conn_pieces):
    database = conn_pieces.path.strip('/')
    loc_pieces = conn_pieces.netloc.split('@')
    host = loc_pieces[1]

    auth_pieces = loc_pieces[0].split(':')
    user = auth_pieces[0]
    password = ""
    if len(auth_pieces) > 1:
        password = auth_pieces[1].strip()

    return (user, password, database, host)


class CommonTestsMixIn(object):
    """These tests are shared between TestNovaMigrations and
    TestBaremetalMigrations.

    BaseMigrationTestCase is effectively an abstract class, meant to be derived
    from and not directly tested against; that's why these `test_` methods need
    to be on a Mixin, so that they won't be picked up as valid tests for
    BaseMigrationTestCase.
    """
    def test_walk_versions(self):
        for key, engine in self.engines.items():
            # We start each walk with a completely blank slate.
            self._reset_database(key)
            self._walk_versions(engine, self.snake_walk, self.downgrade)

    def test_mysql_opportunistically(self):
        self._test_mysql_opportunistically()

    def test_mysql_connect_fail(self):
        """
        Test that we can trigger a mysql connection failure and we fail
        gracefully to ensure we don't break people without mysql
        """
        if _is_backend_avail('mysql', "openstack_cifail", self.PASSWD,
                             self.DATABASE):
            self.fail("Shouldn't have connected")

    def test_postgresql_opportunistically(self):
        self._test_postgresql_opportunistically()

    def test_postgresql_connect_fail(self):
        """
        Test that we can trigger a postgres connection failure and we fail
        gracefully to ensure we don't break people without postgres
        """
        if _is_backend_avail('postgres', "openstack_cifail", self.PASSWD,
                             self.DATABASE):
            self.fail("Shouldn't have connected")


class BaseMigrationTestCase(test.NoDBTestCase):
    """Base class for testing migrations and migration utils. This sets up
    and configures the databases to run tests against.
    """

    # NOTE(jhesketh): It is expected that tests clean up after themselves.
    # This is necessary for concurrency to allow multiple tests to work on
    # one database.
    # The full migration walk tests however do call the old _reset_databases()
    # to throw away whatever was there so they need to operate on their own
    # database that we know isn't accessed concurrently.
    # Hence, BaseWalkMigrationTestCase overwrites the engine list.

    USER = None
    PASSWD = None
    DATABASE = None

    TIMEOUT_SCALING_FACTOR = 2

    def __init__(self, *args, **kwargs):
        super(BaseMigrationTestCase, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                       'test_migrations.conf')
        # Test machines can set the NOVA_TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get('NOVA_TEST_MIGRATIONS_CONF',
                                      self.DEFAULT_CONFIG_FILE)
        self.MIGRATE_FILE = nova.db.sqlalchemy.migrate_repo.__file__
        self.REPOSITORY = repository.Repository(
                        os.path.abspath(os.path.dirname(self.MIGRATE_FILE)))
        self.INIT_VERSION = 0

        self.snake_walk = False
        self.downgrade = False
        self.test_databases = {}
        self.migration = None
        self.migration_api = None

    def setUp(self):
        super(BaseMigrationTestCase, self).setUp()
        self._load_config()

    def _load_config(self):
        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % self.CONFIG_FILE_PATH)
        if os.path.exists(self.CONFIG_FILE_PATH):
            cp = ConfigParser.RawConfigParser()
            try:
                cp.read(self.CONFIG_FILE_PATH)
                config = cp.options('unit_tests')
                for key in config:
                    self.test_databases[key] = cp.get('unit_tests', key)
                self.snake_walk = cp.getboolean('walk_style', 'snake_walk')
                self.downgrade = cp.getboolean('walk_style', 'downgrade')

            except ConfigParser.ParsingError as e:
                self.fail("Failed to read test_migrations.conf config "
                          "file. Got error: %s" % e)
        else:
            self.fail("Failed to find test_migrations.conf config "
                      "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        # NOTE(jhesketh): We only need to make sure the databases are created
        # not necessarily clean of tables.
        self._create_databases()

    def execute_cmd(self, cmd=None):
        out, err = processutils.trycmd(cmd, shell=True, discard_warnings=True)
        output = out or err
        LOG.debug(output)
        self.assertEqual('', err,
                         "Failed to run: %s\n%s" % (cmd, output))

    @utils.synchronized('pgadmin', external=True)
    def _reset_pg(self, conn_pieces):
        (user, password, database, host) = \
            get_pgsql_connection_info(conn_pieces)
        os.environ['PGPASSWORD'] = password
        os.environ['PGUSER'] = user
        # note(boris-42): We must create and drop database, we can't
        # drop database which we have connected to, so for such
        # operations there is a special database template1.
        sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                  " '%(sql)s' -d template1")
        sqldict = {'user': user, 'host': host}

        sqldict['sql'] = ("drop database if exists %s;") % database
        droptable = sqlcmd % sqldict
        self.execute_cmd(droptable)

        sqldict['sql'] = ("create database %s;") % database
        createtable = sqlcmd % sqldict
        self.execute_cmd(createtable)

        os.unsetenv('PGPASSWORD')
        os.unsetenv('PGUSER')

    @utils.synchronized('mysql', external=True)
    def _reset_mysql(self, conn_pieces):
        # We can execute the MySQL client to destroy and re-create
        # the MYSQL database, which is easier and less error-prone
        # than using SQLAlchemy to do this via MetaData...trust me.
        (user, password, database, host) = \
                get_mysql_connection_info(conn_pieces)
        sql = ("drop database if exists %(database)s; "
                "create database %(database)s;" % {'database': database})
        cmd = ("mysql -u \"%(user)s\" %(password)s -h %(host)s "
               "-e \"%(sql)s\"" % {'user': user, 'password': password,
                                   'host': host, 'sql': sql})
        self.execute_cmd(cmd)

    @utils.synchronized('sqlite', external=True)
    def _reset_sqlite(self, conn_pieces):
        # We can just delete the SQLite database, which is
        # the easiest and cleanest solution
        db_path = conn_pieces.path.strip('/')
        if os.path.exists(db_path):
            os.unlink(db_path)
        # No need to recreate the SQLite DB. SQLite will
        # create it for us if it's not there...

    def _create_databases(self):
        """Create all configured databases as needed."""
        for key, engine in self.engines.items():
            self._create_database(key)

    def _create_database(self, key):
        """Create database if it doesn't exist."""
        conn_string = self.test_databases[key]
        conn_pieces = urlparse.urlparse(conn_string)

        if conn_string.startswith('mysql'):
            (user, password, database, host) = \
                get_mysql_connection_info(conn_pieces)
            sql = "create database if not exists %s;" % database
            cmd = ("mysql -u \"%(user)s\" %(password)s -h %(host)s "
                   "-e \"%(sql)s\"" % {'user': user, 'password': password,
                                       'host': host, 'sql': sql})
            self.execute_cmd(cmd)
        elif conn_string.startswith('postgresql'):
            (user, password, database, host) = \
                get_pgsql_connection_info(conn_pieces)
            os.environ['PGPASSWORD'] = password
            os.environ['PGUSER'] = user

            sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                      " '%(sql)s' -d template1")

            sql = ("create database if not exists %s;") % database
            createtable = sqlcmd % {'user': user, 'host': host, 'sql': sql}
            # 0 means databases is created
            # 256 means it already exists (which is fine)
            # otherwise raise an error
            out, err = processutils.trycmd(createtable, shell=True,
                                           check_exit_code=[0, 256],
                                           discard_warnings=True)
            output = out or err
            if err != '':
                self.fail("Failed to run: %s\n%s" % (createtable, output))

            os.unsetenv('PGPASSWORD')
            os.unsetenv('PGUSER')

    def _reset_databases(self):
        """Reset all configured databases."""
        for key, engine in self.engines.items():
            self._reset_database(key)

    def _reset_database(self, key):
        """Reset specific database."""
        engine = self.engines[key]
        conn_string = self.test_databases[key]
        conn_pieces = urlparse.urlparse(conn_string)
        engine.dispose()
        if conn_string.startswith('sqlite'):
            self._reset_sqlite(conn_pieces)
        elif conn_string.startswith('mysql'):
            self._reset_mysql(conn_pieces)
        elif conn_string.startswith('postgresql'):
            self._reset_pg(conn_pieces)


class BaseWalkMigrationTestCase(BaseMigrationTestCase):
    """BaseWalkMigrationTestCase loads in an alternative set of databases for
    testing against. This is necessary as the default databases can run tests
    concurrently without interfering with itself. It is expected that
    databases listed under [migraiton_dbs] in the configuration are only being
    accessed by one test at a time. Currently only test_walk_versions accesses
    the databases (and is the only method that calls _reset_database() which
    is clearly problematic for concurrency).
    """

    def _load_config(self):
        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % self.CONFIG_FILE_PATH)
        if os.path.exists(self.CONFIG_FILE_PATH):
            cp = ConfigParser.RawConfigParser()
            try:
                cp.read(self.CONFIG_FILE_PATH)
                config = cp.options('migration_dbs')
                for key in config:
                    self.test_databases[key] = cp.get('migration_dbs', key)
                self.snake_walk = cp.getboolean('walk_style', 'snake_walk')
                self.downgrade = cp.getboolean('walk_style', 'downgrade')
            except ConfigParser.ParsingError as e:
                self.fail("Failed to read test_migrations.conf config "
                          "file. Got error: %s" % e)
        else:
            self.fail("Failed to find test_migrations.conf config "
                      "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        self._create_databases()

    def _test_mysql_opportunistically(self):
        # Test that table creation on mysql only builds InnoDB tables
        if not _have_mysql(self.USER, self.PASSWD, self.DATABASE):
            self.skipTest("mysql not available")
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        connect_string = _get_connect_string("mysql", self.USER, self.PASSWD,
                self.DATABASE)
        (user, password, database, host) = \
                get_mysql_connection_info(urlparse.urlparse(connect_string))
        engine = sqlalchemy.create_engine(connect_string)
        self.engines[database] = engine
        self.test_databases[database] = connect_string

        # build a fully populated mysql database with all the tables
        self._reset_database(database)
        self._walk_versions(engine, self.snake_walk, self.downgrade)

        connection = engine.connect()
        # sanity check
        total = connection.execute("SELECT count(*) "
                                   "from information_schema.TABLES "
                                   "where TABLE_SCHEMA='%(database)s'" %
                                   {'database': database})
        self.assertTrue(total.scalar() > 0, "No tables found. Wrong schema?")

        noninnodb = connection.execute("SELECT count(*) "
                                       "from information_schema.TABLES "
                                       "where TABLE_SCHEMA='%(database)s' "
                                       "and ENGINE!='InnoDB' "
                                       "and TABLE_NAME!='migrate_version'" %
                                       {'database': database})
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)
        connection.close()

        del(self.engines[database])
        del(self.test_databases[database])

    def _test_postgresql_opportunistically(self):
        # Test postgresql database migration walk
        if not _have_postgresql(self.USER, self.PASSWD, self.DATABASE):
            self.skipTest("postgresql not available")
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        connect_string = _get_connect_string("postgres", self.USER,
                self.PASSWD, self.DATABASE)
        engine = sqlalchemy.create_engine(connect_string)
        (user, password, database, host) = \
                get_mysql_connection_info(urlparse.urlparse(connect_string))
        self.engines[database] = engine
        self.test_databases[database] = connect_string

        # build a fully populated postgresql database with all the tables
        self._reset_database(database)
        self._walk_versions(engine, self.snake_walk, self.downgrade)
        del(self.engines[database])
        del(self.test_databases[database])

    def _walk_versions(self, engine=None, snake_walk=False, downgrade=True):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        self.migration_api.version_control(engine,
                self.REPOSITORY,
                self.INIT_VERSION)
        self.assertEqual(self.INIT_VERSION,
                self.migration_api.db_version(engine,
                                         self.REPOSITORY))

        LOG.debug('latest version is %s' % self.REPOSITORY.latest)
        versions = range(self.INIT_VERSION + 1, self.REPOSITORY.latest + 1)

        for version in versions:
            # upgrade -> downgrade -> upgrade
            self._migrate_up(engine, version, with_data=True)
            if snake_walk:
                downgraded = self._migrate_down(
                        engine, version - 1, with_data=True)
                if downgraded:
                    self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(versions):
                # downgrade -> upgrade -> downgrade
                downgraded = self._migrate_down(engine, version - 1)

                if snake_walk and downgraded:
                    self._migrate_up(engine, version)
                    self._migrate_down(engine, version - 1)

    def _migrate_down(self, engine, version, with_data=False):
        try:
            self.migration_api.downgrade(engine, self.REPOSITORY, version)
        except NotImplementedError:
            # NOTE(sirp): some migrations, namely release-level
            # migrations, don't support a downgrade.
            return False

        self.assertEqual(version,
                         self.migration_api.db_version(engine,
                                                  self.REPOSITORY))

        # NOTE(sirp): `version` is what we're downgrading to (i.e. the 'target'
        # version). So if we have any downgrade checks, they need to be run for
        # the previous (higher numbered) migration.
        if with_data:
            post_downgrade = getattr(
                    self, "_post_downgrade_%03d" % (version + 1), None)
            if post_downgrade:
                post_downgrade(engine)

        return True

    def _migrate_up(self, engine, version, with_data=False):
        """migrate up to a new version of the db.

        We allow for data insertion and post checks at every
        migration version with special _pre_upgrade_### and
        _check_### functions in the main test.
        """
        # NOTE(sdague): try block is here because it's impossible to debug
        # where a failed data migration happens otherwise
        try:
            if with_data:
                data = None
                pre_upgrade = getattr(
                        self, "_pre_upgrade_%03d" % version, None)
                if pre_upgrade:
                    data = pre_upgrade(engine)

            self.migration_api.upgrade(engine, self.REPOSITORY, version)
            self.assertEqual(version,
                             self.migration_api.db_version(engine,
                                                           self.REPOSITORY))
            if with_data:
                check = getattr(self, "_check_%03d" % version, None)
                if check:
                    check(engine, data)
        except Exception:
            LOG.error("Failed to migrate to version %s on engine %s" %
                      (version, engine))
            raise


class TestNovaMigrations(BaseWalkMigrationTestCase, CommonTestsMixIn):
    """Test sqlalchemy-migrate migrations."""
    USER = "openstack_citest"
    PASSWD = "openstack_citest"
    DATABASE = "openstack_citest"

    def __init__(self, *args, **kwargs):
        super(TestNovaMigrations, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                       'test_migrations.conf')
        # Test machines can set the NOVA_TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get('NOVA_TEST_MIGRATIONS_CONF',
                                      self.DEFAULT_CONFIG_FILE)
        self.MIGRATE_FILE = nova.db.sqlalchemy.migrate_repo.__file__
        self.REPOSITORY = repository.Repository(
                        os.path.abspath(os.path.dirname(self.MIGRATE_FILE)))

    def setUp(self):
        super(TestNovaMigrations, self).setUp()

        if self.migration is None:
            self.migration = __import__('nova.db.migration',
                    globals(), locals(), ['db_initial_version'], -1)
            self.INIT_VERSION = self.migration.db_initial_version()
        if self.migration_api is None:
            temp = __import__('nova.db.sqlalchemy.migration',
                    globals(), locals(), ['versioning_api'], -1)
            self.migration_api = temp.versioning_api

    def assertColumnExists(self, engine, table, column):
        t = db_utils.get_table(engine, table)
        self.assertIn(column, t.c)

    def assertColumnNotExists(self, engine, table, column):
        t = db_utils.get_table(engine, table)
        self.assertNotIn(column, t.c)

    def assertIndexExists(self, engine, table, index):
        t = db_utils.get_table(engine, table)
        index_names = [idx.name for idx in t.indexes]
        self.assertIn(index, index_names)

    def assertIndexMembers(self, engine, table, index, members):
        self.assertIndexExists(engine, table, index)

        t = db_utils.get_table(engine, table)
        index_columns = None
        for idx in t.indexes:
            if idx.name == index:
                index_columns = idx.columns.keys()
                break

        self.assertEqual(sorted(members), sorted(index_columns))

    def _check_181(self, engine, data):
        self.assertTrue(db_utils.check_shadow_table(engine, 'cells'))

    def _pre_upgrade_182(self, engine):
        CIDR = '6666:1020:1000:2013:1000:6535:abcd:abcd'

        security_group_rules = \
                    db_utils.get_table(engine, 'shadow_security_group_rules')
        values = {
            'id': 182,
            'protocol': 'tcp',
            'from_port': 6666,
            'to_port': 9999,
            'cidr': CIDR,
            'deleted': 0
        }
        security_group_rules.insert().values(values).execute()

        networks = db_utils.get_table(engine, 'shadow_networks')
        values = {
            'id': 182,
            'vlan': 100500,
            'cidr': CIDR,
            'cidr_v6': CIDR,
            'deleted': 0
        }
        networks.insert().values(values).execute()

        provider_fw_rules = db_utils.get_table(engine,
                                               'shadow_provider_fw_rules')
        values = {
            'id': 182,
            'protocol': 'tcp',
            'from_port': 6666,
            'to_port': 9999,
            'cidr': CIDR,
            'deleted': 0
        }
        provider_fw_rules.insert().values(values).execute()
        return {'cidr': CIDR}

    def _check_182(self, engine, data):
        self.assertTrue(db_utils.check_shadow_table(engine,
                                                    'security_group_rules'))
        self.assertTrue(db_utils.check_shadow_table(engine,
                                                    'provider_fw_rules'))
        self.assertTrue(db_utils.check_shadow_table(engine, 'networks'))

        table_fields = {
            'shadow_security_group_rules': ['cidr'],
            'shadow_networks': ['cidr', 'cidr_v6'],
            'shadow_provider_fw_rules': ['cidr']
        }

        for table_name, fields in table_fields.iteritems():
            table = db_utils.get_table(engine, table_name)
            rows = table.\
                        select().\
                        where(table.c.id == 182).\
                        execute().\
                        fetchall()
            self.assertEqual(len(rows), 1)
            for field in fields:
                self.assertEqual(rows[0][field], data['cidr'])

            for field in fields:
                # we should be able to store mask in cidr fields also
                table.\
                    update().\
                    values({field: data['cidr'] + '/128'}).\
                    execute()

    def _check_183(self, engine, data):
        table_name = 'security_group_default_rules'
        self.assertTrue(db_utils.check_shadow_table(engine, table_name))

    def _check_184(self, engine, data):
        self.assertTrue(db_utils.check_shadow_table(engine, 'instances'))
        self.assertTrue(db_utils.check_shadow_table(engine, 'networks'))
        self.assertTrue(db_utils.check_shadow_table(engine, 'fixed_ips'))
        self.assertTrue(db_utils.check_shadow_table(engine, 'floating_ips'))
        self.assertTrue(db_utils.check_shadow_table(engine, 'console_pools'))

    def _unique_constraint_check_migrate_185(self, engine, check=True):
        """Test check unique constraint behavior.

        It should be the same before and after migration because we
        changed their names only.
        """

        data_list = [
            ("floating_ips", {'address': '10.12.14.16', 'deleted': 0}),
            ("instance_info_caches", {'instance_uuid': 'm185-uuid1'}),
            ('instance_type_projects', {'instance_type_id': 1,
                                        'project_id': '116', 'deleted': 0}),
            ('instance_types', {'flavorid': "flavorid_12", 'deleted': 0,
                                'memory_mb': 64, 'vcpus': 10, 'swap': 100}),
            ('instance_types', {'name': "name_123", 'deleted': 0,
                                'memory_mb': 128, 'vcpus': 11, 'swap': 300}),
            ('key_pairs', {'user_id': 1, 'name': "name_qwer", 'deleted': 0}),
            ('networks', {'vlan': '123', 'deleted': 0}),
            ('task_log', {'task_name': 'task_123', 'host': 'localhost',
                          'period_beginning': datetime.datetime(2013, 2, 11),
                          'period_ending': datetime.datetime(2015, 1, 1),
                          'state': 'state_1', 'message': 'msg_1'}),
            ('virtual_interfaces', {'address': '192.168.0.0'})
        ]

        for table_name, data in data_list:
            table = db_utils.get_table(engine, table_name)
            if not check:
                table.insert().values(data).execute()
            else:
                # we replace values for some columns because they don't
                # belong to unique constraint
                if table_name == "instance_types":
                    for key in ("memory_mb", "vcpus", "swap"):
                        data[key] = data[key] * 2
                if table_name == "task_log":
                    data["message"] = 'msg_2'
                    data["state"] = 'state_2'

                self.assertRaises(sqlalchemy.exc.IntegrityError,
                                  table.insert().execute, data)

    def _pre_upgrade_185(self, engine):
        fake_instances = [dict(uuid='m185-uuid1')]
        instances = db_utils.get_table(engine, 'instances')
        engine.execute(instances.insert(), fake_instances)
        self._unique_constraint_check_migrate_185(engine, False)

    def check_185(self, engine):
        self._unique_constraint_check_migrate_185(engine)

    def _post_downgrade_185(self, engine):
        self._unique_constraint_check_migrate_185(engine)

    def _pre_upgrade_186(self, engine):
        self.mig186_fake_instances = [
            dict(uuid='mig186_uuid-1', image_ref='fake_image_1',
                 root_device_name='/dev/vda'),
            dict(uuid='mig186_uuid-2', image_ref='',
                 root_device_name='vda'),
            dict(uuid='mig186_uuid-3', image_ref='fake_image_2',
                 root_device_name='/dev/vda'),
        ]

        self.mig186_fake_bdms = [
            # Instance 1 - image, volume and swap
            dict(instance_uuid='mig186_uuid-1', device_name='/dev/vdc',
                 volume_id='fake_volume_1'),
            dict(instance_uuid='mig186_uuid-1', device_name='/dev/vdb',
                 virtual_name='swap'),
            # Instance 2 - no image. snapshot and volume
            dict(instance_uuid='mig186_uuid-2', device_name='/dev/vda',
                 snapshot_id='fake_snap_1', volume_id='fake_volume_2'),
            dict(instance_uuid='mig186_uuid-2', device_name='/dev/vdc',
                 volume_id='fake_volume_3'),
            # Instance 3 - ephemerals and swap
            dict(instance_uuid='mig186_uuid-3', device_name='/dev/vdc',
                 virtual_name='ephemeral0'),
            dict(instance_uuid='mig186_uuid-3', device_name='/dev/vdd',
                 virtual_name='ephemeral1'),
            dict(instance_uuid='mig186_uuid-3', device_name='/dev/vdb',
                 virtual_name='swap'),
        ]

        instances = db_utils.get_table(engine, 'instances')
        block_device = db_utils.get_table(engine, 'block_device_mapping')
        engine.execute(instances.insert(), self.mig186_fake_instances)
        for fake_bdm in self.mig186_fake_bdms:
            engine.execute(block_device.insert(), fake_bdm)

        return self.mig186_fake_instances, self.mig186_fake_bdms

    def _check_186(self, engine, data):
        block_device = db_utils.get_table(engine, 'block_device_mapping')

        instance_qs = []

        for instance in ('mig186_uuid-1', 'mig186_uuid-2', 'mig186_uuid-3'):
            q = block_device.select().where(
                block_device.c.instance_uuid == instance).order_by(
                block_device.c.id.asc()
            )
            instance_qs.append(q)

        bdm_1s, bdm_2s, bdm_3s = (
            [bdm for bdm in q.execute()]
            for q in instance_qs
        )

        self.assertEqual(len(bdm_1s), 3)
        self.assertEqual(len(bdm_2s), 2)
        self.assertEqual(len(bdm_3s), 4)

        # Instance 1
        self.assertEqual(bdm_1s[0].source_type, 'volume')
        self.assertEqual(bdm_1s[0].destination_type, 'volume')
        self.assertEqual(bdm_1s[0].volume_id, 'fake_volume_1')
        self.assertEqual(bdm_1s[0].device_type, 'disk')
        self.assertEqual(bdm_1s[0].boot_index, -1)
        self.assertEqual(bdm_1s[0].device_name, '/dev/vdc')

        self.assertEqual(bdm_1s[1].source_type, 'blank')
        self.assertEqual(bdm_1s[1].guest_format, 'swap')
        self.assertEqual(bdm_1s[1].destination_type, 'local')
        self.assertEqual(bdm_1s[1].device_type, 'disk')
        self.assertEqual(bdm_1s[1].boot_index, -1)
        self.assertEqual(bdm_1s[1].device_name, '/dev/vdb')

        self.assertEqual(bdm_1s[2].source_type, 'image')
        self.assertEqual(bdm_1s[2].destination_type, 'local')
        self.assertEqual(bdm_1s[2].device_type, 'disk')
        self.assertEqual(bdm_1s[2].image_id, 'fake_image_1')
        self.assertEqual(bdm_1s[2].boot_index, 0)

        # Instance 2
        self.assertEqual(bdm_2s[0].source_type, 'snapshot')
        self.assertEqual(bdm_2s[0].destination_type, 'volume')
        self.assertEqual(bdm_2s[0].snapshot_id, 'fake_snap_1')
        self.assertEqual(bdm_2s[0].volume_id, 'fake_volume_2')
        self.assertEqual(bdm_2s[0].device_type, 'disk')
        self.assertEqual(bdm_2s[0].boot_index, 0)
        self.assertEqual(bdm_2s[0].device_name, '/dev/vda')

        self.assertEqual(bdm_2s[1].source_type, 'volume')
        self.assertEqual(bdm_2s[1].destination_type, 'volume')
        self.assertEqual(bdm_2s[1].volume_id, 'fake_volume_3')
        self.assertEqual(bdm_2s[1].device_type, 'disk')
        self.assertEqual(bdm_2s[1].boot_index, -1)
        self.assertEqual(bdm_2s[1].device_name, '/dev/vdc')

        # Instance 3
        self.assertEqual(bdm_3s[0].source_type, 'blank')
        self.assertEqual(bdm_3s[0].destination_type, 'local')
        self.assertEqual(bdm_3s[0].device_type, 'disk')
        self.assertEqual(bdm_3s[0].boot_index, -1)
        self.assertEqual(bdm_3s[0].device_name, '/dev/vdc')

        self.assertEqual(bdm_3s[1].source_type, 'blank')
        self.assertEqual(bdm_3s[1].destination_type, 'local')
        self.assertEqual(bdm_3s[1].device_type, 'disk')
        self.assertEqual(bdm_3s[1].boot_index, -1)
        self.assertEqual(bdm_3s[1].device_name, '/dev/vdd')

        self.assertEqual(bdm_3s[2].source_type, 'blank')
        self.assertEqual(bdm_3s[2].guest_format, 'swap')
        self.assertEqual(bdm_3s[2].destination_type, 'local')
        self.assertEqual(bdm_3s[2].device_type, 'disk')
        self.assertEqual(bdm_3s[2].boot_index, -1)
        self.assertEqual(bdm_3s[2].device_name, '/dev/vdb')

        self.assertEqual(bdm_3s[3].source_type, 'image')
        self.assertEqual(bdm_3s[3].destination_type, 'local')
        self.assertEqual(bdm_3s[3].device_type, 'disk')
        self.assertEqual(bdm_3s[3].image_id, 'fake_image_2')
        self.assertEqual(bdm_3s[3].boot_index, 0)

    def _post_downgrade_186(self, engine):
        block_device = db_utils.get_table(engine, 'block_device_mapping')

        q = block_device.select().where(
            sqlalchemy.or_(
                block_device.c.instance_uuid == 'mig186_uuid-1',
                block_device.c.instance_uuid == 'mig186_uuid-2',
                block_device.c.instance_uuid == 'mig186_uuid-3'))\
            .order_by(block_device.c.device_name.asc(),
                      block_device.c.instance_uuid.asc())

        expected_bdms = sorted(self.mig186_fake_bdms,
                               key=lambda x:
                                    x['device_name'] + x['instance_uuid'])
        got_bdms = [bdm for bdm in q.execute()]

        self.assertEqual(len(expected_bdms), len(got_bdms))
        for expected, got in zip(expected_bdms, got_bdms):
            self.assertThat(expected, matchers.IsSubDictOf(dict(got)))

    # addition of the vm instance groups
    def _check_no_group_instance_tables(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'instance_groups')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'instance_group_member')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'instance_group_policy')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'instance_group_metadata')

    def _check_group_instance_groups(self, engine):
        groups = db_utils.get_table(engine, 'instance_groups')
        uuid4 = uuidutils.generate_uuid()
        uuid5 = uuidutils.generate_uuid()
        group_data = [
            {'id': 4, 'deleted': 4, 'uuid': uuid4},
            {'id': 5, 'deleted': 0, 'uuid': uuid5},
        ]
        engine.execute(groups.insert(), group_data)
        group = groups.select(groups.c.id == 4).execute().first()
        self.assertEqual(4, group.deleted)
        group = groups.select(groups.c.id == 5).execute().first()
        self.assertEqual(0, group.deleted)

    def _pre_upgrade_187(self, engine):
        self._check_no_group_instance_tables(engine)

    def _check_187(self, engine, data):
        self._check_group_instance_groups(engine)
        tables = ['instance_group_policy', 'instance_group_metadata',
                  'instance_group_member']
        for table in tables:
            db_utils.get_table(engine, table)

    def _post_downgrade_187(self, engine):
        # check that groups does not exist
        self._check_no_group_instance_tables(engine)

    def _pre_upgrade_188(self, engine):
        host1 = 'compute-host1'
        host2 = 'compute-host2'
        services_data = [
            {'id': 1, 'host': host1, 'binary': 'nova-compute',
             'report_count': 0, 'topic': 'compute', 'deleted': 0},
            {'id': 2, 'host': host1, 'binary': 'nova-compute',
             'report_count': 0, 'topic': 'compute', 'deleted': 1}
            ]

        services = db_utils.get_table(engine, 'services')
        engine.execute(services.insert(), services_data)

        return dict(services=services_data)

    def _check_188(self, engine, data):
        services = db_utils.get_table(engine, 'services')
        rows = services.select().execute().fetchall()
        self.assertIsNone(rows[0]['disabled_reason'])

    def _post_downgrade_188(self, engine):
        services = db_utils.get_table(engine, 'services')
        rows = services.select().execute().fetchall()
        self.assertNotIn('disabled_reason', rows[0])

    def _pre_upgrade_189(self, engine):
        cells = db_utils.get_table(engine, 'cells')
        data = [
                {'name': 'name_123', 'deleted': 0},
                {'name': 'name_123', 'deleted': 0},
                {'name': 'name_345', 'deleted': 0},
        ]
        for item in data:
            cells.insert().values(item).execute()
        return data

    def _check_189(self, engine, data):
        cells = db_utils.get_table(engine, 'cells')

        def get_(name, deleted):
            deleted_value = 0 if not deleted else cells.c.id
            return cells.select().\
                   where(cells.c.name == name).\
                   where(cells.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_('name_123', False)))
        self.assertEqual(1, len(get_('name_123', True)))
        self.assertEqual(1, len(get_('name_345', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          cells.insert().execute,
                          {'name': 'name_123', 'deleted': 0})

    def _pre_upgrade_190(self, engine):
        security_groups = db_utils.get_table(engine, 'security_groups')
        data = [
            {'name': 'group1', 'project_id': 'fake', 'deleted': 0},
            {'name': 'group1', 'project_id': 'fake', 'deleted': 0},
            {'name': 'group2', 'project_id': 'fake', 'deleted': 0},
        ]

        for item in data:
            security_groups.insert().values(item).execute()

    def _check_190(self, engine, data):
        security_groups = db_utils.get_table(engine, 'security_groups')

        def get_(name, project_id, deleted):
            deleted_value = 0 if not deleted else security_groups.c.id
            return security_groups.select().\
                        where(security_groups.c.name == name).\
                        where(security_groups.c.project_id == project_id).\
                        where(security_groups.c.deleted == deleted_value).\
                        execute().\
                        fetchall()

        self.assertEqual(1, len(get_('group1', 'fake', False)))
        self.assertEqual(1, len(get_('group1', 'fake', True)))
        self.assertEqual(1, len(get_('group2', 'fake', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          security_groups.insert().execute,
                          dict(name='group2', project_id='fake', deleted=0))

    def _pre_upgrade_191(self, engine):
        quotas = db_utils.get_table(engine, 'quotas')
        data = [
            {'project_id': 'project1', 'resource': 'resource1', 'deleted': 0},
            {'project_id': 'project1', 'resource': 'resource1', 'deleted': 0},
            {'project_id': 'project2', 'resource': 'resource1', 'deleted': 0},
        ]
        for item in data:
            quotas.insert().values(item).execute()
        return data

    def _check_191(self, engine, data):
        quotas = db_utils.get_table(engine, 'quotas')

        def get_(project_id, deleted):
            deleted_value = 0 if not deleted else quotas.c.id
            return quotas.select().\
                   where(quotas.c.project_id == project_id).\
                   where(quotas.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_('project1', False)))
        self.assertEqual(1, len(get_('project1', True)))
        self.assertEqual(1, len(get_('project2', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          quotas.insert().execute,
                          {'project_id': 'project1', 'resource': 'resource1',
                           'deleted': 0})

    def _check_192(self, engine, data):
        virtual_if = db_utils.get_table(engine, 'virtual_interfaces')
        values = {'address': 'address0', 'deleted': 0}
        virtual_if.insert().values(values).execute()
        values['deleted'] = 1
        virtual_if.insert().values(values).execute()
        values['deleted'] = 0
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          virtual_if.insert().execute,
                          values)

    def _post_downgrade_192(self, engine):
        virtual_if = db_utils.get_table(engine, 'virtual_interfaces')
        deleted = virtual_if.select().\
                  where(virtual_if.c.deleted != 0).\
                  execute().fetchall()
        self.assertEqual([], deleted)
        values = {'address': 'address1'}
        virtual_if.insert().values(values).execute()
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          virtual_if.insert().execute,
                          values)

    def _check_193(self, engine, data):
        tables = set(engine.table_names())
        dropped_tables = set([
            'sm_volume',
            'sm_backend_config',
            'sm_flavors',
            'virtual_storage_arrays',
            'volume_metadata',
            'volume_type_extra_specs',
            'volume_types',
            'shadow_sm_volume',
            'shadow_sm_backend_config',
            'shadow_sm_flavors',
            'shadow_virtual_storage_arrays',
            'shadow_volume_metadata',
            'shadow_volume_type_extra_specs',
            'shadow_volume_types'])
        check = bool(tables & dropped_tables)
        self.assertFalse(check)

    def _post_downgrade_193(self, engine):
        tables = set(engine.table_names())
        dropped_tables = set([
            'sm_volume',
            'sm_backend_config',
            'sm_flavors',
            'virtual_storage_arrays',
            'volume_metadata',
            'volume_type_extra_specs',
            'volume_types',
            'shadow_sm_volume',
            'shadow_sm_backend_config',
            'shadow_sm_flavors',
            'shadow_virtual_storage_arrays',
            'shadow_volume_metadata',
            'shadow_volume_type_extra_specs',
            'shadow_volume_types'])
        check = tables & dropped_tables
        self.assertEqual(check, dropped_tables)

    def _pre_upgrade_194(self, engine):
        test_data = {
            # table_name: ((index_name_1, (*columns)), ...)
            "certificates": (
                ("certificates_project_id_deleted_idx",
                    ["project_id", "deleted"]),
                ("certificates_user_id_deleted_idx", ["user_id", "deleted"]),
            ),
            "instances": (
                ("instances_host_deleted_idx", ["host", "deleted"]),
                ("instances_uuid_deleted_idx", ["uuid", "deleted"]),
                ("instances_host_node_deleted_idx",
                    ["host", "node", "deleted"]),
            ),
            "iscsi_targets": (
                ("iscsi_targets_host_volume_id_deleted_idx",
                    ["host", "volume_id", "deleted"]),
            ),
            "networks": (
                ("networks_bridge_deleted_idx", ["bridge", "deleted"]),
                ("networks_project_id_deleted_idx", ["project_id", "deleted"]),
                ("networks_uuid_project_id_deleted_idx",
                    ["uuid", "project_id", "deleted"]),
                ("networks_vlan_deleted_idx", ["vlan", "deleted"]),
            ),
            "fixed_ips": (
                ("fixed_ips_network_id_host_deleted_idx",
                    ["network_id", "host", "deleted"]),
                ("fixed_ips_address_reserved_network_id_deleted_idx",
                    ["address", "reserved", "network_id", "deleted"]),
                ("fixed_ips_deleted_allocated_idx",
                    ["address", "deleted", "allocated"]),
            ),
            "floating_ips": (
                ("floating_ips_pool_deleted_fixed_ip_id_project_id_idx",
                    ["pool", "deleted", "fixed_ip_id", "project_id"]),
            ),
            "instance_faults": (
                ("instance_faults_instance_uuid_deleted_created_at_idx",
                 ["instance_uuid", "deleted", "created_at"]),
            ),
        }

        return test_data

    def _check_194(self, engine, data):
        if engine.name == 'sqlite':
            return

        for table_name, indexes in data.iteritems():
            meta = sqlalchemy.MetaData()
            meta.bind = engine
            table = sqlalchemy.Table(table_name, meta, autoload=True)

            index_data = [(idx.name, idx.columns.keys())
                          for idx in table.indexes]

            for name, columns in indexes:
                if engine.name == "postgresql":
                    # we can not get correct order of columns in index
                    # definition to postgresql using sqlalchemy. So we sortind
                    # columns list before compare
                    # bug http://www.sqlalchemy.org/trac/ticket/2767
                    self.assertIn(
                        (name, sorted(columns)),
                        ([(idx[0], sorted(idx[1])) for idx in index_data])
                    )
                else:
                    self.assertIn((name, columns), index_data)

    def _post_downgrade_194(self, engine):
        if engine.name == 'sqlite':
            return

        for table_name, indexes in self._pre_upgrade_194(engine).iteritems():
            meta = sqlalchemy.MetaData()
            meta.bind = engine
            table = sqlalchemy.Table(table_name, meta, autoload=True)

            index_data = [(idx.name, idx.columns.keys())
                          for idx in table.indexes]

            for name, columns in indexes:
                if engine.name == "postgresql":
                    # we can not get correct order of columns in index
                    # definition to postgresql using sqlalchemy. So we sortind
                    # columns list before compare
                    # bug http://www.sqlalchemy.org/trac/ticket/2767
                    self.assertNotIn(
                        (name, sorted(columns)),
                        ([(idx[0], sorted(idx[1])) for idx in index_data])
                    )
                else:
                    self.assertNotIn((name, columns), index_data)

    def _pre_upgrade_195(self, engine):
        fixed_ips = db_utils.get_table(engine, 'fixed_ips')
        data = [
            {'address': '128.128.128.128', 'deleted': 0},
            {'address': '128.128.128.128', 'deleted': 0},
            {'address': '128.128.128.129', 'deleted': 0},
        ]

        for item in data:
            fixed_ips.insert().values(item).execute()
        return data

    def _check_195(self, engine, data):
        fixed_ips = db_utils.get_table(engine, 'fixed_ips')

        def get_(address, deleted):
            deleted_value = 0 if not deleted else fixed_ips.c.id
            return fixed_ips.select()\
                            .where(fixed_ips.c.address == address)\
                            .where(fixed_ips.c.deleted == deleted_value)\
                            .execute()\
                            .fetchall()

        self.assertEqual(1, len(get_('128.128.128.128', False)))
        self.assertEqual(1, len(get_('128.128.128.128', True)))
        self.assertEqual(1, len(get_('128.128.128.129', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          fixed_ips.insert().execute,
                          dict(address='128.128.128.129', deleted=0))

    def _pre_upgrade_196(self, engine):
        services = db_utils.get_table(engine, 'services')
        data = [
            {'id': 6, 'host': 'host1', 'binary': 'binary1', 'topic': 'topic3',
             'report_count': 5, 'deleted': 0},
            {'id': 7, 'host': 'host1', 'binary': 'binary1', 'topic': 'topic4',
             'report_count': 5, 'deleted': 0},
            {'id': 8, 'host': 'host2', 'binary': 'binary7', 'topic': 'topic2',
             'report_count': 5, 'deleted': 0},
            {'id': 9, 'host': 'host2', 'binary': 'binary8', 'topic': 'topic2',
             'report_count': 5, 'deleted': 0},
        ]
        for item in data:
            services.insert().values(item).execute()
        return data

    def _check_196(self, engine, data):
        services = db_utils.get_table(engine, 'services')

        def get_(host, deleted):
            deleted_value = 0 if not deleted else services.c.id
            return services.select().\
                   where(services.c.host == host).\
                   where(services.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_('host1', False)))
        self.assertEqual(1, len(get_('host1', True)))
        self.assertEqual(1, len(get_('host2', False)))
        self.assertEqual(1, len(get_('host2', True)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          services.insert().execute,
                          {'id': 10, 'host': 'host1', 'binary': 'binary1',
                           'report_count': 5, 'topic': 'topic0', 'deleted': 0})
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          services.insert().execute,
                          {'id': 11, 'host': 'host2', 'binary': 'binary0',
                           'report_count': 5, 'topic': 'topic2', 'deleted': 0})

    def _pre_upgrade_197(self, engine):
        abuilds = db_utils.get_table(engine, 'agent_builds')
        data = [
            {'hypervisor': 'hyper1', 'os': 'os1', 'architecture': 'arch1',
             'deleted': 0},
            {'hypervisor': 'hyper1', 'os': 'os1', 'architecture': 'arch1',
             'deleted': 0},
            {'hypervisor': 'hyper2', 'os': 'os1', 'architecture': 'arch1',
             'deleted': 0},
        ]
        for item in data:
            abuilds.insert().values(item).execute()
        return data

    def _check_197(self, engine, data):
        abuilds = db_utils.get_table(engine, 'agent_builds')

        def get_(hypervisor, deleted):
            deleted_value = 0 if not deleted else abuilds.c.id
            return abuilds.select().\
                   where(abuilds.c.hypervisor == hypervisor).\
                   where(abuilds.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_('hyper1', False)))
        self.assertEqual(1, len(get_('hyper1', True)))
        self.assertEqual(1, len(get_('hyper2', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          abuilds.insert().execute,
                          {'hypervisor': 'hyper2', 'os': 'os1',
                           'architecture': 'arch1', 'deleted': 0})

    def _pre_upgrade_198(self, engine):
        table = db_utils.get_table(engine, 'console_pools')
        data = [
            {'host': 'localhost', 'console_type': 'type_1',
             'compute_host': '192.168.122.8', 'deleted': 0},
            {'host': 'localhost', 'console_type': 'type_1',
             'compute_host': '192.168.122.8', 'deleted': 0},
            {'host': 'localhost', 'console_type': 'type_2',
             'compute_host': '192.168.122.8', 'deleted': 0},
        ]

        for item in data:
            table.insert().values(item).execute()
        return data

    def _check_198(self, engine, data):
        table = db_utils.get_table(engine, 'console_pools')

        def get_(host, console_type, compute_host, deleted):
            deleted_value = 0 if not deleted else table.c.id
            return table.select()\
                        .where(table.c.host == host)\
                        .where(table.c.console_type == console_type)\
                        .where(table.c.compute_host == compute_host)\
                        .where(table.c.deleted == deleted_value)\
                        .execute()\
                        .fetchall()

        self.assertEqual(
            1, len(get_('localhost', 'type_1', '192.168.122.8', False)))
        self.assertEqual(
            1, len(get_('localhost', 'type_1', '192.168.122.8', True)))
        self.assertEqual(
            1, len(get_('localhost', 'type_2', '192.168.122.8', False)))
        self.assertRaises(
            sqlalchemy.exc.IntegrityError,
            table.insert().execute,
            {'host': 'localhost', 'console_type': 'type_2',
             'compute_host': '192.168.122.8', 'deleted': 0},
        )

    def _pre_upgrade_199(self, engine):
        fake_aggregates = [{'id': 5, 'name': 'name1'},
                            {'id': 6, 'name': 'name2'}]
        aggregates = db_utils.get_table(engine, 'aggregates')
        engine.execute(aggregates.insert(), fake_aggregates)

        fake_metadata = [{'aggregate_id': 5, 'key': 'availability_zone',
                           'value': 'custom_az'},
                          {'aggregate_id': 6, 'key': 'availability_zone',
                           'value': 'custom_az'}]
        metadata = db_utils.get_table(engine, 'aggregate_metadata')
        engine.execute(metadata.insert(), fake_metadata)

        ahosts = db_utils.get_table(engine, 'aggregate_hosts')
        data = [
                {'host': 'host1', 'aggregate_id': 5, 'deleted': 0},
                {'host': 'host1', 'aggregate_id': 5, 'deleted': 0},
                {'host': 'host2', 'aggregate_id': 6, 'deleted': 0},
        ]
        for item in data:
            ahosts.insert().values(item).execute()
        return data

    def _check_199(self, engine, data):
        ahosts = db_utils.get_table(engine, 'aggregate_hosts')

        def get_(host, deleted):
            deleted_value = 0 if not deleted else ahosts.c.id
            return ahosts.select().\
                   where(ahosts.c.host == host).\
                   where(ahosts.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_('host1', False)))
        self.assertEqual(1, len(get_('host1', True)))
        self.assertEqual(1, len(get_('host2', False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          ahosts.insert().execute,
                          {'host': 'host2', 'aggregate_id': 6,
                           'deleted': 0})

    def _pre_upgrade_200(self, engine):
        cells = db_utils.get_table(engine, 'cells')
        shadow_cells = db_utils.get_table(engine, 'shadow_cells')
        cells.delete().execute()
        shadow_cells.delete().execute()
        data = [
            {
                'name': 'cell_transport_123',
                'deleted': 0,
                'username': 'user_123',
                'password': 'pass_123',
                'rpc_host': 'host_123',
                'rpc_port': 123,
                'rpc_virtual_host': 'virtual_123',
            },
            {
                'name': 'cell_transport_456',
                'deleted': 0,
                'username': 'user_456',
                'password': 'pass_456',
                'rpc_host': 'ffff::456',
                'rpc_port': 456,
                'rpc_virtual_host': 'virtual_456',
            },
        ]
        for item in data:
            cells.insert().values(item).execute()
            shadow_cells.insert().values(item).execute()
        return data

    def _check_200(self, engine, data):
        cells = db_utils.get_table(engine, 'cells')
        shadow_cells = db_utils.get_table(engine, 'shadow_cells')

        def get_(table, name):
            return table.select().\
                where(cells.c.name == name).\
                execute().\
                first()

        for table in (cells, shadow_cells):
            cell_123 = get_(cells, 'cell_transport_123')
            self.assertNotIn('username', cell_123)
            self.assertNotIn('password', cell_123)
            self.assertNotIn('rpc_host', cell_123)
            self.assertNotIn('rpc_port', cell_123)
            self.assertNotIn('rpc_virtual_host', cell_123)
            self.assertEqual('rabbit://user_123:pass_123@host_123:123/'
                             'virtual_123', cell_123['transport_url'])

            cell_456 = get_(cells, 'cell_transport_456')
            self.assertNotIn('username', cell_456)
            self.assertNotIn('password', cell_456)
            self.assertNotIn('rpc_host', cell_456)
            self.assertNotIn('rpc_port', cell_456)
            self.assertNotIn('rpc_virtual_host', cell_456)
            self.assertEqual('rabbit://user_456:pass_456@[ffff::456]:456/'
                             'virtual_456', cell_456['transport_url'])

        # Verify that the unique constraint still exists
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          cells.insert().execute,
                          {'name': 'cell_transport_123', 'deleted': 0})

    def _post_downgrade_200(self, engine):
        cells = db_utils.get_table(engine, 'cells')
        shadow_cells = db_utils.get_table(engine, 'shadow_cells')

        def get_(table, name):
            return table.select().\
                where(cells.c.name == name).\
                execute().\
                first()

        for table in (cells, shadow_cells):
            cell_123 = get_(cells, 'cell_transport_123')
            self.assertNotIn('transport_url', cell_123)
            self.assertEqual('user_123', cell_123['username'])
            self.assertEqual('pass_123', cell_123['password'])
            self.assertEqual('host_123', cell_123['rpc_host'])
            self.assertEqual(123, cell_123['rpc_port'])
            self.assertEqual('virtual_123', cell_123['rpc_virtual_host'])

            cell_456 = get_(cells, 'cell_transport_456')
            self.assertNotIn('transport_url', cell_456)
            self.assertEqual('user_456', cell_456['username'])
            self.assertEqual('pass_456', cell_456['password'])
            self.assertEqual('ffff::456', cell_456['rpc_host'])
            self.assertEqual(456, cell_456['rpc_port'])
            self.assertEqual('virtual_456', cell_456['rpc_virtual_host'])

        # Verify that the unique constraint still exists
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          cells.insert().execute,
                          {'name': 'cell_transport_123', 'deleted': 0})

    def _pre_upgrade_201(self, engine):
        data = {
            # table_name: ((idx_1, (c1, c2,)), (idx2, (c1, c2,)), ...)
            'agent_builds': (
                ('agent_builds_hypervisor_os_arch_idx',
                 ('hypervisor', 'os', 'architecture'),),
            ),
            'aggregate_metadata': (
                ('aggregate_metadata_key_idx', ('key',),),
            ),
            'block_device_mapping': (
                ('block_device_mapping_instance_uuid_idx',
                 ('instance_uuid',),),
                ('block_device_mapping_instance_uuid_device_name_idx',
                 ('instance_uuid', 'device_name',),),
                ('block_device_mapping_instance_uuid_volume_id_idx',
                 ('instance_uuid', 'volume_id',)),
                ('snapshot_id', ('snapshot_id',)),
                ('volume_id', ('volume_id',)),
            ),
            'bw_usage_cache': (
                ('bw_usage_cache_uuid_start_period_idx',
                 ('uuid', 'start_period',)),
            ),
            'certificates': (
                ('certificates_project_id_deleted_idx',
                 ('project_id', 'deleted',)),
                ('certificates_user_id_deleted_idx', ('user_id', 'deleted',)),
            ),
            'compute_node_stats': (
                ('ix_compute_node_stats_compute_node_id',
                 ('compute_node_id',)),
            ),
            'consoles': (
                ('consoles_instance_uuid_idx', ('instance_uuid',)),
            ),
            'dns_domains': (
                ('dns_domains_domain_deleted_idx', ('domain', 'deleted',)),
            ),
            'fixed_ips': (
                ('address', ('address',)),
                ('fixed_ips_host_idx', ('host',)),
                ('fixed_ips_network_id_host_deleted_idx',
                 ('network_id', 'host', 'deleted',)),
                ('fixed_ips_address_reserved_network_id_deleted_idx',
                 ('address', 'reserved', 'network_id', 'deleted',)),
                ('network_id', ('network_id',)),
                ('fixed_ips_virtual_interface_id_fkey',
                 ('virtual_interface_id',)),
                ('fixed_ips_instance_uuid_fkey', ('instance_uuid',)),
            ),
            'floating_ips': (
                ('fixed_ip_id', ('fixed_ip_id',)),
                ('floating_ips_host_idx', ('host',)),
                ('floating_ips_project_id_idx', ('project_id',)),
                ('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
                 ('pool', 'deleted', 'fixed_ip_id', 'project_id',)),
            ),
            'instance_group_member': (
                ('instance_group_member_instance_idx', ('instance_id',)),
            ),
            'instance_group_metadata': (
                ('instance_instance_group_metadata_key_idx', ('key',)),
            ),
            'instance_group_policy': (
                ('instance_instance_group_policy_policy_idx', ('policy',)),
            ),
            'instance_faults': (
                ('instance_faults_instance_uuid_deleted_created_at_idx',
                 ('instance_uuid', 'deleted', 'created_at',)),
            ),
            'instance_id_mappings': (
                ('ix_instance_id_mappings_uuid', ('uuid',)),
            ),
            'instance_type_extra_specs': (
                ('instance_type_extra_specs_instance_type_id_key_idx',
                 ('instance_type_id', 'key',)),
            ),
            'instance_system_metadata': (
                ('instance_uuid', ('instance_uuid',)),
            ),
            'instance_metadata': (
                ('instance_metadata_instance_uuid_idx', ('instance_uuid',)),
            ),
            'instance_type_projects': (
                ('instance_type_id', ('instance_type_id',)),
            ),
            'iscsi_targets': (
                ('iscsi_targets_host_idx', ('host',)),
                ('iscsi_targets_volume_id_fkey', ('volume_id',)),
                ('iscsi_targets_host_volume_id_deleted_idx',
                 ('host', 'volume_id', 'deleted',)),
            ),
            'networks': (
                ('networks_bridge_deleted_idx', ('bridge', 'deleted',)),
                ('networks_host_idx', ('host',)),
                ('networks_project_id_deleted_idx', ('project_id',
                                                     'deleted',)),
                ('networks_uuid_project_id_deleted_idx', ('uuid', 'project_id',
                                                          'deleted',)),
                ('networks_vlan_deleted_idx', ('vlan', 'deleted',)),
                ('networks_cidr_v6_idx', ('cidr_v6',)),
            ),
            'reservations': (
                ('ix_reservations_project_id', ('project_id',)),
                ('usage_id', ('usage_id',)),
            ),
            'security_group_instance_association': (
                ('security_group_instance_association_instance_uuid_idx',
                 ('instance_uuid',)),
            ),
            'quota_classes': (
                ('ix_quota_classes_class_name', ('class_name',)),
            ),
            'quota_usages': (
                ('ix_quota_usages_project_id', ('project_id',)),
            ),
            'virtual_interfaces': (
                ('virtual_interfaces_network_id_idx', ('network_id',)),
                ('virtual_interfaces_instance_uuid_fkey', ('instance_uuid',)),
            ),
            'volumes': (
                ('volumes_instance_uuid_idx', ('instance_uuid',)),
            ),
            'task_log': (
                ('ix_task_log_period_beginning', ('period_beginning',)),
                ('ix_task_log_host', ('host',)),
                ('ix_task_log_period_ending', ('period_ending',)),
            ),
        }
        return data

    def _check_201(self, engine, data):
        if engine.name != 'sqlite':
            return

        meta = sqlalchemy.MetaData()
        meta.bind = engine

        for table_name, indexes in data.iteritems():
            table = sqlalchemy.Table(table_name, meta, autoload=True)
            loaded_indexes = [(i.name, tuple(i.columns.keys()))
                              for i in table.indexes]

            for index in indexes:
                self.assertIn(index, loaded_indexes)

    def _post_downgrade_201(self, engine):
        if engine.name != 'sqlite':
            return

        data = self._pre_upgrade_201(engine)
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        for table_name, indexes in data.iteritems():
            table = sqlalchemy.Table(table_name, meta, autoload=True)
            loaded_indexes = [(i.name, tuple(i.columns.keys()))
                              for i in table.indexes]

            for index in indexes:
                self.assertNotIn(index, loaded_indexes)

    def _pre_upgrade_202(self, engine):
        fake_types = [
                {'id': 35, 'name': 'type1', 'memory_mb': 128, 'vcpus': 1,
                 'root_gb': 10, 'ephemeral_gb': 0, 'flavorid': "1", 'swap': 0,
                 'rxtx_factor': 1.0, 'vcpu_weight': 1, 'disabled': False,
                 'is_public': True},
                {'id': 36, 'name': 'type2', 'memory_mb': 512, 'vcpus': 1,
                 'root_gb': 10, 'ephemeral_gb': 5, 'flavorid': "2", 'swap': 0,
                 'rxtx_factor': 1.5, 'vcpu_weight': 2, 'disabled': False,
                 'is_public': True},
            ]
        instance_types = db_utils.get_table(engine, 'instance_types')
        engine.execute(instance_types.insert(), fake_types)
        specs = db_utils.get_table(engine, 'instance_type_extra_specs')
        data = [
                {'instance_type_id': 35, 'key': 'key1', 'deleted': 0},
                {'instance_type_id': 35, 'key': 'key1', 'deleted': 0},
                {'instance_type_id': 36, 'key': 'key1', 'deleted': 0},
        ]
        for item in data:
            specs.insert().values(item).execute()
        return data

    def _check_202(self, engine, data):
        specs = db_utils.get_table(engine, 'instance_type_extra_specs')

        def get_(typeid, deleted):
            deleted_value = 0 if not deleted else specs.c.id
            return specs.select().\
                   where(specs.c.instance_type_id == typeid).\
                   where(specs.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_(35, False)))
        self.assertEqual(1, len(get_(35, True)))
        self.assertEqual(1, len(get_(36, False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          specs.insert().execute,
                          {'instance_type_id': 35, 'key': 'key1',
                           'deleted': 0})

    # migration 203 - make user quotas key and value
    def _pre_upgrade_203(self, engine):
        quota_usages = db_utils.get_table(engine, 'quota_usages')
        reservations = db_utils.get_table(engine, 'reservations')
        fake_quota_usages = {'id': 5,
                             'resource': 'instances',
                             'in_use': 1,
                             'reserved': 1}
        fake_reservations = {'id': 6,
                             'uuid': 'fake_reservationo_uuid',
                             'usage_id': 5,
                             'resource': 'instances',
                             'delta': 1,
                             'expire': timeutils.utcnow()}
        quota_usages.insert().execute(fake_quota_usages)
        reservations.insert().execute(fake_reservations)

    def _check_203(self, engine, data):
        project_user_quotas = db_utils.get_table(engine, 'project_user_quotas')
        fake_quotas = {'id': 4,
                       'project_id': 'fake_project',
                       'user_id': 'fake_user',
                       'resource': 'instances',
                       'hard_limit': 10}
        project_user_quotas.insert().execute(fake_quotas)
        quota_usages = db_utils.get_table(engine, 'quota_usages')
        reservations = db_utils.get_table(engine, 'reservations')
        # Get the record
        quota = project_user_quotas.select().execute().first()
        quota_usage = quota_usages.select().execute().first()
        reservation = reservations.select().execute().first()

        self.assertEqual(quota['id'], 4)
        self.assertEqual(quota['project_id'], 'fake_project')
        self.assertEqual(quota['user_id'], 'fake_user')
        self.assertEqual(quota['resource'], 'instances')
        self.assertEqual(quota['hard_limit'], 10)
        self.assertIsNone(quota_usage['user_id'])
        self.assertIsNone(reservation['user_id'])
        # Check indexes exist
        if engine.name == 'mysql' or engine.name == 'postgresql':
            data = {
                # table_name: ((idx_1, (c1, c2,)), (idx2, (c1, c2,)), ...)
                'quota_usages': (
                    ('ix_quota_usages_user_id_deleted',
                     sorted(('user_id', 'deleted'))),
                ),
                'reservations': (
                    ('ix_reservations_user_id_deleted',
                     sorted(('user_id', 'deleted'))),
                )
            }

            meta = sqlalchemy.MetaData()
            meta.bind = engine

            for table_name, indexes in data.iteritems():
                table = sqlalchemy.Table(table_name, meta, autoload=True)
                current_indexes = [(i.name, tuple(i.columns.keys()))
                                   for i in table.indexes]

                # we can not get correct order of columns in index
                # definition to postgresql using sqlalchemy. So we sort
                # columns list before compare
                # bug http://www.sqlalchemy.org/trac/ticket/2767
                current_indexes = (
                    [(idx[0], sorted(idx[1])) for idx in current_indexes]
                )
                for index in indexes:
                    self.assertIn(index, current_indexes)

    def _post_downgrade_203(self, engine):
        try:
            table_exist = True
            db_utils.get_table(engine, 'project_user_quotas')
        except Exception:
            table_exist = False
        quota_usages = db_utils.get_table(engine, 'quota_usages')
        reservations = db_utils.get_table(engine, 'reservations')

        # Get the record
        quota_usage = quota_usages.select().execute().first()
        reservation = reservations.select().execute().first()

        self.assertNotIn('user_id', quota_usage)
        self.assertNotIn('user_id', reservation)
        self.assertFalse(table_exist)
        # Check indexes are gone
        if engine.name == 'mysql' or engine.name == 'postgresql':
            data = {
                # table_name: ((idx_1, (c1, c2,)), (idx2, (c1, c2,)), ...)
                'quota_usages': (
                    ('ix_quota_usages_user_id_deleted',
                     sorted(('user_id', 'deleted'))),
                ),
                'reservations': (
                    ('ix_reservations_user_id_deleted',
                     sorted(('user_id', 'deleted'))),
                )
            }

            meta = sqlalchemy.MetaData()
            meta.bind = engine

            for table_name, indexes in data.iteritems():
                table = sqlalchemy.Table(table_name, meta, autoload=True)
                current_indexes = [(i.name, tuple(i.columns.keys()))
                           for i in table.indexes]

                # we can not get correct order of columns in index
                # definition to postgresql using sqlalchemy. So we sort
                # columns list before compare
                # bug http://www.sqlalchemy.org/trac/ticket/2767
                current_indexes = (
                    [(idx[0], sorted(idx[1])) for idx in current_indexes]
                )
                for index in indexes:
                    self.assertNotIn(index, current_indexes)

        # Check indexes are gone
        if engine.name == 'mysql' or engine.name == 'postgresql':
            data = {
                # table_name: ((idx_1, (c1, c2,)), (idx2, (c1, c2,)), ...)
                'quota_usages': (
                    ('ix_quota_usages_user_id_deleted',
                     ('user_id', 'deleted')),
                ),
                'reservations': (
                    ('ix_reservations_user_id_deleted',
                     ('user_id', 'deleted')),
                )
            }

            meta = sqlalchemy.MetaData()
            meta.bind = engine

            for table_name, indexes in data.iteritems():
                table = sqlalchemy.Table(table_name, meta, autoload=True)
                current_indexes = [(i.name, tuple(i.columns.keys()))
                           for i in table.indexes]
                for index in indexes:
                    self.assertNotIn(index, current_indexes)

    def _check_204(self, engine, data):
        if engine.name != 'sqlite':
            return

        meta = sqlalchemy.MetaData()
        meta.bind = engine
        reservations = sqlalchemy.Table('reservations', meta, autoload=True)

        index_data = [(idx.name, idx.columns.keys())
                      for idx in reservations.indexes]

        if engine.name == "postgresql":
            # we can not get correct order of columns in index
            # definition to postgresql using sqlalchemy. So we sort
            # columns list before compare
            # bug http://www.sqlalchemy.org/trac/ticket/2767
            self.assertIn(
                ('reservations_uuid_idx', sorted(['uuid'])),
                ([(idx[0], sorted(idx[1])) for idx in index_data])
            )
        else:
            self.assertIn(('reservations_uuid_idx', ['uuid']), index_data)

    def _pre_upgrade_205(self, engine):
        fake_instances = [dict(uuid='m205-uuid1', locked=True),
                          dict(uuid='m205-uuid2', locked=False)]
        for table_name in ['instances', 'shadow_instances']:
            table = db_utils.get_table(engine, table_name)
            engine.execute(table.insert(), fake_instances)

    def _check_205(self, engine, data):
        for table_name in ['instances', 'shadow_instances']:
            table = db_utils.get_table(engine, table_name)
            rows = table.select().\
                where(table.c.uuid.in_(['m205-uuid1', 'm205-uuid2'])).\
                order_by(table.c.uuid).execute().fetchall()
            self.assertEqual(rows[0]['locked_by'], 'admin')
            self.assertIsNone(rows[1]['locked_by'])

    def _post_downgrade_205(self, engine):
        for table_name in ['instances', 'shadow_instances']:
            table = db_utils.get_table(engine, table_name)
            rows = table.select().execute().fetchall()
            self.assertNotIn('locked_by', rows[0])

    def _pre_upgrade_206(self, engine):
        instances = db_utils.get_table(engine, 'instances')
        shadow_instances = db_utils.get_table(engine, 'shadow_instances')

        data = [
            {
                'id': 650,
                'deleted': 0,
            },
            {
                'id': 651,
                'deleted': 2,
            },
        ]
        for item in data:
            instances.insert().values(item).execute()
            shadow_instances.insert().values(item).execute()
        return data

    def _check_206(self, engine, data):
        self.assertColumnExists(engine, 'instances', 'cleaned')
        self.assertColumnExists(engine, 'shadow_instances', 'cleaned')
        self.assertIndexMembers(engine, 'instances',
                                'instances_host_deleted_cleaned_idx',
                                ['host', 'deleted', 'cleaned'])

        instances = db_utils.get_table(engine, 'instances')
        shadow_instances = db_utils.get_table(engine, 'shadow_instances')

        def get_(table, ident):
            return table.select().\
                where(table.c.id == ident).\
                execute().\
                first()

        for table in (instances, shadow_instances):
            id_1 = get_(instances, 650)
            self.assertEqual(0, id_1['deleted'])
            self.assertEqual(0, id_1['cleaned'])

            id_2 = get_(instances, 651)
            self.assertEqual(2, id_2['deleted'])
            self.assertEqual(1, id_2['cleaned'])

    def _post_downgrade_206(self, engine):
        self.assertColumnNotExists(engine, 'instances', 'cleaned')
        self.assertColumnNotExists(engine, 'shadow_instances', 'cleaned')

    def _207(self, engine, upgrade=False):
        uniq_names = ['uniq_cell_name0deleted',
                      'uniq_cells0name0deleted']
        if upgrade:
            uniq_names = uniq_names[::-1]
        cells = db_utils.get_table(engine, 'cells')
        values = {'name': 'name',
                  'deleted': 0,
                  'transport_url': 'fake_transport_url'}
        cells.insert().values(values).execute()
        values['deleted'] = 1
        cells.insert().values(values).execute()
        values['deleted'] = 0
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          cells.insert().execute,
                          values)
        cells.delete().execute()
        indexes = dict((i.name, i) for i in cells.indexes)
        if indexes:
            check_index_old = indexes.get(uniq_names[0])
            check_index_new = indexes.get(uniq_names[1])
            self.assertTrue(bool(check_index_old))
            self.assertFalse(bool(check_index_new))

    def _pre_upgrade_207(self, engine):
        self._207(engine)

    def _check_207(self, engine, data):
        self._207(engine, upgrade=True)

    def _post_downgrade_207(self, engine):
        self._207(engine)

    def _check_208(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'host_ip')
        self.assertColumnExists(engine, 'compute_nodes', 'supported_instances')

        compute_nodes = db_utils.get_table(engine, 'compute_nodes')
        if engine.name == "postgresql":
            self.assertIsInstance(compute_nodes.c.host_ip.type,
                                  sqlalchemy.dialects.postgresql.INET)
        else:
            self.assertIsInstance(compute_nodes.c.host_ip.type,
                                  sqlalchemy.types.String)
        self.assertIsInstance(compute_nodes.c.supported_instances.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_208(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'host_ip')
        self.assertColumnNotExists(engine, 'compute_nodes',
                                   'supported_instance')

    def _data_209(self):
        ret = {
            "compute_nodes": ({"service_id": 999, "vcpus": 1, "memory_mb": 1,
                               "local_gb": 1, "vcpus_used": 1,
                               "memory_mb_used": 1, "local_gb_used": 1,
                               "hypervisor_type": "fake_type",
                               "hypervisor_version": 1, "cpu_info": "info"},
                              ("compute_node_stats", "compute_node_id",
                               {"key": "fake", "value": "bar"})),
           "instance_actions": ({"instance_uuid": "fake"},
                                ("instance_actions_events", "action_id",
                                 {"event": "fake"})),
           "migrations": ({"instance_uuid": "fake"}, None),
           "instance_faults": ({"instance_uuid": "fake", "code": 1}, None),
           "compute_node_stats": ({"compute_node_id": 1, "key": "fake"},
                                  None),
        }
        return ret

    def _constraints_209(self):
        return {"compute_nodes": ('services', 'id'),
                "instance_actions": ('instances', 'uuid'),
                "migrations": ('instances', 'uuid'),
                "instance_faults": ('instances', 'uuid'),
                "compute_node_stats": ('compute_nodes', 'id')}

    def _pre_upgrade_209(self, engine):
        if engine.name == 'sqlite':
            return

        instances = db_utils.get_table(engine, 'instances')
        instances.delete().where(instances.c.uuid == None).execute()

        for table_name, (row, child) in self._data_209().iteritems():
            table = db_utils.get_table(engine, table_name)
            table.delete().execute()
            result = table.insert().values(row).execute()

            if child:
                # Get id of row
                child_table_name, child_column_name, child_row = child

                child_row = child_row.copy()
                child_row[child_column_name] = result.inserted_primary_key[0]

                child_table = db_utils.get_table(engine, child_table_name)
                child_table.delete().execute()
                child_table.insert().values(child_row).execute()

        # NOTE(jhesketh): Add instance with NULL uuid to check the backups
        #                 still work correctly and avoid violating the foreign
        #                 key constraint. If there are NULL values in a NOT IN
        #                 () set the result is always false. Therefore having
        #                 this instance inserted here causes migration 209 to
        #                 fail unless the IN set sub-query is modified
        #                 appropriately. See bug/1240325
        instances.insert({'uuid': None}).execute()

    def _check_209(self, engine, data):
        if engine.name == 'sqlite':
            return
        for table_name, (row, child) in self._data_209().iteritems():
            table = db_utils.get_table(engine, table_name)
            self.assertRaises(sqlalchemy.exc.IntegrityError,
                              table.insert().values(row).execute)
            dump_table = db_utils.get_table(engine, 'dump_' + table_name)
            self.assertEqual(len(dump_table.select().execute().fetchall()), 1)
            table.delete().execute()
            fks = [(f.column.table.name, f.column.name)
                   for f in table.foreign_keys]
            self.assertIn(self._constraints_209().get(table_name), fks)

    def _post_downgrade_209(self, engine):
        if engine.name == 'sqlite':
            return
        check_tables = engine.table_names()
        for table_name, (row, child) in self._data_209().iteritems():
            table = db_utils.get_table(engine, table_name)
            dump_table_name = 'dump_' + table_name
            self.assertNotIn(dump_table_name, check_tables)
            table.insert().values(row).execute()
            self.assertEqual(len(table.select().execute().fetchall()), 2)
            fks = [(f.column.table.name, f.column.name)
                   for f in table.foreign_keys]
            self.assertNotIn(self._constraints_209().get(table_name), fks)

    def _check_210(self, engine, data):
        project_user_quotas = db_utils.get_table(engine, 'project_user_quotas')

        index_data = [(idx.name, idx.columns.keys())
                      for idx in project_user_quotas.indexes]

        if engine.name == 'postgresql':
            # NOTE(vsergeyev): There is no possibility to get the order of
            #                  columns due to bug in reflection of indexes in
            #                  PostgreSQL.
            #                  See http://www.sqlalchemy.org/trac/ticket/2767
            #                  So we should compare sets instead of lists.
            index_data = [(name, set(columns)) for name, columns in index_data]
            self.assertIn(('project_user_quotas_user_id_deleted_idx',
                           set(['user_id', 'deleted'])), index_data)
        else:
            self.assertIn(('project_user_quotas_user_id_deleted_idx',
                           ['user_id', 'deleted']), index_data)

    def _post_downgrade_210(self, engine):
        project_user_quotas = db_utils.get_table(engine, 'project_user_quotas')

        index_data = [(idx.name, idx.columns.keys())
                      for idx in project_user_quotas.indexes]

        if engine.name == 'postgresql':
            # NOTE(vsergeyev): There is no possibility to get the order of
            #                  columns due to bug in reflection of indexes in
            #                  PostgreSQL.
            #                  See http://www.sqlalchemy.org/trac/ticket/2767
            #                  So we should compare sets instead of lists.
            index_data = [(name, set(columns)) for name, columns in index_data]
            self.assertNotIn(('project_user_quotas_user_id_deleted_idx',
                              set(['user_id', 'deleted'])), index_data)
        else:
            self.assertNotIn(('project_user_quotas_user_id_deleted_idx',
                              ['user_id', 'deleted']), index_data)

    def _pre_upgrade_211(self, engine):
        fake_aggregates = [{'id': 7, 'name': 'name1'},
                           {'id': 8, 'name': 'name2'}]
        aggregates = db_utils.get_table(engine, 'aggregates')
        engine.execute(aggregates.insert(), fake_aggregates)
        metadata = db_utils.get_table(engine, 'aggregate_metadata')
        data = [
                {'aggregate_id': 7, 'key': 'availability_zone',
                 'value': 'custom_az1', 'deleted': 0},
                {'aggregate_id': 7, 'key': 'availability_zone',
                 'value': 'custom_az2', 'deleted': 0},
                {'aggregate_id': 8, 'key': 'availability_zone',
                 'value': 'custom_az3', 'deleted': 0},
        ]
        for item in data:
            metadata.insert().values(item).execute()
        return data

    def _check_211(self, engine, data):
        metadata = db_utils.get_table(engine, 'aggregate_metadata')

        def get_(aggrid, deleted):
            deleted_value = 0 if not deleted else metadata.c.id
            return metadata.select().\
                   where(metadata.c.aggregate_id == aggrid).\
                   where(metadata.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_(7, False)))
        self.assertEqual(1, len(get_(7, True)))
        self.assertEqual(1, len(get_(8, False)))
        self.assertRaises(sqlalchemy.exc.IntegrityError,
                          metadata.insert().execute,
                          {'aggregate_id': 7, 'key': 'availability_zone',
                           'value': 'az4', 'deleted': 0})

    def _post_downgrade_211(self, engine):
        metadata = db_utils.get_table(engine, 'aggregate_metadata')
        data = {'aggregate_id': 8, 'key': 'availability_zone',
                'value': 'az', 'deleted': 0}
        metadata.insert().values(data).execute()
        self.assertIsNotNone(metadata.insert().values(data).execute())

    def _212(self, engine, ext=None):
        if engine.name == 'sqlite':
            return
        migrations = db_utils.get_table(engine, 'migrations')
        indexes = dict((i.name, i) for i in migrations.indexes)
        check_index = indexes['migrations_by_host_nodes_and_status_idx']
        index_columns = [c.name for c in check_index.columns]
        check_columns = ['source_compute', 'dest_compute', 'source_node',
                         'dest_node', 'status']
        if ext is not None:
            check_columns.insert(0, ext)
        self.assertTrue(set(index_columns) == set(check_columns))

    def _pre_upgrade_212(self, engine):
        if engine.name == 'mysql':
            self._212(engine)

    def _check_212(self, engine, data):
        self._212(engine, ext='deleted')

    def _post_downgrade_212(self, engine):
        if engine.name == 'mysql':
            self._212(engine)

    def _213(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'pci_devices')
        self.assertColumnNotExists(engine, 'compute_nodes', 'pci_stats')

    def _pre_upgrade_213(self, engine):
        self._213(engine)

    def _check_213(self, engine, data):
        fake_pci = {'id': 3353,
                    'compute_node_id': 1,
                    'dev_id': 'pci_0000:0f:08:07',
                    'address': '0000:0f:08:7',
                    'product_id': '8086',
                    'vendor_id': '1520',
                    'dev_type': 'type-VF',
                    'label': 'label_8086_1520',
                    'status': 'available',
                    'extra_info': None,
                    'deleted': 0,
                    'instance_uuid': '00000000-0000-0000-0000-000000000010',
                   }
        devs = db_utils.get_table(engine, 'pci_devices')
        engine.execute(devs.insert(), fake_pci)
        result = devs.select().execute().fetchall()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['vendor_id'], '1520')

        self.assertColumnExists(engine, 'compute_nodes', 'pci_stats')
        nodes = db_utils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(nodes.c.pci_stats.type, sqlalchemy.types.Text)

    def _post_downgrade_213(self, engine):
        self._213(engine)

    def _pre_upgrade_214(self, engine):
        test_data = {
            # table_name: ((index_name_1, (*columns)), ...)
            "migrations": ((
                 'migrations_instance_uuid_and_status_idx',
                ['deleted', 'instance_uuid', 'status']
            ),)
        }

        return test_data

    def _check_214(self, engine, data):
        if engine.name == 'sqlite':
            return

        for table_name, indexes in data.iteritems():
            meta = sqlalchemy.MetaData()
            meta.bind = engine
            table = sqlalchemy.Table(table_name, meta, autoload=True)

            index_data = [(idx.name, idx.columns.keys())
                          for idx in table.indexes]

            for name, columns in indexes:
                if engine.name == "postgresql":
                    # we can not get correct order of columns in index
                    # definition to postgresql using sqlalchemy. So we sortind
                    # columns list before compare
                    # bug http://www.sqlalchemy.org/trac/ticket/2767
                    self.assertIn(
                        (name, sorted(columns)),
                        ([(idx[0], sorted(idx[1])) for idx in index_data])
                    )
                else:
                    self.assertIn((name, columns), index_data)

    def _post_downgrade_214(self, engine):
        if engine.name == 'sqlite':
            return

        for table_name, indexes in self._pre_upgrade_214(engine).iteritems():
            meta = sqlalchemy.MetaData()
            meta.bind = engine
            table = sqlalchemy.Table(table_name, meta, autoload=True)

            index_data = [(idx.name, idx.columns.keys())
                          for idx in table.indexes]

            for name, columns in indexes:
                if engine.name == "postgresql":
                    # we can not get correct order of columns in index
                    # definition to postgresql using sqlalchemy. So we sortind
                    # columns list before compare
                    # bug http://www.sqlalchemy.org/trac/ticket/2767
                    self.assertNotIn(
                        (name, sorted(columns)),
                        ([(idx[0], sorted(idx[1])) for idx in index_data])
                    )
                else:
                    self.assertNotIn((name, columns), index_data)

    def _data_215(self):
        ret = {"services": [{"host": "compute-host1", "id": 1,
                             "binary": "nova-compute", "topic": "compute",
                             "report_count": 1}],
               "compute_nodes": [{"vcpus": 1, "cpu_info": "info",
                                  "memory_mb": 1, "local_gb": 1,
                                  "vcpus_used": 1, "memory_mb_used": 1,
                                  "local_gb_used": 1, "deleted": 0,
                                  "hypervisor_type": "fake_type",
                                  "hypervisor_version": 1,
                                  "service_id": 1, "id": 10001},
                                 {"vcpus": 1, "cpu_info": "info",
                                  "memory_mb": 1, "local_gb": 1,
                                  "vcpus_used": 1, "memory_mb_used": 1,
                                  "local_gb_used": 1, "deleted": 2,
                                  "hypervisor_type": "fake_type",
                                  "hypervisor_version": 1,
                                  "service_id": 1, "id": 10002}],
               "compute_node_stats": [{"id": 10, "compute_node_id": 10001,
                                       "key": "fake-1",
                                       "deleted": 0},
                                      {"id": 20, "compute_node_id": 10002,
                                       "key": "fake-2",
                                       "deleted": 0}]}
        return ret

    def _pre_upgrade_215(self, engine):
        tables = ["services", "compute_nodes", "compute_node_stats"]
        change_tables = dict((i, db_utils.get_table(engine, i))
                             for i in tables)
        data = self._data_215()
        for i in tables:
            change_tables[i].delete().execute()
            for v in data[i]:
                change_tables[i].insert().values(v).execute()

    def _check_215(self, engine, data):
        stats = db_utils.get_table(engine, "compute_node_stats")

        def get_(stat_id, deleted):
            deleted_value = 0 if not deleted else stats.c.id
            return stats.select().\
                   where(stats.c.id == stat_id).\
                   where(stats.c.deleted == deleted_value).\
                   execute().\
                   fetchall()

        self.assertEqual(1, len(get_(10, False)))
        self.assertEqual(1, len(get_(20, True)))

    def _data_216(self):
        ret = {'instances': [{'user_id': '1234', 'project_id': '5678',
                              'vcpus': 2, 'memory_mb': 256, 'uuid': 'uuid1',
                              'deleted': 0},
                             {'user_id': '234', 'project_id': '5678',
                              'vcpus': 1, 'memory_mb': 256, 'deleted': 0}],
            'security_groups': [{'user_id': '1234', 'project_id': '5678',
                                 'deleted': 0},
                                {'user_id': '234', 'project_id': '5678',
                                 'deleted': 0},
                                {'user_id': '234', 'project_id': '5678',
                                 'deleted': 0}],
            'floating_ips': [{'deleted': 0, 'project_id': '5678',
                              'auto_assigned': False},
                             {'deleted': 0, 'project_id': '5678',
                              'auto_assigned': False}],
            'fixed_ips': [{'instance_uuid': 'uuid1', 'deleted': 0}],
            'networks': [{'project_id': '5678', 'deleted': 0}],
            'quota_usages': [{'user_id': '1234', 'project_id': '5678',
                'resource': 'instances', 'in_use': 1, 'reserved': 0},
                {'user_id': '234', 'project_id': '5678',
                    'resource': 'instances', 'in_use': 1, 'reserved': 0},
                {'user_id': None, 'project_id': '5678',
                    'resource': 'instances', 'in_use': 1, 'reserved': 0},
                {'user_id': '1234', 'project_id': '5678',
                    'resource': 'security_groups', 'in_use': 1, 'reserved': 0},
                {'user_id': '234', 'project_id': '5678',
                    'resource': 'security_groups', 'in_use': 2, 'reserved': 0},
                {'user_id': None, 'project_id': '5678',
                    'resource': 'security_groups', 'in_use': 1, 'reserved': 0},
                {'user_id': '1234', 'project_id': '5678',
                    'resource': 'floating_ips', 'in_use': 1, 'reserved': 0},
                {'user_id': None, 'project_id': '5678',
                    'resource': 'floating_ips', 'in_use': 1, 'reserved': 0},
                {'user_id': '1234', 'project_id': '5678',
                    'resource': 'fixed_ips', 'in_use': 1, 'reserved': 0},
                {'user_id': None, 'project_id': '5678',
                    'resource': 'fixed_ips', 'in_use': 1, 'reserved': 0},
                {'user_id': '1234', 'project_id': '5678',
                    'resource': 'networks', 'in_use': 1, 'reserved': 0},
                {'user_id': None, 'project_id': '5678',
                    'resource': 'networks', 'in_use': 2, 'reserved': 0}]}
        return ret

    def _pre_upgrade_216(self, engine):
        tables = ['instance_system_metadata', 'instance_info_caches',
                'block_device_mapping', 'security_group_instance_association',
                'security_groups', 'migrations', 'instance_metadata',
                'fixed_ips', 'instances', 'security_groups', 'floating_ips',
                'fixed_ips', 'networks']
        delete_tables = dict((table, db_utils.get_table(engine, table))
                             for table in tables)
        for table in tables:
            delete_tables[table].delete().execute()

        data = self._data_216()
        tables = data.keys()
        change_tables = dict((table, db_utils.get_table(engine, table))
                             for table in tables)
        for table in tables:
            for row in data[table]:
                try:
                    change_tables[table].insert().values(row).execute()
                except sqlalchemy.exc.IntegrityError:
                    # This is run multiple times with opportunistic db testing.
                    # There's no on duplicate key update functionality in
                    # sqlalchemy so we just ignore the error.
                    pass

    def _check_216(self, engine, data):
        quota_usages = db_utils.get_table(engine, 'quota_usages')
        per_user = {'1234': {'instances': 1, 'cores': 2, 'ram': 256,
                        'security_groups': 1},
                    '234': {'instances': 1, 'cores': 1, 'ram': 256,
                        'security_groups': 2}}

        per_project = {'floating_ips': 2, 'fixed_ips': 1, 'networks': 1}

        for resource in ['instances', 'cores', 'ram', 'security_groups']:
            rows = quota_usages.select().where(
                    quota_usages.c.user_id == None).where(
                            quota_usages.c.resource == resource).execute(
                                    ).fetchall()
            self.assertEqual(0, len(rows))

        for user in per_user.keys():
            rows = quota_usages.select().where(
                    quota_usages.c.user_id == user).where(
                            quota_usages.c.project_id == '5678').execute(
                                    ).fetchall()
            for row in rows:
                resource = row['resource']
                self.assertEqual(per_user[user][resource], row['in_use'])

        networks = db_utils.get_table(engine, 'networks')
        rows = networks.select().execute().fetchall()
        for resource in per_project:
            rows = quota_usages.select().where(
                    quota_usages.c.resource == resource).where(
                            quota_usages.c.project_id == '5678').execute(
                                    ).fetchall()
            self.assertEqual(1, len(rows))
            self.assertEqual(per_project[resource], rows[0]['in_use'])

    def _check_227(self, engine, data):
        table = db_utils.get_table(engine, 'project_user_quotas')

        # Insert fake_quotas with the longest resource name.
        fake_quotas = {'id': 5,
                       'project_id': 'fake_project',
                       'user_id': 'fake_user',
                       'resource': 'injected_file_content_bytes',
                       'hard_limit': 10}
        table.insert().execute(fake_quotas)

        # Check we can get the longest resource name.
        quota = table.select(table.c.id == 5).execute().first()
        self.assertEqual(quota['resource'], 'injected_file_content_bytes')

    def _check_228(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'metrics')

        compute_nodes = db_utils.get_table(engine, 'compute_nodes')
        self.assertTrue(isinstance(compute_nodes.c.metrics.type,
                            sqlalchemy.types.Text))

    def _post_downgrade_228(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'metrics')

    def _check_229(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'extra_resources')

        compute_nodes = db_utils.get_table(engine, 'compute_nodes')
        self.assertTrue(isinstance(compute_nodes.c.extra_resources.type,
                            sqlalchemy.types.Text))

    def _post_downgrade_229(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'extra_resources')


class TestBaremetalMigrations(BaseWalkMigrationTestCase, CommonTestsMixIn):
    """Test sqlalchemy-migrate migrations."""
    USER = "openstack_citest"
    PASSWD = "openstack_citest"
    DATABASE = "openstack_baremetal_citest"

    def __init__(self, *args, **kwargs):
        super(TestBaremetalMigrations, self).__init__(*args, **kwargs)

        self.DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                '../virt/baremetal/test_baremetal_migrations.conf')
        # Test machines can set the NOVA_TEST_MIGRATIONS_CONF variable
        # to override the location of the config file for migration testing
        self.CONFIG_FILE_PATH = os.environ.get(
                'BAREMETAL_TEST_MIGRATIONS_CONF',
                self.DEFAULT_CONFIG_FILE)
        self.MIGRATE_FILE = \
                nova.virt.baremetal.db.sqlalchemy.migrate_repo.__file__
        self.REPOSITORY = repository.Repository(
                        os.path.abspath(os.path.dirname(self.MIGRATE_FILE)))

    def setUp(self):
        super(TestBaremetalMigrations, self).setUp()

        if self.migration is None:
            self.migration = __import__('nova.virt.baremetal.db.migration',
                    globals(), locals(), ['db_initial_version'], -1)
            self.INIT_VERSION = self.migration.db_initial_version()
        if self.migration_api is None:
            temp = __import__('nova.virt.baremetal.db.sqlalchemy.migration',
                    globals(), locals(), ['versioning_api'], -1)
            self.migration_api = temp.versioning_api

    def _pre_upgrade_002(self, engine):
        data = [{'id': 1, 'key': 'fake-key', 'image_path': '/dev/null',
                 'pxe_config_path': '/dev/null/', 'root_mb': 0, 'swap_mb': 0}]
        table = db_utils.get_table(engine, 'bm_deployments')
        engine.execute(table.insert(), data)
        return data

    def _check_002(self, engine, data):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'bm_deployments')

    def _post_downgrade_004(self, engine):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        self.assertNotIn(u'instance_name', [c.name for c in bm_nodes.columns])

    def _check_005(self, engine, data):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        columns = [c.name for c in bm_nodes.columns]
        self.assertNotIn(u'prov_vlan_id', columns)
        self.assertNotIn(u'registration_status', columns)

    def _pre_upgrade_006(self, engine):
        nodes = db_utils.get_table(engine, 'bm_nodes')
        ifs = db_utils.get_table(engine, 'bm_interfaces')
        # node 1 has two diffrent addresses in bm_nodes and bm_interfaces
        engine.execute(nodes.insert(),
                       [{'id': 1,
                         'prov_mac_address': 'aa:aa:aa:aa:aa:aa'}])
        engine.execute(ifs.insert(),
                       [{'id': 101,
                         'bm_node_id': 1,
                         'address': 'bb:bb:bb:bb:bb:bb'}])
        # node 2 has one same address both in bm_nodes and bm_interfaces
        engine.execute(nodes.insert(),
                       [{'id': 2,
                         'prov_mac_address': 'cc:cc:cc:cc:cc:cc'}])
        engine.execute(ifs.insert(),
                       [{'id': 201,
                         'bm_node_id': 2,
                         'address': 'cc:cc:cc:cc:cc:cc'}])

    def _check_006(self, engine, data):
        ifs = db_utils.get_table(engine, 'bm_interfaces')
        rows = ifs.select().\
                    where(ifs.c.bm_node_id == 1).\
                    execute().\
                    fetchall()
        self.assertEqual(len(rows), 2)
        rows = ifs.select().\
                    where(ifs.c.bm_node_id == 2).\
                    execute().\
                    fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['address'], 'cc:cc:cc:cc:cc:cc')

    def _post_downgrade_006(self, engine):
        ifs = db_utils.get_table(engine, 'bm_interfaces')
        rows = ifs.select().where(ifs.c.bm_node_id == 1).execute().fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['address'], 'bb:bb:bb:bb:bb:bb')

        rows = ifs.select().where(ifs.c.bm_node_id == 2).execute().fetchall()
        self.assertEqual(len(rows), 0)

    def _check_007(self, engine, data):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        columns = [c.name for c in bm_nodes.columns]
        self.assertNotIn(u'prov_mac_address', columns)

    def _check_008(self, engine, data):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'bm_pxe_ips')

    def _post_downgrade_008(self, engine):
        db_utils.get_table(engine, 'bm_pxe_ips')


class ProjectTestCase(test.NoDBTestCase):

    def test_all_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../../')
        py_glob = os.path.join(topdir, "nova", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")

        missing_downgrade = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and not has_downgrade:
                    fname = os.path.basename(path)
                    missing_downgrade.append(fname)

        helpful_msg = (_("The following migrations are missing a downgrade:"
                         "\n\t%s") % '\n\t'.join(sorted(missing_downgrade)))
        self.assertTrue(not missing_downgrade, helpful_msg)

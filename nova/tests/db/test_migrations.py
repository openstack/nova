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

For the opportunistic testing you need to set up db's named 'openstack_citest'
and 'openstack_baremetal_citest' with user 'openstack_citest' and password
'openstack_citest' on localhost. The test will then use that db and u/p combo
to run the tests.

For postgres on Ubuntu this can be done with the following commands:

sudo -u postgres psql
postgres=# create user openstack_citest with createdb login password
      'openstack_citest';
postgres=# create database openstack_citest with owner openstack_citest;
postgres=# create database openstack_baremetal_citest with owner
            openstack_citest;

"""

import ConfigParser
import glob
import os

from migrate.versioning import repository
import six.moves.urllib.parse as urlparse
import sqlalchemy
import sqlalchemy.exc

import nova.db.sqlalchemy.migrate_repo
from nova.db.sqlalchemy import utils as db_utils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import test
from nova import utils
import nova.virt.baremetal.db.sqlalchemy.migrate_repo


LOG = logging.getLogger(__name__)


def _get_connect_string(backend, user, passwd, database):
    """Try to get a connection with a very specific set of values, if we get
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
        """Test that we can trigger a mysql connection failure and we fail
        gracefully to ensure we don't break people without mysql
        """
        if _is_backend_avail('mysql', "openstack_cifail", self.PASSWD,
                             self.DATABASE):
            self.fail("Shouldn't have connected")

    def test_postgresql_opportunistically(self):
        self._test_postgresql_opportunistically()

    def test_postgresql_connect_fail(self):
        """Test that we can trigger a postgres connection failure and we fail
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
                get_pgsql_connection_info(urlparse.urlparse(connect_string))
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

    def assertTableNotExists(self, engine, table):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, table)

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
        self.assertIsInstance(compute_nodes.c.metrics.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_228(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'metrics')

    def _check_229(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'extra_resources')

        compute_nodes = db_utils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.extra_resources.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_229(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'extra_resources')

    def _check_230(self, engine, data):
        for table_name in ['instance_actions_events',
                           'shadow_instance_actions_events']:
            self.assertColumnExists(engine, table_name, 'host')
            self.assertColumnExists(engine, table_name, 'details')

        action_events = db_utils.get_table(engine, 'instance_actions_events')
        self.assertIsInstance(action_events.c.host.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(action_events.c.details.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_230(self, engine):
        for table_name in ['instance_actions_events',
                           'shadow_instance_actions_events']:
            self.assertColumnNotExists(engine, table_name, 'host')
            self.assertColumnNotExists(engine, table_name, 'details')

    def _check_231(self, engine, data):
        self.assertColumnExists(engine, 'instances', 'ephemeral_key_uuid')

        instances = db_utils.get_table(engine, 'instances')
        self.assertIsInstance(instances.c.ephemeral_key_uuid.type,
                              sqlalchemy.types.String)
        self.assertTrue(db_utils.check_shadow_table(engine, 'instances'))

    def _post_downgrade_231(self, engine):
        self.assertColumnNotExists(engine, 'instances', 'ephemeral_key_uuid')
        self.assertTrue(db_utils.check_shadow_table(engine, 'instances'))

    def _check_232(self, engine, data):
        table_names = ['compute_node_stats', 'compute_nodes',
                       'instance_actions', 'instance_actions_events',
                       'instance_faults', 'migrations']
        for table_name in table_names:
            self.assertTableNotExists(engine, 'dump_' + table_name)

    def _check_233(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'stats')

        compute_nodes = db_utils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.stats.type,
                              sqlalchemy.types.Text)

        self.assertRaises(sqlalchemy.exc.NoSuchTableError, db_utils.get_table,
                          engine, 'compute_node_stats')

    def _post_downgrade_233(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'stats')

        # confirm compute_node_stats exists
        db_utils.get_table(engine, 'compute_node_stats')


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
        # node 1 has two different addresses in bm_nodes and bm_interfaces
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

    def _pre_upgrade_010(self, engine):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        data = [{'id': 10, 'prov_mac_address': 'cc:cc:cc:cc:cc:cc'}]
        engine.execute(bm_nodes.insert(), data)

        return data

    def _check_010(self, engine, data):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        self.assertIn('preserve_ephemeral', bm_nodes.columns)

        default = engine.execute(
            sqlalchemy.select([bm_nodes.c.preserve_ephemeral])
                      .where(bm_nodes.c.id == data[0]['id'])
        ).scalar()
        self.assertEqual(default, False)

        bm_nodes.delete().where(bm_nodes.c.id == data[0]['id']).execute()

    def _post_downgrade_010(self, engine):
        bm_nodes = db_utils.get_table(engine, 'bm_nodes')
        self.assertNotIn('preserve_ephemeral', bm_nodes.columns)


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

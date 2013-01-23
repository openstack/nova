# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack, LLC
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
"""

import commands
import ConfigParser
import os
import urlparse

from migrate.versioning import repository
import sqlalchemy

import nova.db.migration as migration
import nova.db.sqlalchemy.migrate_repo
from nova.db.sqlalchemy.migration import versioning_api as migration_api
from nova.openstack.common import log as logging
from nova import test


LOG = logging.getLogger(__name__)


def _get_connect_string(backend,
                        user="openstack_citest",
                        passwd="openstack_citest",
                        database="openstack_citest"):
    """
    Try to get a connection with a very specific set of values, if we get
    these then we'll run the tests, otherwise they are skipped
    """
    if backend == "postgres":
        backend = "postgresql+psycopg2"

    return ("%(backend)s://%(user)s:%(passwd)s@localhost/%(database)s"
            % locals())


def _is_backend_avail(backend,
                      user="openstack_citest",
                      passwd="openstack_citest",
                      database="openstack_citest"):
    try:
        if backend == "mysql":
            connect_uri = _get_connect_string("mysql",
                user=user, passwd=passwd, database=database)
        elif backend == "postgres":
            connect_uri = _get_connect_string("postgres",
                user=user, passwd=passwd, database=database)
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


def _have_mysql():
    present = os.environ.get('NOVA_TEST_MYSQL_PRESENT')
    if present is None:
        return _is_backend_avail('mysql')
    return present.lower() in ('', 'true')


class TestMigrations(test.TestCase):
    """Test sqlalchemy-migrate migrations."""

    DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__),
                                       'test_migrations.conf')
    # Test machines can set the NOVA_TEST_MIGRATIONS_CONF variable
    # to override the location of the config file for migration testing
    CONFIG_FILE_PATH = os.environ.get('NOVA_TEST_MIGRATIONS_CONF',
                                      DEFAULT_CONFIG_FILE)
    MIGRATE_FILE = nova.db.sqlalchemy.migrate_repo.__file__
    REPOSITORY = repository.Repository(
                                os.path.abspath(os.path.dirname(MIGRATE_FILE)))

    def setUp(self):
        super(TestMigrations, self).setUp()

        self.snake_walk = False
        self.test_databases = {}

        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % TestMigrations.CONFIG_FILE_PATH)
        if os.path.exists(TestMigrations.CONFIG_FILE_PATH):
            cp = ConfigParser.RawConfigParser()
            try:
                cp.read(TestMigrations.CONFIG_FILE_PATH)
                defaults = cp.defaults()
                for key, value in defaults.items():
                    self.test_databases[key] = value
                self.snake_walk = cp.getboolean('walk_style', 'snake_walk')
            except ConfigParser.ParsingError, e:
                self.fail("Failed to read test_migrations.conf config "
                          "file. Got error: %s" % e)
        else:
            self.fail("Failed to find test_migrations.conf config "
                      "file.")

        self.engines = {}
        for key, value in self.test_databases.items():
            self.engines[key] = sqlalchemy.create_engine(value)

        # We start each test case with a completely blank slate.
        self._reset_databases()

    def tearDown(self):
        # We destroy the test data store between each test case,
        # and recreate it, which ensures that we have no side-effects
        # from the tests
        self._reset_databases()

        # remove these from the list so they aren't used in the migration tests
        if "mysqlcitest" in self.engines:
            del self.engines["mysqlcitest"]
        if "mysqlcitest" in self.test_databases:
            del self.test_databases["mysqlcitest"]
        super(TestMigrations, self).tearDown()

    def _reset_databases(self):
        def execute_cmd(cmd=None):
            status, output = commands.getstatusoutput(cmd)
            LOG.debug(output)
            self.assertEqual(0, status)
        for key, engine in self.engines.items():
            conn_string = self.test_databases[key]
            conn_pieces = urlparse.urlparse(conn_string)
            engine.dispose()
            if conn_string.startswith('sqlite'):
                # We can just delete the SQLite database, which is
                # the easiest and cleanest solution
                db_path = conn_pieces.path.strip('/')
                if os.path.exists(db_path):
                    os.unlink(db_path)
                # No need to recreate the SQLite DB. SQLite will
                # create it for us if it's not there...
            elif conn_string.startswith('mysql'):
                # We can execute the MySQL client to destroy and re-create
                # the MYSQL database, which is easier and less error-prone
                # than using SQLAlchemy to do this via MetaData...trust me.
                database = conn_pieces.path.strip('/')
                loc_pieces = conn_pieces.netloc.split('@')
                host = loc_pieces[1]
                auth_pieces = loc_pieces[0].split(':')
                user = auth_pieces[0]
                password = ""
                if len(auth_pieces) > 1:
                    if auth_pieces[1].strip():
                        password = "-p\"%s\"" % auth_pieces[1]
                sql = ("drop database if exists %(database)s; "
                       "create database %(database)s;") % locals()
                cmd = ("mysql -u \"%(user)s\" %(password)s -h %(host)s "
                       "-e \"%(sql)s\"") % locals()
                execute_cmd(cmd)
            elif conn_string.startswith('postgresql'):
                database = conn_pieces.path.strip('/')
                loc_pieces = conn_pieces.netloc.split('@')
                host = loc_pieces[1]

                auth_pieces = loc_pieces[0].split(':')
                user = auth_pieces[0]
                password = ""
                if len(auth_pieces) > 1:
                    password = auth_pieces[1].strip()
                # note(boris-42): This file is used for authentication
                # without password prompt.
                createpgpass = ("echo '*:*:*:%(user)s:%(password)s' > "
                                "~/.pgpass && chmod 0600 ~/.pgpass" % locals())
                execute_cmd(createpgpass)
                # note(boris-42): We must create and drop database, we can't
                # drop database which we have connected to, so for such
                # operations there is a special database template1.
                sqlcmd = ("psql -w -U %(user)s -h %(host)s -c"
                                     " '%(sql)s' -d template1")
                sql = ("drop database if exists %(database)s;") % locals()
                droptable = sqlcmd % locals()
                execute_cmd(droptable)
                sql = ("create database %(database)s;") % locals()
                createtable = sqlcmd % locals()
                execute_cmd(createtable)

    def test_walk_versions(self):
        """
        Walks all version scripts for each tested database, ensuring
        that there are no errors in the version scripts for each engine
        """
        for key, engine in self.engines.items():
            self._walk_versions(engine, self.snake_walk)

    def test_mysql_connect_fail(self):
        """
        Test that we can trigger a mysql connection failure and we fail
        gracefully to ensure we don't break people without mysql
        """
        if _is_backend_avail('mysql', user="openstack_cifail"):
            self.fail("Shouldn't have connected")

    def test_mysql_opportunistically(self):
        # Test that table creation on mysql only builds InnoDB tables
        if not _is_backend_avail('mysql'):
            self.skipTest("mysql not available")
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        connect_string = _get_connect_string("mysql")
        engine = sqlalchemy.create_engine(connect_string)
        self.engines["mysqlcitest"] = engine
        self.test_databases["mysqlcitest"] = connect_string

        # Test that we end in an innodb
        self._check_mysql_innodb(engine)
        # Test IP transition
        self._check_mysql_migration_149(engine)

    def _check_mysql_innodb(self, engine):
        # build a fully populated mysql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

        uri = _get_connect_string("mysql", database="information_schema")
        connection = sqlalchemy.create_engine(uri).connect()

        # sanity check
        total = connection.execute("SELECT count(*) "
                                   "from information_schema.TABLES "
                                   "where TABLE_SCHEMA='openstack_citest'")
        self.assertTrue(total.scalar() > 0, "No tables found. Wrong schema?")

        noninnodb = connection.execute("SELECT count(*) "
                                       "from information_schema.TABLES "
                                       "where TABLE_SCHEMA='openstack_citest' "
                                       "and ENGINE!='InnoDB' "
                                       "and TABLE_NAME!='migrate_version'")
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)

    def test_migration_149_postgres(self):
        """Test updating a table with IPAddress columns."""
        if not _is_backend_avail('postgres'):
            self.skipTest("postgres not available")

        connect_string = _get_connect_string("postgres")
        engine = sqlalchemy.create_engine(connect_string)

        self.engines["postgrescitest"] = engine
        self.test_databases["postgrescitest"] = connect_string

        self._reset_databases()
        migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                      migration.INIT_VERSION)

        connection = engine.connect()

        self._migrate_up(engine, 148)
        IPS = ("127.0.0.1", "255.255.255.255", "2001:db8::1:2", "::1")
        connection.execute("INSERT INTO provider_fw_rules "
                           "            (protocol, from_port, to_port, cidr)"
                           "VALUES ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s')" % IPS)
        self.assertEqual('character varying',
                         connection.execute(
                "SELECT data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_name='provider_fw_rules' "
                "AND table_catalog='openstack_citest' "
                "AND column_name='cidr'").scalar())

        self._migrate_up(engine, 149)
        self.assertEqual(IPS,
                         tuple(tup[0] for tup in connection.execute(
                    "SELECT cidr from provider_fw_rules").fetchall()))
        self.assertEqual('inet',
                         connection.execute(
                "SELECT data_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_name='provider_fw_rules' "
                "AND table_catalog='openstack_citest' "
                "AND column_name='cidr'").scalar())
        connection.close()

    def _check_mysql_migration_149(self, engine):
        """Test updating a table with IPAddress columns."""
        self._reset_databases()
        migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                      migration.INIT_VERSION)

        uri = _get_connect_string("mysql", database="openstack_citest")
        connection = sqlalchemy.create_engine(uri).connect()

        self._migrate_up(engine, 148)

        IPS = ("127.0.0.1", "255.255.255.255", "2001:db8::1:2", "::1")
        connection.execute("INSERT INTO provider_fw_rules "
                           "            (protocol, from_port, to_port, cidr)"
                           "VALUES ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s'), "
                           "       ('tcp', 1234, 1234, '%s')" % IPS)
        self.assertEqual('varchar(255)',
                         connection.execute(
                "SELECT column_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_name='provider_fw_rules' "
                "AND table_schema='openstack_citest' "
                "AND column_name='cidr'").scalar())

        connection.close()

        self._migrate_up(engine, 149)

        connection = sqlalchemy.create_engine(uri).connect()

        self.assertEqual(IPS,
                         tuple(tup[0] for tup in connection.execute(
                    "SELECT cidr from provider_fw_rules").fetchall()))
        self.assertEqual('varchar(39)',
                         connection.execute(
                "SELECT column_type FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_name='provider_fw_rules' "
                "AND table_schema='openstack_citest' "
                "AND column_name='cidr'").scalar())

    def _walk_versions(self, engine=None, snake_walk=False, downgrade=True):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                     migration.INIT_VERSION)
        self.assertEqual(migration.INIT_VERSION,
                migration_api.db_version(engine,
                                         TestMigrations.REPOSITORY))

        migration_api.upgrade(engine, TestMigrations.REPOSITORY,
                              migration.INIT_VERSION + 1)

        LOG.debug('latest version is %s' % TestMigrations.REPOSITORY.latest)

        for version in xrange(migration.INIT_VERSION + 2,
                               TestMigrations.REPOSITORY.latest + 1):
            # upgrade -> downgrade -> upgrade
            self._migrate_up(engine, version)
            if snake_walk:
                self._migrate_down(engine, version)
                self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(
                xrange(migration.INIT_VERSION + 2,
                       TestMigrations.REPOSITORY.latest + 1)):
                # downgrade -> upgrade -> downgrade
                self._migrate_down(engine, version)
                if snake_walk:
                    self._migrate_up(engine, version)
                    self._migrate_down(engine, version)

    def _migrate_down(self, engine, version):
        migration_api.downgrade(engine,
                                TestMigrations.REPOSITORY,
                                version)
        self.assertEqual(version,
                         migration_api.db_version(engine,
                                                  TestMigrations.REPOSITORY))

    def _migrate_up(self, engine, version):
        migration_api.upgrade(engine,
                              TestMigrations.REPOSITORY,
                              version)
        self.assertEqual(version,
                migration_api.db_version(engine,
                                         TestMigrations.REPOSITORY))

    def test_migration_146(self):
        name = 'name'
        az = 'custom_az'

        def _145_check():
            agg = aggregates.select(aggregates.c.id == 1).execute().first()
            self.assertEqual(name, agg.name)
            self.assertEqual(az, agg.availability_zone)

        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 145)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine
            aggregates = sqlalchemy.Table('aggregates', metadata,
                    autoload=True)

            aggregates.insert().values(id=1, availability_zone=az,
                    aggregate_name=1, name=name).execute()

            _145_check()

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 146)

            aggregate_metadata = sqlalchemy.Table('aggregate_metadata',
                    metadata, autoload=True)
            metadata = aggregate_metadata.select(aggregate_metadata.c.
                    aggregate_id == 1).execute().first()
            self.assertEqual(az, metadata['value'])

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 145)
            _145_check()

    def test_migration_147(self):
        az = 'test_zone'
        host1 = 'compute-host1'
        host2 = 'compute-host2'

        def _146_check():
            service = services.select(services.c.id == 1).execute().first()
            self.assertEqual(az, service.availability_zone)
            self.assertEqual(host1, service.host)
            service = services.select(services.c.id == 2).execute().first()
            self.assertNotEqual(az, service.availability_zone)
            service = services.select(services.c.id == 3).execute().first()
            self.assertEqual(az, service.availability_zone)
            self.assertEqual(host2, service.host)

        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 146)
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            #populate service table
            services = sqlalchemy.Table('services', metadata,
                    autoload=True)
            services.insert().values(id=1, host=host1,
                    binary='nova-compute', topic='compute', report_count=0,
                    availability_zone=az).execute()
            services.insert().values(id=2, host='sched-host',
                    binary='nova-scheduler', topic='scheduler', report_count=0,
                    availability_zone='ignore_me').execute()
            services.insert().values(id=3, host=host2,
                    binary='nova-compute', topic='compute', report_count=0,
                    availability_zone=az).execute()

            _146_check()

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 147)

            # check aggregate metadata
            aggregate_metadata = sqlalchemy.Table('aggregate_metadata',
                    metadata, autoload=True)
            aggregate_hosts = sqlalchemy.Table('aggregate_hosts',
                    metadata, autoload=True)
            metadata = aggregate_metadata.select(aggregate_metadata.c.
                    aggregate_id == 1).execute().first()
            self.assertEqual(az, metadata['value'])
            self.assertEqual(aggregate_hosts.select(
                    aggregate_hosts.c.aggregate_id == 1).execute().
                    first().host, host1)
            blank = [h for h in aggregate_hosts.select(
                    aggregate_hosts.c.aggregate_id == 2).execute()]
            self.assertEqual(blank, [])

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 146)

            _146_check()

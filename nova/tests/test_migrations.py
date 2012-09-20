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


def _mysql_get_connect_string(user="openstack_citest",
                              passwd="openstack_citest",
                              database="openstack_citest"):
    """
    Try to get a connection with a very specfic set of values, if we get
    these then we'll run the mysql tests, otherwise they are skipped
    """
    return "mysql://%(user)s:%(passwd)s@localhost/%(database)s" % locals()


def _is_mysql_avail(user="openstack_citest",
                    passwd="openstack_citest",
                    database="openstack_citest"):
    try:
        connect_uri = _mysql_get_connect_string(
            user=user, passwd=passwd, database=database)
        engine = sqlalchemy.create_engine(connect_uri)
        connection = engine.connect()
    except Exception:
        # intential catch all to handle exceptions even if we don't
        # have mysql code loaded at all.
        return False
    else:
        connection.close()
        return True


def _have_mysql():
    present = os.environ.get('NOVA_TEST_MYSQL_PRESENT')
    if present is None:
        return _is_mysql_avail()
    return present.lower() in ('', 'true')


class TestMigrations(test.TestCase):
    """Test sqlalchemy-migrate migrations"""

    TEST_DATABASES = {}
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

        # Load test databases from the config file. Only do this
        # once. No need to re-run this on each test...
        LOG.debug('config_path is %s' % TestMigrations.CONFIG_FILE_PATH)
        if not TestMigrations.TEST_DATABASES:
            if os.path.exists(TestMigrations.CONFIG_FILE_PATH):
                cp = ConfigParser.RawConfigParser()
                try:
                    cp.read(TestMigrations.CONFIG_FILE_PATH)
                    defaults = cp.defaults()
                    for key, value in defaults.items():
                        TestMigrations.TEST_DATABASES[key] = value
                    self.snake_walk = cp.getboolean('walk_style', 'snake_walk')
                except ConfigParser.ParsingError, e:
                    self.fail("Failed to read test_migrations.conf config "
                              "file. Got error: %s" % e)
            else:
                self.fail("Failed to find test_migrations.conf config "
                          "file.")

        self.engines = {}
        for key, value in TestMigrations.TEST_DATABASES.items():
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
        if "mysqlcitest" in TestMigrations.TEST_DATABASES:
            del TestMigrations.TEST_DATABASES["mysqlcitest"]
        super(TestMigrations, self).tearDown()

    def _reset_databases(self):
        def execute_cmd(cmd=None):
            status, output = commands.getstatusoutput(cmd)
            LOG.debug(output)
            self.assertEqual(0, status)
        for key, engine in self.engines.items():
            conn_string = TestMigrations.TEST_DATABASES[key]
            conn_pieces = urlparse.urlparse(conn_string)
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
                    if auth_pieces[1].strip():
                        password = auth_pieces[1]
                cmd = ("touch ~/.pgpass;"
                       "chmod 0600 ~/.pgpass;"
                       "sed -i -e"
                       "'1{s/^.*$/\*:\*:\*:%(user)s:%(password)s/};"
                       "1!d' ~/.pgpass") % locals()
                execute_cmd(cmd)
                sql = ("UPDATE pg_catalog.pg_database SET datallowconn=false "
                       "WHERE datname='%(database)s';") % locals()
                cmd = ("psql -U%(user)s -h%(host)s -c\"%(sql)s\"") % locals()
                execute_cmd(cmd)
                sql = ("SELECT pg_catalog.pg_terminate_backend(procpid) "
                       "FROM pg_catalog.pg_stat_activity "
                       "WHERE datname='%(database)s';") % locals()
                cmd = ("psql -U%(user)s -h%(host)s -c\"%(sql)s\"") % locals()
                execute_cmd(cmd)
                sql = ("drop database if exists %(database)s;") % locals()
                cmd = ("psql -U%(user)s -h%(host)s -c\"%(sql)s\"") % locals()
                execute_cmd(cmd)
                sql = ("create database %(database)s;") % locals()
                cmd = ("psql -U%(user)s -h%(host)s -c\"%(sql)s\"") % locals()
                execute_cmd(cmd)

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
        if _is_mysql_avail(user="openstack_cifail"):
            self.fail("Shouldn't have connected")

    @test.skip_unless(_have_mysql(), "mysql not available")
    def test_mysql_innodb(self):
        """
        Test that table creation on mysql only builds InnoDB tables
        """
        # add this to the global lists to make reset work with it, it's removed
        # automaticaly in tearDown so no need to clean it up here.
        connect_string = _mysql_get_connect_string()
        engine = sqlalchemy.create_engine(connect_string)
        self.engines["mysqlcitest"] = engine
        TestMigrations.TEST_DATABASES["mysqlcitest"] = connect_string

        # build a fully populated mysql database with all the tables
        self._reset_databases()
        self._walk_versions(engine, False, False)

        uri = _mysql_get_connect_string(database="information_schema")
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
                self._migrate_down(engine, version - 1)
                self._migrate_up(engine, version)

        if downgrade:
            # Now walk it back down to 0 from the latest, testing
            # the downgrade paths.
            for version in reversed(
                xrange(migration.INIT_VERSION + 1,
                       TestMigrations.REPOSITORY.latest)):
                # downgrade -> upgrade -> downgrade
                self._migrate_down(engine, version)
                if snake_walk:
                    self._migrate_up(engine, version + 1)
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

    def test_migration_98(self):
        """Test that migration 98 runs

        This test exists to prove bug 1047633 has been fixed
        """
        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 97)

            # Set up a single volume, values don't matter
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine
            volumes = sqlalchemy.Table('volumes', metadata, autoload=True)
            vol_id = '9db3c2e5-8cac-4e94-9e6c-b5f750736727'
            volumes.insert().values(id=vol_id).execute()

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 98)
            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 97)

    def test_migration_91(self):
        """Test that migration 91 works correctly.

        This test prevents regression of bugs 1052244 and 1052220.
        """
        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 90)

            vol1_id = '10'
            vol1_uuid = '9db3c2e5-8cac-4e94-9e6c-b5f750736727'

            vol2_id = '11'
            vol2_uuid = 'fb17fb5a-ca3d-4bba-8903-fc776ea81d78'

            snap_id = '7'
            snap_uuid = 'a87e5108-8a2b-4c89-be96-0e8760db2c6a'

            inst_id = '0ec45d38-aefd-4c42-a209-361e848240b7'

            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine

            instances = sqlalchemy.Table('instances', metadata, autoload=True)
            volumes = sqlalchemy.Table('volumes', metadata, autoload=True)
            sm_flavors = sqlalchemy.Table(
                    'sm_flavors', metadata, autoload=True)
            sm_backend_config = sqlalchemy.Table(
                    'sm_backend_config', metadata, autoload=True)
            sm_volume = sqlalchemy.Table(
                    'sm_volume', metadata, autoload=True)
            volume_mappings = sqlalchemy.Table(
                    'volume_id_mappings', metadata, autoload=True)
            iscsi_targets = sqlalchemy.Table(
                    'iscsi_targets', metadata, autoload=True)
            volume_metadata = sqlalchemy.Table(
                    'volume_metadata', metadata, autoload=True)
            snapshots = sqlalchemy.Table('snapshots', metadata, autoload=True)
            snapshot_mappings = sqlalchemy.Table(
                    'snapshot_id_mappings', metadata, autoload=True)
            block_device_mapping = sqlalchemy.Table(
                    'block_device_mapping', metadata, autoload=True)

            volumes.insert().values(id=vol1_id).execute()
            volume_mappings.insert() \
                    .values(id=vol1_id, uuid=vol1_uuid).execute()
            snapshots.insert().values(id=snap_id, volume_id=vol1_id).execute()
            snapshot_mappings.insert() \
                    .values(id=snap_id, uuid=snap_uuid).execute()
            volumes.insert().values(id=vol2_id, snapshot_id=snap_id).execute()
            volume_mappings.insert() \
                    .values(id=vol2_id, uuid=vol2_uuid).execute()
            sm_flavors.insert().values(id=7).execute()
            sm_backend_config.insert().values(id=7, flavor_id=7).execute()
            sm_volume.insert().values(id=vol1_id, backend_id=7).execute()
            volume_metadata.insert().values(id=7, volume_id=vol1_id).execute()
            iscsi_targets.insert().values(id=7, volume_id=vol1_id).execute()
            instances.insert().values(id=7, uuid=inst_id).execute()
            block_device_mapping.insert()\
                    .values(id=7, volume_id=vol1_id, instance_uuid=inst_id) \
                    .execute()

            vols = volumes.select().execute().fetchall()
            self.assertEqual(set([vol.id for vol in vols]),
                             set([vol1_id, vol2_id]))
            self.assertEqual(snap_id, vols[1].snapshot_id)

            query = volume_metadata.select(volume_metadata.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            query = iscsi_targets.select(iscsi_targets.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            query = block_device_mapping.select(block_device_mapping.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            snaps = sqlalchemy.select([snapshots.c.id]).execute().fetchall()
            self.assertEqual(set([snap.id for snap in snaps]),
                             set([snap_id]))

            sm_vols = sqlalchemy.select([sm_volume.c.id]).execute().fetchall()
            self.assertEqual(set([sm_vol.id for sm_vol in sm_vols]),
                             set([vol1_id]))

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 91)

            vols = volumes.select().execute().fetchall()
            self.assertEqual(set([vol.id for vol in vols]),
                             set([vol1_uuid, vol2_uuid]))
            self.assertEqual(snap_uuid, vols[1].snapshot_id)

            query = volume_metadata.select(volume_metadata.c.id == 7)
            self.assertEqual(vol1_uuid, query.execute().fetchone().volume_id)

            query = iscsi_targets.select(iscsi_targets.c.id == 7)
            self.assertEqual(vol1_uuid, query.execute().fetchone().volume_id)

            query = block_device_mapping.select(block_device_mapping.c.id == 7)
            self.assertEqual(vol1_uuid, query.execute().fetchone().volume_id)

            snaps = sqlalchemy.select([snapshots.c.id]).execute().fetchall()
            self.assertEqual(set([snap.id for snap in snaps]),
                             set([snap_uuid]))

            sm_vols = sqlalchemy.select([sm_volume.c.id]).execute().fetchall()
            self.assertEqual(set([sm_vol.id for sm_vol in sm_vols]),
                             set([vol1_uuid]))

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 90)

            vols = volumes.select().execute().fetchall()
            self.assertEqual(set([vol.id for vol in vols]),
                             set([vol1_id, vol2_id]))
            self.assertEqual(snap_id, vols[1].snapshot_id)

            query = volume_metadata.select(volume_metadata.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            query = iscsi_targets.select(iscsi_targets.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            query = block_device_mapping.select(block_device_mapping.c.id == 7)
            self.assertEqual(vol1_id, query.execute().fetchone().volume_id)

            snaps = sqlalchemy.select([snapshots.c.id]).execute().fetchall()
            self.assertEqual(set([snap.id for snap in snaps]),
                             set([snap_id]))

            sm_vols = sqlalchemy.select([sm_volume.c.id]).execute().fetchall()
            self.assertEqual(set([sm_vol.id for sm_vol in sm_vols]),
                             set([vol1_id]))

    def test_migration_111(self):
        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 110)

            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine
            aggregate_hosts = sqlalchemy.Table('aggregate_hosts', metadata,
                    autoload=True)
            host = 'host'
            aggregate_hosts.insert().values(id=1,
                    aggregate_id=1, host=host).execute()

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 111)
            agg = sqlalchemy.select([aggregate_hosts.c.host]).execute().first()
            self.assertEqual(host, agg.host)
            aggregate_hosts.insert().values(id=2,
                    aggregate_id=2, host=host).execute()

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 111)
            agg = sqlalchemy.select([aggregate_hosts.c.host]).execute().first()
            self.assertEqual(host, agg.host)

    def test_migration_133(self):
        for key, engine in self.engines.items():
            migration_api.version_control(engine, TestMigrations.REPOSITORY,
                                          migration.INIT_VERSION)
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 132)

            # Set up a single volume, values don't matter
            metadata = sqlalchemy.schema.MetaData()
            metadata.bind = engine
            aggregates = sqlalchemy.Table('aggregates', metadata,
                    autoload=True)
            name = 'name'
            aggregates.insert().values(id=1, availability_zone='nova',
                    aggregate_name=1, name=name).execute()

            migration_api.upgrade(engine, TestMigrations.REPOSITORY, 133)
            aggregates.insert().values(id=2, availability_zone='nova',
                    aggregate_name=2, name=name).execute()

            migration_api.downgrade(engine, TestMigrations.REPOSITORY, 132)
            agg = sqlalchemy.select([aggregates.c.name]).execute().first()
            self.assertEqual(name, agg.name)

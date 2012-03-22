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

import ConfigParser
import commands
import os
import unittest
import urlparse

from migrate.versioning import repository
import sqlalchemy

import nova.db.sqlalchemy.migrate_repo
from nova.db.sqlalchemy.migration import versioning_api as migration_api
from nova import log as logging
from nova import test

LOG = logging.getLogger('nova.tests.test_migrations')


class TestMigrations(unittest.TestCase):
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
        super(TestMigrations, self).tearDown()

        # We destroy the test data store between each test case,
        # and recreate it, which ensures that we have no side-effects
        # from the tests
        self._reset_databases()

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
                        password = "-p%s" % auth_pieces[1]
                sql = ("drop database if exists %(database)s; "
                       "create database %(database)s;") % locals()
                cmd = ("mysql -u%(user)s %(password)s -h%(host)s "
                       "-e\"%(sql)s\"") % locals()
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

    def _walk_versions(self, engine=None, snake_walk=False):
        # Determine latest version script from the repo, then
        # upgrade from 1 through to the latest, with no data
        # in the databases. This just checks that the schema itself
        # upgrades successfully.

        # Place the database under version control
        migration_api.version_control(engine, TestMigrations.REPOSITORY)
        self.assertEqual(0,
                migration_api.db_version(engine,
                                         TestMigrations.REPOSITORY))

        LOG.debug('latest version is %s' % TestMigrations.REPOSITORY.latest)

        for version in xrange(1, TestMigrations.REPOSITORY.latest + 1):
            # upgrade -> downgrade -> upgrade
            migration_api.upgrade(engine, TestMigrations.REPOSITORY, version)
            self.assertEqual(version,
                    migration_api.db_version(engine,
                                             TestMigrations.REPOSITORY))
            if snake_walk:
                migration_api.downgrade(engine,
                                        TestMigrations.REPOSITORY,
                                        version - 1)
                self.assertEqual(version - 1,
                        migration_api.db_version(engine,
                                                 TestMigrations.REPOSITORY))
                migration_api.upgrade(engine,
                                      TestMigrations.REPOSITORY,
                                      version)
                self.assertEqual(version,
                        migration_api.db_version(engine,
                                                 TestMigrations.REPOSITORY))

        # Now walk it back down to 0 from the latest, testing
        # the downgrade paths.
        for version in reversed(
            xrange(0, TestMigrations.REPOSITORY.latest)):
            # downgrade -> upgrade -> downgrade
            migration_api.downgrade(engine, TestMigrations.REPOSITORY, version)
            self.assertEqual(version,
                    migration_api.db_version(engine,
                                             TestMigrations.REPOSITORY))
            if snake_walk:
                migration_api.upgrade(engine,
                                      TestMigrations.REPOSITORY,
                                      version + 1)
                self.assertEqual(version + 1,
                        migration_api.db_version(engine,
                                                 TestMigrations.REPOSITORY))
                migration_api.downgrade(engine,
                                        TestMigrations.REPOSITORY,
                                        version)
                self.assertEqual(version,
                        migration_api.db_version(engine,
                                                 TestMigrations.REPOSITORY))

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
Tests for database migrations.
There are "opportunistic" tests which allows testing against all 3 databases
(sqlite in memory, mysql, pg) in a properly configured unit test environment.

For the opportunistic testing you need to set up db's named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost. The
test will then use that db and u/p combo to run the tests.

For postgres on Ubuntu this can be done with the following commands::

| sudo -u postgres psql
| postgres=# create user openstack_citest with createdb login password
|       'openstack_citest';
| postgres=# create database openstack_citest with owner openstack_citest;

"""

import glob
import os

from migrate.versioning import repository
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as oslodbutils
from oslotest import timeout
import sqlalchemy
import sqlalchemy.exc
import testtools

from nova.db import migration
from nova.db.sqlalchemy import migrate_repo
from nova.db.sqlalchemy import migration as sa_migration
from nova.db.sqlalchemy import models
from nova import test
from nova.tests import fixtures as nova_fixtures

# TODO(sdague): no tests in the nova/tests tree should inherit from
# base test classes in another library. This causes all kinds of havoc
# in these doing things incorrectly for what we need in subunit
# reporting. This is a long unwind, but should be done in the future
# and any code needed out of oslo_db should be exported / accessed as
# a fixture.


class NovaMigrationsCheckers(test_migrations.ModelsMigrationsSync,
                             test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    TIMEOUT_SCALING_FACTOR = 4

    @property
    def INIT_VERSION(self):
        return migration.db_initial_version()

    @property
    def REPOSITORY(self):
        return repository.Repository(
            os.path.abspath(os.path.dirname(migrate_repo.__file__)))

    @property
    def migration_api(self):
        return sa_migration.versioning_api

    @property
    def migrate_engine(self):
        return self.engine

    def setUp(self):
        # NOTE(sdague): the oslo_db base test case completely
        # invalidates our logging setup, we actually have to do that
        # before it is called to keep this from vomitting all over our
        # test output.
        self.useFixture(nova_fixtures.StandardLogging())

        super(NovaMigrationsCheckers, self).setUp()
        # The Timeout fixture picks up env.OS_TEST_TIMEOUT, defaulting to 0.
        self.useFixture(timeout.Timeout(
            scaling_factor=self.TIMEOUT_SCALING_FACTOR))
        self.engine = enginefacade.writer.get_engine()

    def assertColumnExists(self, engine, table_name, column):
        self.assertTrue(oslodbutils.column_exists(engine, table_name, column),
                        'Column %s.%s does not exist' % (table_name, column))

    def assertColumnNotExists(self, engine, table_name, column):
        self.assertFalse(oslodbutils.column_exists(engine, table_name, column),
                        'Column %s.%s should not exist' % (table_name, column))

    def assertTableNotExists(self, engine, table):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          oslodbutils.get_table, engine, table)

    def assertIndexExists(self, engine, table_name, index):
        self.assertTrue(oslodbutils.index_exists(engine, table_name, index),
                        'Index %s on table %s does not exist' %
                        (index, table_name))

    def assertIndexNotExists(self, engine, table_name, index):
        self.assertFalse(oslodbutils.index_exists(engine, table_name, index),
                         'Index %s on table %s should not exist' %
                         (index, table_name))

    def assertIndexMembers(self, engine, table, index, members):
        # NOTE(johannes): Order of columns can matter. Most SQL databases
        # can use the leading columns for optimizing queries that don't
        # include all of the covered columns.
        self.assertIndexExists(engine, table, index)

        t = oslodbutils.get_table(engine, table)
        index_columns = None
        for idx in t.indexes:
            if idx.name == index:
                index_columns = [c.name for c in idx.columns]
                break

        self.assertEqual(members, index_columns)

    # Implementations for ModelsMigrationsSync
    def db_sync(self, engine):
        with mock.patch.object(sa_migration, 'get_engine',
                               return_value=engine):
            sa_migration.db_sync()

    def get_engine(self, context=None):
        return self.migrate_engine

    def get_metadata(self):
        return models.BASE.metadata

    def include_object(self, object_, name, type_, reflected, compare_to):
        if type_ == 'table':
            # migrate_version is a sqlalchemy-migrate control table and
            # isn't included in the model. shadow_* are generated from
            # the model and have their own tests to ensure they don't
            # drift.
            if name == 'migrate_version' or name.startswith('shadow_'):
                return False

        return True

    def _skippable_migrations(self):
        special = [
            self.INIT_VERSION + 1,
        ]

        train_placeholders = list(range(403, 408))
        ussuri_placeholders = list(range(408, 413))
        victoria_placeholders = list(range(413, 418))

        return (special +
                train_placeholders +
                ussuri_placeholders +
                victoria_placeholders)

    def migrate_up(self, version, with_data=False):
        if with_data:
            check = getattr(self, "_check_%03d" % version, None)
            if version not in self._skippable_migrations():
                self.assertIsNotNone(check,
                                     ('DB Migration %i does not have a '
                                      'test. Please add one!') % version)

        # NOTE(danms): This is a list of migrations where we allow dropping
        # things. The rules for adding things here are very very specific.
        # Chances are you don't meet the critera.
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE
        exceptions = [
            # The base migration can do whatever it likes
            self.INIT_VERSION + 1,
        ]
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE

        if version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with nova_fixtures.BannedDBSchemaOperations(banned):
            super(NovaMigrationsCheckers, self).migrate_up(version, with_data)

    def filter_metadata_diff(self, diff):
        # Overriding the parent method to decide on certain attributes
        # that maybe present in the DB but not in the models.py

        def removed_column(element):
            # Define a whitelist of columns that would be removed from the
            # DB at a later release.
            # NOTE(Luyao) The vpmems column was added to the schema in train,
            # and removed from the model in train.
            column_whitelist = {
                'instances': ['internal_id'],
                'instance_extra': ['vpmems'],
            }

            if element[0] != 'remove_column':
                return False

            table_name, column = element[2], element[3]
            return (
                table_name in column_whitelist and
                column.name in column_whitelist[table_name]
            )

        return [element for element in diff if not removed_column(element)]

    def test_walk_versions(self):
        self.walk_versions(snake_walk=False, downgrade=False)


class TestNovaMigrationsSQLite(NovaMigrationsCheckers,
                               test_fixtures.OpportunisticDBTestMixin,
                               testtools.TestCase):
    pass


class TestNovaMigrationsMySQL(NovaMigrationsCheckers,
                              test_fixtures.OpportunisticDBTestMixin,
                              testtools.TestCase):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture

    def test_innodb_tables(self):
        with mock.patch.object(sa_migration, 'get_engine',
                               return_value=self.migrate_engine):
            sa_migration.db_sync()

        total = self.migrate_engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = '%(database)s'" %
            {'database': self.migrate_engine.url.database})
        self.assertGreater(total.scalar(), 0, "No tables found. Wrong schema?")

        noninnodb = self.migrate_engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='%(database)s' "
            "AND ENGINE != 'InnoDB' "
            "AND TABLE_NAME != 'migrate_version'" %
            {'database': self.migrate_engine.url.database})
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)


class TestNovaMigrationsPostgreSQL(NovaMigrationsCheckers,
                                   test_fixtures.OpportunisticDBTestMixin,
                                   testtools.TestCase):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class ProjectTestCase(test.NoDBTestCase):

    def test_no_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../../')
        # Walk both the nova_api and nova (cell) database migrations.
        includes_downgrade = []
        for subdir in ('api_migrations', ''):
            py_glob = os.path.join(topdir, "db", "sqlalchemy", subdir,
                                   "migrate_repo", "versions", "*.py")
            for path in glob.iglob(py_glob):
                has_upgrade = False
                has_downgrade = False
                with open(path, "r") as f:
                    for line in f:
                        if 'def upgrade(' in line:
                            has_upgrade = True
                        if 'def downgrade(' in line:
                            has_downgrade = True

                    if has_upgrade and has_downgrade:
                        fname = os.path.basename(path)
                        includes_downgrade.append(fname)

        helpful_msg = ("The following migrations have a downgrade "
                       "which is not supported:"
                       "\n\t%s" % '\n\t'.join(sorted(includes_downgrade)))
        self.assertFalse(includes_downgrade, helpful_msg)

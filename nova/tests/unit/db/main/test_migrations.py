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

from alembic import command as alembic_api
from alembic import script as alembic_script
from migrate.versioning import api as migrate_api
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as oslodbutils
from oslo_log import log as logging
import sqlalchemy
import sqlalchemy.exc
import testtools

from nova.db.main import models
from nova.db import migration
from nova import test

LOG = logging.getLogger(__name__)


class NovaModelsMigrationsSync(test_migrations.ModelsMigrationsSync):
    """Test sqlalchemy-migrate migrations."""

    def setUp(self):
        super().setUp()
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

    def db_sync(self, engine):
        with mock.patch.object(migration, '_get_engine', return_value=engine):
            migration.db_sync(database='main')

    def get_engine(self):
        return self.engine

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


class TestModelsSyncSQLite(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    pass


class TestModelsSyncMySQL(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture

    def test_innodb_tables(self):
        self.db_sync(self.get_engine())

        total = self.engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = '%(database)s'" %
            {'database': self.engine.url.database})
        self.assertGreater(total.scalar(), 0, "No tables found. Wrong schema?")

        noninnodb = self.engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='%(database)s' "
            "AND ENGINE != 'InnoDB' "
            "AND TABLE_NAME != 'migrate_version'" %
            {'database': self.engine.url.database})
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)


class TestModelsSyncPostgreSQL(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class NovaModelsMigrationsLegacySync(NovaModelsMigrationsSync):
    """Test that the models match the database after old migrations are run."""

    def db_sync(self, engine):
        # the 'nova.db.migration.db_sync' method will not use the legacy
        # sqlalchemy-migrate-based migration flow unless the database is
        # already controlled with sqlalchemy-migrate, so we need to manually
        # enable version controlling with this tool to test this code path
        repository = migration._find_migrate_repo(database='main')
        migrate_api.version_control(
            engine, repository, migration.MIGRATE_INIT_VERSION['main'])

        # now we can apply migrations as expected and the legacy path will be
        # followed
        super().db_sync(engine)


class TestModelsLegacySyncSQLite(
    NovaModelsMigrationsLegacySync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    pass


class TestModelsLegacySyncMySQL(
    NovaModelsMigrationsLegacySync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestModelsLegacySyncPostgreSQL(
    NovaModelsMigrationsLegacySync,
    test_fixtures.OpportunisticDBTestMixin,
    testtools.TestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class NovaMigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin, test.NoDBTestCase,
):

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        self.config = migration._find_alembic_conf('main')
        self.init_version = migration.ALEMBIC_INIT_VERSION['main']

    def _migrate_up(self, revision):
        if revision == self.init_version:  # no tests for the initial revision
            return

        self.assertIsNotNone(
            getattr(self, '_check_%s' % revision, None),
            (
                'API DB Migration %s does not have a test; you must add one'
            ) % revision,
        )
        alembic_api.upgrade(self.config, revision)

    def test_single_base_revision(self):
        """Ensure we only have a single base revision.

        There's no good reason for us to have diverging history, so validate
        that only one base revision exists. This will prevent simple errors
        where people forget to specify the base revision. If this fail for your
        change, look for migrations that do not have a 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_bases()))

    def test_single_head_revision(self):
        """Ensure we only have a single head revision.

        There's no good reason for us to have diverging history, so validate
        that only one head revision exists. This will prevent merge conflicts
        adding additional head revision points. If this fail for your change,
        look for migrations with the same 'revises' line in them.
        """
        script = alembic_script.ScriptDirectory.from_config(self.config)
        self.assertEqual(1, len(script.get_heads()))

    def test_walk_versions(self):
        with self.engine.begin() as connection:
            self.config.attributes['connection'] = connection
            script = alembic_script.ScriptDirectory.from_config(self.config)
            for revision_script in script.walk_revisions():
                revision = revision_script.revision
                LOG.info('Testing revision %s', revision)
                self._migrate_up(revision)

    def test_db_version_alembic(self):
        migration.db_sync(database='main')

        head = alembic_script.ScriptDirectory.from_config(
            self.config).get_current_head()
        self.assertEqual(head, migration.db_version(database='main'))


class TestMigrationsWalkSQLite(
    NovaMigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test.NoDBTestCase,
):
    pass


class TestMigrationsWalkMySQL(
    NovaMigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test.NoDBTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestMigrationsWalkPostgreSQL(
    NovaMigrationsWalk,
    test_fixtures.OpportunisticDBTestMixin,
    test.NoDBTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class ProjectTestCase(test.NoDBTestCase):

    def test_no_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../../')
        # Walk both the nova_api and nova (cell) database migrations.
        includes_downgrade = []
        for directory in (
            os.path.join(topdir, 'db', 'main', 'legacy_migrations'),
            os.path.join(topdir, 'db', 'api', 'legacy_migrations'),
        ):
            py_glob = os.path.join(directory, 'versions', '*.py')
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

        helpful_msg = (
            "The following migrations have a downgrade "
            "which is not supported:"
            "\n\t%s" % '\n\t'.join(sorted(includes_downgrade)))
        self.assertFalse(includes_downgrade, helpful_msg)

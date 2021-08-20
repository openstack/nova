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

"""Tests for database migrations for the main database.

These are "opportunistic" tests which allow testing against all three databases
(sqlite in memory, mysql, pg) in a properly configured unit test environment.

For the opportunistic testing you need to set up DBs named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost. The
test will then use that DB and username/password combo to run the tests. Refer
to the 'tools/test-setup.sh' for an example of how to configure this.
"""

from alembic import command as alembic_api
from alembic import script as alembic_script
import fixtures
from migrate.versioning import api as migrate_api
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as oslodbutils
from oslo_log.fixture import logging_error as log_fixture
from oslo_log import log as logging
from oslotest import base
import sqlalchemy as sa
import sqlalchemy.exc

from nova.db.main import models
from nova.db import migration
from nova import test
from nova.tests import fixtures as nova_fixtures

LOG = logging.getLogger(__name__)


class NovaModelsMigrationsSync(test_migrations.ModelsMigrationsSync):
    """Test sqlalchemy-migrate migrations."""

    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

    def setUp(self):
        # Ensure BaseTestCase's ConfigureLogging fixture is disabled since
        # we're using our own (StandardLogging).
        with fixtures.EnvironmentVariable('OS_LOG_CAPTURE', '0'):
            super().setUp()

        self.useFixture(log_fixture.get_logging_handle_error_fixture())
        self.useFixture(nova_fixtures.WarningsFixture())
        self.useFixture(nova_fixtures.StandardLogging())

        self.engine = enginefacade.writer.get_engine()

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

            # Define a whitelist of tables that will be removed from the DB in
            # a later release and don't have a corresponding model anymore.

            return name not in models.REMOVED_TABLES

        return True

    def filter_metadata_diff(self, diff):
        # Filter out diffs that shouldn't cause a sync failure.
        new_diff = []

        for element in diff:
            if isinstance(element, list):
                # modify_nullable is a list
                new_diff.append(element)
            else:
                # tuple with action as first element. Different actions have
                # different tuple structures.
                if element[0] == 'add_fk':
                    fkey = element[1]
                    tablename = fkey.table.name
                    column_keys = fkey.column_keys
                    if (tablename, column_keys) in models.REMOVED_FKEYS:
                        continue
                if element[0] == 'remove_column':
                    table = element[2]
                    column = element[3].name
                    if (table, column) in models.REMOVED_COLUMNS:
                        continue

                new_diff.append(element)

        return new_diff


class TestModelsSyncSQLite(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    base.BaseTestCase,
):
    pass


class TestModelsSyncMySQL(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture

    def test_innodb_tables(self):
        self.db_sync(self.get_engine())

        with self.engine.connect() as conn:
            total = conn.execute(
                sa.text(
                    "SELECT count(*) "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = :database"
                ),
                {'database': self.engine.url.database},
            )
        self.assertGreater(total.scalar(), 0, "No tables found. Wrong schema?")

        with self.engine.connect() as conn:
            noninnodb = conn.execute(
                sa.text(
                    "SELECT count(*) "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = :database "
                    "AND ENGINE != 'InnoDB' "
                    "AND TABLE_NAME != 'migrate_version'"
                ),
                {'database': self.engine.url.database},
            )
            count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)


class TestModelsSyncPostgreSQL(
    NovaModelsMigrationsSync,
    test_fixtures.OpportunisticDBTestMixin,
    base.BaseTestCase,
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
    base.BaseTestCase,
):
    pass


class TestModelsLegacySyncMySQL(
    NovaModelsMigrationsLegacySync,
    test_fixtures.OpportunisticDBTestMixin,
    base.BaseTestCase,
):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestModelsLegacySyncPostgreSQL(
    NovaModelsMigrationsLegacySync,
    test_fixtures.OpportunisticDBTestMixin,
    base.BaseTestCase,
):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class NovaMigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin, test.NoDBTestCase,
):

    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        self.config = migration._find_alembic_conf('main')
        self.init_version = migration.ALEMBIC_INIT_VERSION['main']

    def assertIndexExists(self, connection, table_name, index):
        self.assertTrue(
            oslodbutils.index_exists(connection, table_name, index),
            'Index %s on table %s should not exist' % (index, table_name),
        )

    def assertIndexNotExists(self, connection, table_name, index):
        self.assertFalse(
            oslodbutils.index_exists(connection, table_name, index),
            'Index %s on table %s should not exist' % (index, table_name),
        )

    def _migrate_up(self, connection, revision):
        if revision == self.init_version:  # no tests for the initial revision
            alembic_api.upgrade(self.config, revision)
            return

        self.assertIsNotNone(
            getattr(self, '_check_%s' % revision, None),
            (
                'Main DB Migration %s does not have a test; you must add one'
            ) % revision,
        )

        pre_upgrade = getattr(self, '_pre_upgrade_%s' % revision, None)
        if pre_upgrade:
            pre_upgrade(connection)

        alembic_api.upgrade(self.config, revision)

        post_upgrade = getattr(self, '_check_%s' % revision, None)
        if post_upgrade:
            post_upgrade(connection)

    def _pre_upgrade_16f1fbcab42b(self, connection):
        self.assertIndexExists(
            connection, 'shadow_instance_extra', 'shadow_instance_extra_idx',
        )
        self.assertIndexExists(
            connection, 'shadow_migrations', 'shadow_migrations_uuid',
        )

    def _check_16f1fbcab42b(self, connection):
        self.assertIndexNotExists(
            connection, 'shadow_instance_extra', 'shadow_instance_extra_idx',
        )
        self.assertIndexNotExists(
            connection, 'shadow_migrations', 'shadow_migrations_uuid',
        )

        # no check for the MySQL-specific change

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
            revisions = [x.revision for x in script.walk_revisions()]

            # for some reason, 'walk_revisions' gives us the revisions in
            # reverse chronological order so we have to invert this
            revisions.reverse()
            self.assertEqual(revisions[0], self.init_version)

            for revision in revisions:
                LOG.info('Testing revision %s', revision)
                self._migrate_up(connection, revision)

    def test_db_version_alembic(self):
        engine = enginefacade.writer.get_engine()

        with mock.patch.object(migration, '_get_engine', return_value=engine):
            migration.db_sync(database='main')

            script = alembic_script.ScriptDirectory.from_config(self.config)
            head = script.get_current_head()
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

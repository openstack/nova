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

"""Tests for database migrations.

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

from alembic import command as alembic_api
from alembic import script as alembic_script
from migrate.versioning import api as migrate_api
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_log import log as logging
import testtools

from nova.db.api import models
from nova.db import migration
from nova import test

LOG = logging.getLogger(__name__)


class NovaModelsMigrationsSync(test_migrations.ModelsMigrationsSync):
    """Test that the models match the database after migrations are run."""

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()

    def db_sync(self, engine):
        with mock.patch.object(migration, '_get_engine', return_value=engine):
            migration.db_sync(database='api')

    def get_engine(self):
        return self.engine

    def get_metadata(self):
        return models.BASE.metadata

    def include_object(self, object_, name, type_, reflected, compare_to):
        if type_ == 'table':
            # migrate_version is a sqlalchemy-migrate control table and
            # isn't included in the model.
            if name == 'migrate_version':
                return False

        return True

    def filter_metadata_diff(self, diff):
        # Filter out diffs that shouldn't cause a sync failure.
        new_diff = []

        # Define a whitelist of ForeignKeys that exist on the model but not in
        # the database. They will be removed from the model at a later time.
        fkey_whitelist = {'build_requests': ['request_spec_id']}

        # Define a whitelist of columns that will be removed from the
        # DB at a later release and aren't on a model anymore.

        column_whitelist = {
            'build_requests': [
                'vm_state', 'instance_metadata',
                'display_name', 'access_ip_v6', 'access_ip_v4', 'key_name',
                'locked_by', 'image_ref', 'progress', 'request_spec_id',
                'info_cache', 'user_id', 'task_state', 'security_groups',
                'config_drive',
            ],
            'resource_providers': ['can_host'],
        }

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
                    if (
                        tablename in fkey_whitelist and
                        column_keys == fkey_whitelist[tablename]
                    ):
                        continue
                elif element[0] == 'remove_column':
                    tablename = element[2]
                    column = element[3]
                    if (
                        tablename in column_whitelist and
                        column.name in column_whitelist[tablename]
                    ):
                        continue

                new_diff.append(element)

        return new_diff


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
        repository = migration._find_migrate_repo(database='api')
        migrate_api.version_control(
            engine, repository, migration.MIGRATE_INIT_VERSION['api'])

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
        self.config = migration._find_alembic_conf('api')
        self.init_version = migration.ALEMBIC_INIT_VERSION['api']

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
        migration.db_sync(database='api')

        head = alembic_script.ScriptDirectory.from_config(
            self.config).get_current_head()
        self.assertEqual(head, migration.db_version(database='api'))


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

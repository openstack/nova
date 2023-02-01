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

"""Tests for database migrations for the API database.

These are "opportunistic" tests which allow testing against all three databases
(sqlite in memory, mysql, pg) in a properly configured unit test environment.

For the opportunistic testing you need to set up DBs named 'openstack_citest'
with user 'openstack_citest' and password 'openstack_citest' on localhost. The
test will then use that DB and username/password combo to run the tests. Refer
to the 'tools/test-setup.sh' for an example of how to configure this.
"""

from unittest import mock

from alembic import command as alembic_api
from alembic import script as alembic_script
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_log import log as logging
import sqlalchemy
import testtools

from nova.db.api import models
from nova.db import migration
from nova import test

LOG = logging.getLogger(__name__)


class NovaModelsMigrationsSync(test_migrations.ModelsMigrationsSync):
    """Test that the models match the database after migrations are run."""

    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

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
                elif element[0] == 'remove_column':
                    table = element[2]
                    column = element[3].name
                    if (table, column) in models.REMOVED_COLUMNS:
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


class NovaMigrationsWalk(
    test_fixtures.OpportunisticDBTestMixin, test.NoDBTestCase,
):

    # Migrations can take a long time, particularly on underpowered CI nodes.
    # Give them some breathing room.
    TIMEOUT_SCALING_FACTOR = 4

    def setUp(self):
        super().setUp()
        self.engine = enginefacade.writer.get_engine()
        self.config = migration._find_alembic_conf('api')
        self.init_version = 'd67eeaabee36'

    def _migrate_up(self, connection, revision):
        if revision == self.init_version:  # no tests for the initial revision
            alembic_api.upgrade(self.config, revision)
            return

        self.assertIsNotNone(
            getattr(self, '_check_%s' % revision, None),
            (
                'API DB Migration %s does not have a test; you must add one'
            ) % revision,
        )

        pre_upgrade = getattr(self, '_pre_upgrade_%s' % revision, None)
        if pre_upgrade:
            pre_upgrade(connection)

        alembic_api.upgrade(self.config, revision)

        post_upgrade = getattr(self, '_check_%s' % revision, None)
        if post_upgrade:
            post_upgrade(connection)

    _b30f573d3377_removed_columns = {
        'access_ip_v4',
        'access_ip_v6',
        'config_drive',
        'display_name',
        'image_ref',
        'info_cache',
        'instance_metadata',
        'key_name',
        'locked_by',
        'progress',
        'request_spec_id',
        'security_groups',
        'task_state',
        'user_id',
        'vm_state',
    }

    def _pre_upgrade_b30f573d3377(self, connection):
        # we use the inspector here rather than oslo_db.utils.column_exists,
        # since the latter will create a new connection
        inspector = sqlalchemy.inspect(connection)
        columns = [x['name'] for x in inspector.get_columns('build_requests')]
        for removed_column in self._b30f573d3377_removed_columns:
            self.assertIn(removed_column, columns)

    def _check_b30f573d3377(self, connection):
        # we use the inspector here rather than oslo_db.utils.column_exists,
        # since the latter will create a new connection
        inspector = sqlalchemy.inspect(connection)
        columns = [x['name'] for x in inspector.get_columns('build_requests')]
        for removed_column in self._b30f573d3377_removed_columns:
            self.assertNotIn(removed_column, columns)

    def _check_cdeec0c85668(self, connection):
        # the table optionally existed: there's no way to check for its
        # removal without creating it first, which is dumb
        pass

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
            migration.db_sync(database='api')

            script = alembic_script.ScriptDirectory.from_config(self.config)
            head = script.get_current_head()
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

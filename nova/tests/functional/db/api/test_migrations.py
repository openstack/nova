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

import os

from migrate.versioning import repository
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
import testtools

from nova.db import migration
from nova.db.sqlalchemy.api_migrations import migrate_repo
from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import migration as sa_migration
from nova import test
from nova.tests import fixtures as nova_fixtures


class NovaAPIModelsSync(test_migrations.ModelsMigrationsSync):
    """Test that the models match the database after migrations are run."""

    def setUp(self):
        super(NovaAPIModelsSync, self).setUp()
        self.engine = enginefacade.writer.get_engine()

    def db_sync(self, engine):
        with mock.patch.object(sa_migration, 'get_engine',
                               return_value=engine):
            sa_migration.db_sync(database='api')

    @property
    def migrate_engine(self):
        return self.engine

    def get_engine(self, context=None):
        return self.migrate_engine

    def get_metadata(self):
        return api_models.API_BASE.metadata

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
                'build_requests': ['vm_state', 'instance_metadata',
                    'display_name', 'access_ip_v6', 'access_ip_v4', 'key_name',
                    'locked_by', 'image_ref', 'progress', 'request_spec_id',
                    'info_cache', 'user_id', 'task_state', 'security_groups',
                    'config_drive'],
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
                    if (tablename in fkey_whitelist and
                            column_keys == fkey_whitelist[tablename]):
                        continue
                elif element[0] == 'remove_column':
                    tablename = element[2]
                    column = element[3]
                    if (tablename in column_whitelist and
                            column.name in column_whitelist[tablename]):
                        continue

                new_diff.append(element)
        return new_diff


class TestNovaAPIMigrationsSQLite(NovaAPIModelsSync,
                                  test_fixtures.OpportunisticDBTestMixin,
                                  testtools.TestCase):
    pass


class TestNovaAPIMigrationsMySQL(NovaAPIModelsSync,
                                 test_fixtures.OpportunisticDBTestMixin,
                                 testtools.TestCase):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestNovaAPIMigrationsPostgreSQL(NovaAPIModelsSync,
        test_fixtures.OpportunisticDBTestMixin, testtools.TestCase):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture


class NovaAPIMigrationsWalk(test_migrations.WalkVersionsMixin):
    def setUp(self):
        # NOTE(sdague): the oslo_db base test case completely
        # invalidates our logging setup, we actually have to do that
        # before it is called to keep this from vomiting all over our
        # test output.
        self.useFixture(nova_fixtures.StandardLogging())
        super(NovaAPIMigrationsWalk, self).setUp()
        self.engine = enginefacade.writer.get_engine()

    @property
    def INIT_VERSION(self):
        return migration.db_initial_version('api')

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

    def _skippable_migrations(self):
        train_placeholders = list(range(68, 73))
        ussuri_placeholders = list(range(73, 78))
        victoria_placeholders = list(range(78, 83))
        special_cases = [
            self.INIT_VERSION + 1,  # initial change
        ]
        return (train_placeholders +
                ussuri_placeholders +
                victoria_placeholders +
                special_cases)

    def migrate_up(self, version, with_data=False):
        if with_data:
            check = getattr(self, '_check_%03d' % version, None)
            if version not in self._skippable_migrations():
                self.assertIsNotNone(check,
                                     ('API DB Migration %i does not have a '
                                      'test. Please add one!') % version)
        super(NovaAPIMigrationsWalk, self).migrate_up(version, with_data)

    def test_walk_versions(self):
        self.walk_versions(snake_walk=False, downgrade=False)


class TestNovaAPIMigrationsWalkSQLite(NovaAPIMigrationsWalk,
                                      test_fixtures.OpportunisticDBTestMixin,
                                      test.NoDBTestCase):
    pass


class TestNovaAPIMigrationsWalkMySQL(NovaAPIMigrationsWalk,
                                     test_fixtures.OpportunisticDBTestMixin,
                                     test.NoDBTestCase):
    FIXTURE = test_fixtures.MySQLOpportunisticFixture


class TestNovaAPIMigrationsWalkPostgreSQL(NovaAPIMigrationsWalk,
        test_fixtures.OpportunisticDBTestMixin, test.NoDBTestCase):
    FIXTURE = test_fixtures.PostgresqlOpportunisticFixture

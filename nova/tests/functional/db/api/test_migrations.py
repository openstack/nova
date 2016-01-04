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

import logging
import os

from migrate.versioning import repository
import mock
from oslo_config import cfg
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
import sqlalchemy
from sqlalchemy.engine import reflection

from nova.db import migration
from nova.db.sqlalchemy.api_migrations import migrate_repo
from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import migration as sa_migration
from nova import test


CONF = cfg.CONF


class NovaAPIModelsSync(test_migrations.ModelsMigrationsSync):
    """Test that the models match the database after migrations are run."""

    def db_sync(self, engine):
        with mock.patch.object(sa_migration, 'get_engine',
                               return_value=engine):
            sa_migration.db_sync(database='api')

    @property
    def migrate_engine(self):
        return self.engine

    def get_engine(self):
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


class TestNovaAPIMigrationsSQLite(NovaAPIModelsSync,
                                  test_base.DbTestCase,
                                  test.NoDBTestCase):
    pass


class TestNovaAPIMigrationsMySQL(NovaAPIModelsSync,
                                 test_base.MySQLOpportunisticTestCase,
                                 test.NoDBTestCase):
    pass


class TestNovaAPIMigrationsPostgreSQL(NovaAPIModelsSync,
        test_base.PostgreSQLOpportunisticTestCase, test.NoDBTestCase):
    pass


class NovaAPIMigrationsWalk(test_migrations.WalkVersionsMixin):
    def setUp(self):
        super(NovaAPIMigrationsWalk, self).setUp()
        # NOTE(viktors): We should reduce log output because it causes issues,
        #                when we run tests with testr
        migrate_log = logging.getLogger('migrate')
        old_level = migrate_log.level
        migrate_log.setLevel(logging.WARN)
        self.addCleanup(migrate_log.setLevel, old_level)

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

    def test_walk_versions(self):
        self.walk_versions(snake_walk=False, downgrade=False)

    def assertColumnExists(self, engine, table_name, column):
        self.assertTrue(db_utils.column_exists(engine, table_name, column),
                'Column %s.%s does not exist' % (table_name, column))

    def assertIndexExists(self, engine, table_name, index):
        self.assertTrue(db_utils.index_exists(engine, table_name, index),
                        'Index %s on table %s does not exist' %
                        (index, table_name))

    def assertUniqueConstraintExists(self, engine, table_name, columns):
        inspector = reflection.Inspector.from_engine(engine)
        constrs = inspector.get_unique_constraints(table_name)
        constr_columns = [constr['column_names'] for constr in constrs]
        self.assertIn(columns, constr_columns)

    def assertTableNotExists(self, engine, table_name):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                db_utils.get_table, engine, table_name)

    def _check_001(self, engine, data):
        for column in ['created_at', 'updated_at', 'id', 'uuid', 'name',
                'transport_url', 'database_connection']:
            self.assertColumnExists(engine, 'cell_mappings', column)

        self.assertIndexExists(engine, 'cell_mappings', 'uuid_idx')
        self.assertUniqueConstraintExists(engine, 'cell_mappings',
                ['uuid'])

    def _check_002(self, engine, data):
        for column in ['created_at', 'updated_at', 'id', 'instance_uuid',
                'cell_id', 'project_id']:
            self.assertColumnExists(engine, 'instance_mappings', column)

        for index in ['instance_uuid_idx', 'project_id_idx']:
            self.assertIndexExists(engine, 'instance_mappings', index)

        self.assertUniqueConstraintExists(engine, 'instance_mappings',
                ['instance_uuid'])

        inspector = reflection.Inspector.from_engine(engine)
        # There should only be one foreign key here
        fk = inspector.get_foreign_keys('instance_mappings')[0]
        self.assertEqual('cell_mappings', fk['referred_table'])
        self.assertEqual(['id'], fk['referred_columns'])
        self.assertEqual(['cell_id'], fk['constrained_columns'])

    def _check_003(self, engine, data):
        for column in ['created_at', 'updated_at', 'id',
                'cell_id', 'host']:
            self.assertColumnExists(engine, 'host_mappings', column)

        self.assertIndexExists(engine, 'host_mappings', 'host_idx')
        self.assertUniqueConstraintExists(engine, 'host_mappings',
                ['host'])

        inspector = reflection.Inspector.from_engine(engine)
        # There should only be one foreign key here
        fk = inspector.get_foreign_keys('host_mappings')[0]
        self.assertEqual('cell_mappings', fk['referred_table'])
        self.assertEqual(['id'], fk['referred_columns'])
        self.assertEqual(['cell_id'], fk['constrained_columns'])

    def _check_004(self, engine, data):
        columns = ['created_at', 'updated_at', 'id', 'instance_uuid', 'spec']
        for column in columns:
            self.assertColumnExists(engine, 'request_specs', column)

        self.assertUniqueConstraintExists(engine, 'request_specs',
                ['instance_uuid'])
        if engine.name != 'ibm_db_sa':
            self.assertIndexExists(engine, 'request_specs',
                    'request_spec_instance_uuid_idx')


class TestNovaAPIMigrationsWalkSQLite(NovaAPIMigrationsWalk,
                                      test_base.DbTestCase,
                                      test.NoDBTestCase):
    pass


class TestNovaAPIMigrationsWalkMySQL(NovaAPIMigrationsWalk,
                                     test_base.MySQLOpportunisticTestCase,
                                     test.NoDBTestCase):
    pass


class TestNovaAPIMigrationsWalkPostgreSQL(NovaAPIMigrationsWalk,
        test_base.PostgreSQLOpportunisticTestCase, test.NoDBTestCase):
    pass

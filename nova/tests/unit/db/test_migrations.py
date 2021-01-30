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
from sqlalchemy.engine import reflection
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

        kilo_placeholders = list(range(281, 291))
        liberty_placeholders = list(range(303, 313))
        mitaka_placeholders = list(range(320, 330))
        newton_placeholders = list(range(335, 345))
        ocata_placeholders = list(range(348, 358))
        pike_placeholders = list(range(363, 373))
        queens_placeholders = list(range(379, 389))
        # We forgot to add the rocky placeholder. We've also switched to 5
        # placeholders per cycle since the rate of DB changes has dropped
        # significantly
        stein_placeholders = list(range(392, 397))
        train_placeholders = list(range(403, 408))
        ussuri_placeholders = list(range(408, 413))
        victoria_placeholders = list(range(413, 418))

        return (special +
                kilo_placeholders +
                liberty_placeholders +
                mitaka_placeholders +
                newton_placeholders +
                ocata_placeholders +
                pike_placeholders +
                queens_placeholders +
                stein_placeholders +
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

            # 292 drops completely orphaned tables with no users, so
            # it can be done without affecting anything.
            292,

            # 346 Drops column scheduled_at from instances table since it
            # is no longer used. The field value is always NULL so
            # it does not affect anything.
            346,
        ]
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE

        if version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with nova_fixtures.BannedDBSchemaOperations(banned):
            super(NovaMigrationsCheckers, self).migrate_up(version, with_data)

    def test_walk_versions(self):
        self.walk_versions(snake_walk=False, downgrade=False)

    def _check_291(self, engine, data):
        # NOTE(danms): This is a dummy migration that just does a consistency
        # check
        pass

    def _check_292(self, engine, data):
        self.assertTableNotExists(engine, 'iscsi_targets')
        self.assertTableNotExists(engine, 'volumes')
        self.assertTableNotExists(engine, 'shadow_iscsi_targets')
        self.assertTableNotExists(engine, 'shadow_volumes')

    def _pre_upgrade_293(self, engine):
        migrations = oslodbutils.get_table(engine, 'migrations')
        fake_migration = {}
        migrations.insert().execute(fake_migration)

    def _check_293(self, engine, data):
        self.assertColumnExists(engine, 'migrations', 'migration_type')
        self.assertColumnExists(engine, 'shadow_migrations', 'migration_type')
        migrations = oslodbutils.get_table(engine, 'migrations')
        fake_migration = migrations.select().execute().first()
        self.assertIsNone(fake_migration.migration_type)
        self.assertFalse(fake_migration.hidden)

    def _check_294(self, engine, data):
        self.assertColumnExists(engine, 'services', 'last_seen_up')
        self.assertColumnExists(engine, 'shadow_services', 'last_seen_up')

        services = oslodbutils.get_table(engine, 'services')
        shadow_services = oslodbutils.get_table(
                engine, 'shadow_services')
        self.assertIsInstance(services.c.last_seen_up.type,
                              sqlalchemy.types.DateTime)
        self.assertIsInstance(shadow_services.c.last_seen_up.type,
                              sqlalchemy.types.DateTime)

    def _pre_upgrade_295(self, engine):
        self.assertIndexNotExists(engine, 'virtual_interfaces',
                                  'virtual_interfaces_uuid_idx')

    def _check_295(self, engine, data):
        self.assertIndexMembers(engine, 'virtual_interfaces',
                                'virtual_interfaces_uuid_idx', ['uuid'])

    def _check_296(self, engine, data):
        pass

    def _check_297(self, engine, data):
        self.assertColumnExists(engine, 'services', 'forced_down')

    def _check_298(self, engine, data):
        # NOTE(nic): This is a MySQL-specific migration, and is a no-op from
        # the point-of-view of unit tests, since they use SQLite
        pass

    def filter_metadata_diff(self, diff):
        # Overriding the parent method to decide on certain attributes
        # that maybe present in the DB but not in the models.py

        def removed_column(element):
            # Define a whitelist of columns that would be removed from the
            # DB at a later release.
            # NOTE(Luyao) The vpmems column was added to the schema in train,
            # and removed from the model in train.
            column_whitelist = {'instances': ['internal_id'],
                                'instance_extra': ['vpmems']}

            if element[0] != 'remove_column':
                return False

            table_name, column = element[2], element[3]
            return (table_name in column_whitelist and
                    column.name in column_whitelist[table_name])

        return [
            element
            for element in diff
            if not removed_column(element)
        ]

    def _check_299(self, engine, data):
        self.assertColumnExists(engine, 'services', 'version')

    def _check_300(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'migration_context')

    def _check_301(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes',
                                'cpu_allocation_ratio')
        self.assertColumnExists(engine, 'compute_nodes',
                                'ram_allocation_ratio')

    def _check_302(self, engine, data):
        self.assertIndexMembers(engine, 'instance_system_metadata',
                                'instance_uuid', ['instance_uuid'])

    def _check_313(self, engine, data):

        self.assertColumnExists(engine, 'pci_devices', 'parent_addr')
        self.assertColumnExists(engine, 'shadow_pci_devices', 'parent_addr')
        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        shadow_pci_devices = oslodbutils.get_table(
            engine, 'shadow_pci_devices')
        self.assertIsInstance(pci_devices.c.parent_addr.type,
                              sqlalchemy.types.String)
        self.assertTrue(pci_devices.c.parent_addr.nullable)
        self.assertIsInstance(shadow_pci_devices.c.parent_addr.type,
                              sqlalchemy.types.String)
        self.assertTrue(shadow_pci_devices.c.parent_addr.nullable)
        self.assertIndexMembers(engine, 'pci_devices',
                        'ix_pci_devices_compute_node_id_parent_addr_deleted',
                        ['compute_node_id', 'parent_addr', 'deleted'])

    def _check_314(self, engine, data):
        self.assertColumnExists(engine, 'inventories', 'resource_class_id')
        self.assertColumnExists(engine, 'allocations', 'resource_class_id')

        self.assertColumnExists(engine, 'resource_providers', 'id')
        self.assertColumnExists(engine, 'resource_providers', 'uuid')

        self.assertColumnExists(engine, 'compute_nodes', 'uuid')
        self.assertColumnExists(engine, 'shadow_compute_nodes', 'uuid')

        self.assertIndexMembers(engine, 'allocations',
                        'allocations_resource_provider_class_id_idx',
                        ['resource_provider_id', 'resource_class_id'])

    def _check_315(self, engine, data):
        self.assertColumnExists(engine, 'migrations',
                                'memory_total')
        self.assertColumnExists(engine, 'migrations',
                                'memory_processed')
        self.assertColumnExists(engine, 'migrations',
                                'memory_remaining')
        self.assertColumnExists(engine, 'migrations',
                                'disk_total')
        self.assertColumnExists(engine, 'migrations',
                                'disk_processed')
        self.assertColumnExists(engine, 'migrations',
                                'disk_remaining')

    def _check_316(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes',
                                'disk_allocation_ratio')

    def _check_317(self, engine, data):
        self.assertColumnExists(engine, 'aggregates', 'uuid')
        self.assertColumnExists(engine, 'shadow_aggregates', 'uuid')

    def _check_318(self, engine, data):
        self.assertColumnExists(engine, 'resource_providers', 'name')
        self.assertColumnExists(engine, 'resource_providers', 'generation')
        self.assertColumnExists(engine, 'resource_providers', 'can_host')
        self.assertIndexMembers(engine, 'resource_providers',
                                'resource_providers_name_idx',
                                ['name'])

        self.assertColumnExists(engine, 'resource_provider_aggregates',
                                'resource_provider_id')
        self.assertColumnExists(engine, 'resource_provider_aggregates',
                                'aggregate_id')

        self.assertIndexMembers(engine, 'resource_provider_aggregates',
            'resource_provider_aggregates_aggregate_id_idx',
            ['aggregate_id'])

        self.assertIndexMembers(engine, 'resource_provider_aggregates',
            'resource_provider_aggregates_aggregate_id_idx',
            ['aggregate_id'])

        self.assertIndexMembers(engine, 'inventories',
            'inventories_resource_provider_resource_class_idx',
            ['resource_provider_id', 'resource_class_id'])

    def _check_319(self, engine, data):
        self.assertIndexMembers(engine, 'instances',
                                'instances_deleted_created_at_idx',
                                ['deleted', 'created_at'])

    def _check_330(self, engine, data):
        # Just a sanity-check migration
        pass

    def _check_331(self, engine, data):
        self.assertColumnExists(engine, 'virtual_interfaces', 'tag')
        self.assertColumnExists(engine, 'block_device_mapping', 'tag')

    def _check_332(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'keypairs')

    def _check_333(self, engine, data):
        self.assertColumnExists(engine, 'console_auth_tokens', 'id')
        self.assertColumnExists(engine, 'console_auth_tokens', 'token_hash')
        self.assertColumnExists(engine, 'console_auth_tokens', 'console_type')
        self.assertColumnExists(engine, 'console_auth_tokens', 'host')
        self.assertColumnExists(engine, 'console_auth_tokens', 'port')
        self.assertColumnExists(engine, 'console_auth_tokens',
                                'internal_access_path')
        self.assertColumnExists(engine, 'console_auth_tokens',
                                'instance_uuid')
        self.assertColumnExists(engine, 'console_auth_tokens', 'expires')
        self.assertIndexMembers(engine, 'console_auth_tokens',
            'console_auth_tokens_instance_uuid_idx',
            ['instance_uuid'])
        self.assertIndexMembers(engine, 'console_auth_tokens',
            'console_auth_tokens_host_expires_idx',
            ['host', 'expires'])
        self.assertIndexMembers(engine, 'console_auth_tokens',
            'console_auth_tokens_token_hash_idx',
            ['token_hash'])

    def _check_334(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'device_metadata')
        self.assertColumnExists(engine, 'shadow_instance_extra',
                                        'device_metadata')

    def _check_345(self, engine, data):
        # NOTE(danms): Just a sanity-check migration
        pass

    def _check_346(self, engine, data):
        self.assertColumnNotExists(engine, 'instances', 'scheduled_at')
        self.assertColumnNotExists(engine, 'shadow_instances', 'scheduled_at')

    def _check_347(self, engine, data):
        self.assertIndexMembers(engine, 'instances',
                                'instances_project_id_idx',
                                ['project_id'])
        self.assertIndexMembers(engine, 'instances',
                                'instances_updated_at_project_id_idx',
                                ['updated_at', 'project_id'])

    def _check_358(self, engine, data):
        self.assertColumnExists(engine, 'block_device_mapping',
                                'attachment_id')

    def _check_359(self, engine, data):
        self.assertColumnExists(engine, 'services', 'uuid')
        self.assertIndexMembers(engine, 'services', 'services_uuid_idx',
                                ['uuid'])

    def _check_360(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'mapped')
        self.assertColumnExists(engine, 'shadow_compute_nodes', 'mapped')

    def _check_361(self, engine, data):
        self.assertIndexMembers(engine, 'compute_nodes',
                                'compute_nodes_uuid_idx', ['uuid'])

    def _check_362(self, engine, data):
        self.assertColumnExists(engine, 'pci_devices', 'uuid')

    def _check_373(self, engine, data):
        self.assertColumnExists(engine, 'migrations', 'uuid')

    def _check_374(self, engine, data):
        self.assertColumnExists(engine, 'block_device_mapping', 'uuid')
        self.assertColumnExists(engine, 'shadow_block_device_mapping', 'uuid')

        inspector = reflection.Inspector.from_engine(engine)
        constraints = inspector.get_unique_constraints('block_device_mapping')
        constraint_names = [constraint['name'] for constraint in constraints]
        self.assertIn('uniq_block_device_mapping0uuid', constraint_names)

    def _check_375(self, engine, data):
        self.assertColumnExists(engine, 'console_auth_tokens',
                                'access_url_base')

    def _check_376(self, engine, data):
        self.assertIndexMembers(
            engine, 'console_auth_tokens',
            'console_auth_tokens_token_hash_instance_uuid_idx',
            ['token_hash', 'instance_uuid'])

    def _check_377(self, engine, data):
        self.assertIndexMembers(engine, 'migrations',
                                'migrations_updated_at_idx', ['updated_at'])

    def _check_378(self, engine, data):
        self.assertIndexMembers(
            engine, 'instance_actions',
            'instance_actions_instance_uuid_updated_at_idx',
            ['instance_uuid', 'updated_at'])

    def _check_389(self, engine, data):
        self.assertIndexMembers(engine, 'aggregate_metadata',
                                'aggregate_metadata_value_idx',
                                ['value'])

    def _check_390(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'trusted_certs')
        self.assertColumnExists(engine, 'shadow_instance_extra',
                                'trusted_certs')

    def _check_391(self, engine, data):
        self.assertColumnExists(engine, 'block_device_mapping', 'volume_type')
        self.assertColumnExists(engine, 'shadow_block_device_mapping',
                                'volume_type')

    def _check_397(self, engine, data):
        for prefix in ('', 'shadow_'):
            self.assertColumnExists(
                engine, '%smigrations' % prefix, 'cross_cell_move')

    def _check_398(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'vpmems')
        self.assertColumnExists(engine, 'shadow_instance_extra', 'vpmems')

    def _check_399(self, engine, data):
        for prefix in ('', 'shadow_'):
            self.assertColumnExists(
                engine, '%sinstances' % prefix, 'hidden')

    def _check_400(self, engine, data):
        # NOTE(mriedem): This is a dummy migration that just does a consistency
        # check. The actual test for 400 is in TestServicesUUIDCheck.
        pass

    def _check_401(self, engine, data):
        for prefix in ('', 'shadow_'):
            self.assertColumnExists(
                engine, '%smigrations' % prefix, 'user_id')
            self.assertColumnExists(
                engine, '%smigrations' % prefix, 'project_id')

    def _check_402(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'resources')
        self.assertColumnExists(engine, 'shadow_instance_extra', 'resources')


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

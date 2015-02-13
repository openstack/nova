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
import logging
import os

from migrate import UniqueConstraint
from migrate.versioning import repository
import mock
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as oslodbutils
import sqlalchemy
from sqlalchemy.engine import reflection
import sqlalchemy.exc
from sqlalchemy.sql import null

from nova.db import migration
from nova.db.sqlalchemy import migrate_repo
from nova.db.sqlalchemy import migration as sa_migration
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy import utils as db_utils
from nova import exception
from nova import test


LOG = logging.getLogger(__name__)


class NovaMigrationsCheckers(test_migrations.ModelsMigrationsSync,
                             test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    TIMEOUT_SCALING_FACTOR = 2

    snake_walk = True
    downgrade = True

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
        super(NovaMigrationsCheckers, self).setUp()
        # NOTE(viktors): We should reduce log output because it causes issues,
        #                when we run tests with testr
        migrate_log = logging.getLogger('migrate')
        old_level = migrate_log.level
        migrate_log.setLevel(logging.WARN)
        self.addCleanup(migrate_log.setLevel, old_level)

    def assertColumnExists(self, engine, table_name, column):
        self.assertTrue(oslodbutils.column_exists(engine, table_name, column))

    def assertColumnNotExists(self, engine, table_name, column):
        self.assertFalse(oslodbutils.column_exists(engine, table_name, column))

    def assertTableNotExists(self, engine, table):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          oslodbutils.get_table, engine, table)

    def assertIndexExists(self, engine, table_name, index):
        self.assertTrue(oslodbutils.index_exists(engine, table_name, index))

    def assertIndexNotExists(self, engine, table_name, index):
        self.assertFalse(oslodbutils.index_exists(engine, table_name, index))

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

    def get_engine(self):
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
            216,  # Havana
            272,  # NOOP migration due to revert
        ]

        havana_placeholders = range(217, 227)
        icehouse_placeholders = range(235, 244)
        juno_placeholders = range(255, 265)

        return (special +
                havana_placeholders +
                icehouse_placeholders +
                juno_placeholders)

    def migrate_up(self, version, with_data=False):
        if with_data:
            check = getattr(self, "_check_%03d" % version, None)
            if version not in self._skippable_migrations():
                self.assertIsNotNone(check,
                                     ('DB Migration %i does not have a '
                                      'test. Please add one!') % version)

        super(NovaMigrationsCheckers, self).migrate_up(version, with_data)

    def test_walk_versions(self):
        self.walk_versions(self.snake_walk, self.downgrade)

    def _check_227(self, engine, data):
        table = oslodbutils.get_table(engine, 'project_user_quotas')

        # Insert fake_quotas with the longest resource name.
        fake_quotas = {'id': 5,
                       'project_id': 'fake_project',
                       'user_id': 'fake_user',
                       'resource': 'injected_file_content_bytes',
                       'hard_limit': 10}
        table.insert().execute(fake_quotas)

        # Check we can get the longest resource name.
        quota = table.select(table.c.id == 5).execute().first()
        self.assertEqual(quota['resource'], 'injected_file_content_bytes')

    def _check_228(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'metrics')

        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.metrics.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_228(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'metrics')

    def _check_229(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'extra_resources')

        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.extra_resources.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_229(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'extra_resources')

    def _check_230(self, engine, data):
        for table_name in ['instance_actions_events',
                           'shadow_instance_actions_events']:
            self.assertColumnExists(engine, table_name, 'host')
            self.assertColumnExists(engine, table_name, 'details')

        action_events = oslodbutils.get_table(engine,
                                              'instance_actions_events')
        self.assertIsInstance(action_events.c.host.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(action_events.c.details.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_230(self, engine):
        for table_name in ['instance_actions_events',
                           'shadow_instance_actions_events']:
            self.assertColumnNotExists(engine, table_name, 'host')
            self.assertColumnNotExists(engine, table_name, 'details')

    def _check_231(self, engine, data):
        self.assertColumnExists(engine, 'instances', 'ephemeral_key_uuid')

        instances = oslodbutils.get_table(engine, 'instances')
        self.assertIsInstance(instances.c.ephemeral_key_uuid.type,
                              sqlalchemy.types.String)
        self.assertTrue(db_utils.check_shadow_table(engine, 'instances'))

    def _post_downgrade_231(self, engine):
        self.assertColumnNotExists(engine, 'instances', 'ephemeral_key_uuid')
        self.assertTrue(db_utils.check_shadow_table(engine, 'instances'))

    def _check_232(self, engine, data):
        table_names = ['compute_node_stats', 'compute_nodes',
                       'instance_actions', 'instance_actions_events',
                       'instance_faults', 'migrations']
        for table_name in table_names:
            self.assertTableNotExists(engine, 'dump_' + table_name)

    def _check_233(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'stats')

        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.stats.type,
                              sqlalchemy.types.Text)

        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          oslodbutils.get_table, engine, 'compute_node_stats')

    def _post_downgrade_233(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'stats')

        # confirm compute_node_stats exists
        oslodbutils.get_table(engine, 'compute_node_stats')

    def _check_234(self, engine, data):
        self.assertIndexMembers(engine, 'reservations',
                                'reservations_deleted_expire_idx',
                                ['deleted', 'expire'])

    def _check_244(self, engine, data):
        volume_usage_cache = oslodbutils.get_table(
            engine, 'volume_usage_cache')
        self.assertEqual(64, volume_usage_cache.c.user_id.type.length)

    def _post_downgrade_244(self, engine):
        volume_usage_cache = oslodbutils.get_table(
            engine, 'volume_usage_cache')
        self.assertEqual(36, volume_usage_cache.c.user_id.type.length)

    def _pre_upgrade_245(self, engine):
        # create a fake network
        networks = oslodbutils.get_table(engine, 'networks')
        fake_network = {'id': 1}
        networks.insert().execute(fake_network)

    def _check_245(self, engine, data):
        networks = oslodbutils.get_table(engine, 'networks')
        network = networks.select(networks.c.id == 1).execute().first()
        # mtu should default to None
        self.assertIsNone(network.mtu)
        # dhcp_server should default to None
        self.assertIsNone(network.dhcp_server)
        # enable dhcp should default to true
        self.assertTrue(network.enable_dhcp)
        # share address should default to false
        self.assertFalse(network.share_address)

    def _post_downgrade_245(self, engine):
        self.assertColumnNotExists(engine, 'networks', 'mtu')
        self.assertColumnNotExists(engine, 'networks', 'dhcp_server')
        self.assertColumnNotExists(engine, 'networks', 'enable_dhcp')
        self.assertColumnNotExists(engine, 'networks', 'share_address')

    def _check_246(self, engine, data):
        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertEqual(1, len([fk for fk in pci_devices.foreign_keys
                                 if fk.parent.name == 'compute_node_id']))

    def _post_downgrade_246(self, engine):
        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertEqual(0, len([fk for fk in pci_devices.foreign_keys
                                 if fk.parent.name == 'compute_node_id']))

    def _check_247(self, engine, data):
        quota_usages = oslodbutils.get_table(engine, 'quota_usages')
        self.assertFalse(quota_usages.c.resource.nullable)

        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertTrue(pci_devices.c.deleted.nullable)
        self.assertFalse(pci_devices.c.product_id.nullable)
        self.assertFalse(pci_devices.c.vendor_id.nullable)
        self.assertFalse(pci_devices.c.dev_type.nullable)

    def _post_downgrade_247(self, engine):
        quota_usages = oslodbutils.get_table(engine, 'quota_usages')
        self.assertTrue(quota_usages.c.resource.nullable)

        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertFalse(pci_devices.c.deleted.nullable)
        self.assertTrue(pci_devices.c.product_id.nullable)
        self.assertTrue(pci_devices.c.vendor_id.nullable)
        self.assertTrue(pci_devices.c.dev_type.nullable)

    def _check_248(self, engine, data):
        self.assertIndexMembers(engine, 'reservations',
                                'reservations_deleted_expire_idx',
                                ['deleted', 'expire'])

    def _post_downgrade_248(self, engine):
        reservations = oslodbutils.get_table(engine, 'reservations')
        index_names = [idx.name for idx in reservations.indexes]
        self.assertNotIn('reservations_deleted_expire_idx', index_names)

    def _check_249(self, engine, data):
        # Assert that only one index exists that covers columns
        # instance_uuid and device_name
        bdm = oslodbutils.get_table(engine, 'block_device_mapping')
        self.assertEqual(1, len([i for i in bdm.indexes
                                 if [c.name for c in i.columns] ==
                                    ['instance_uuid', 'device_name']]))

    def _post_downgrade_249(self, engine):
        # The duplicate index is not created on downgrade, so this
        # asserts that only one index exists that covers columns
        # instance_uuid and device_name
        bdm = oslodbutils.get_table(engine, 'block_device_mapping')
        self.assertEqual(1, len([i for i in bdm.indexes
                                 if [c.name for c in i.columns] ==
                                    ['instance_uuid', 'device_name']]))

    def _check_250(self, engine, data):
        self.assertTableNotExists(engine, 'instance_group_metadata')
        self.assertTableNotExists(engine, 'shadow_instance_group_metadata')

    def _post_downgrade_250(self, engine):
        oslodbutils.get_table(engine, 'instance_group_metadata')
        oslodbutils.get_table(engine, 'shadow_instance_group_metadata')

    def _check_251(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'numa_topology')
        self.assertColumnExists(engine, 'shadow_compute_nodes',
                                'numa_topology')

        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        shadow_compute_nodes = oslodbutils.get_table(engine,
                                                     'shadow_compute_nodes')
        self.assertIsInstance(compute_nodes.c.numa_topology.type,
                              sqlalchemy.types.Text)
        self.assertIsInstance(shadow_compute_nodes.c.numa_topology.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_251(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'numa_topology')
        self.assertColumnNotExists(engine, 'shadow_compute_nodes',
                                   'numa_topology')

    def _check_252(self, engine, data):
        oslodbutils.get_table(engine, 'instance_extra')
        oslodbutils.get_table(engine, 'shadow_instance_extra')
        self.assertIndexMembers(engine, 'instance_extra',
                                'instance_extra_idx',
                                ['instance_uuid'])

    def _post_downgrade_252(self, engine):
        self.assertTableNotExists(engine, 'instance_extra')
        self.assertTableNotExists(engine, 'shadow_instance_extra')

    def _check_253(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'pci_requests')
        self.assertColumnExists(
            engine, 'shadow_instance_extra', 'pci_requests')
        instance_extra = oslodbutils.get_table(engine, 'instance_extra')
        shadow_instance_extra = oslodbutils.get_table(engine,
                                                      'shadow_instance_extra')
        self.assertIsInstance(instance_extra.c.pci_requests.type,
                              sqlalchemy.types.Text)
        self.assertIsInstance(shadow_instance_extra.c.pci_requests.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_253(self, engine):
        self.assertColumnNotExists(engine, 'instance_extra', 'pci_requests')
        self.assertColumnNotExists(engine, 'shadow_instance_extra',
                                   'pci_requests')

    def _check_254(self, engine, data):
        self.assertColumnExists(engine, 'pci_devices', 'request_id')
        self.assertColumnExists(
            engine, 'shadow_pci_devices', 'request_id')

        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        shadow_pci_devices = oslodbutils.get_table(
            engine, 'shadow_pci_devices')
        self.assertIsInstance(pci_devices.c.request_id.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(shadow_pci_devices.c.request_id.type,
                              sqlalchemy.types.String)

    def _post_downgrade_254(self, engine):
        self.assertColumnNotExists(engine, 'pci_devices', 'request_id')
        self.assertColumnNotExists(
            engine, 'shadow_pci_devices', 'request_id')

    def _check_265(self, engine, data):
        # Assert that only one index exists that covers columns
        # host and deleted
        instances = oslodbutils.get_table(engine, 'instances')
        self.assertEqual(1, len([i for i in instances.indexes
                                 if [c.name for c in i.columns][:2] ==
                                    ['host', 'deleted']]))
        # and only one index covers host column
        iscsi_targets = oslodbutils.get_table(engine, 'iscsi_targets')
        self.assertEqual(1, len([i for i in iscsi_targets.indexes
                                 if [c.name for c in i.columns][:1] ==
                                    ['host']]))

    def _post_downgrade_265(self, engine):
        # The duplicated index is not created on downgrade, so this
        # asserts that only one index exists that covers columns
        # host and deleted
        instances = oslodbutils.get_table(engine, 'instances')
        self.assertEqual(1, len([i for i in instances.indexes
                                 if [c.name for c in i.columns][:2] ==
                                    ['host', 'deleted']]))
        # and only one index covers host column
        iscsi_targets = oslodbutils.get_table(engine, 'iscsi_targets')
        self.assertEqual(1, len([i for i in iscsi_targets.indexes
                                 if [c.name for c in i.columns][:1] ==
                                    ['host']]))

    def _check_266(self, engine, data):
        self.assertColumnExists(engine, 'tags', 'resource_id')
        self.assertColumnExists(engine, 'tags', 'tag')

        table = oslodbutils.get_table(engine, 'tags')

        self.assertIsInstance(table.c.resource_id.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(table.c.tag.type,
                              sqlalchemy.types.String)

    def _post_downgrade_266(self, engine):
        self.assertTableNotExists(engine, 'tags')

    def _pre_upgrade_267(self, engine):
        # Create a fixed_ips row with a null instance_uuid (if not already
        # there) to make sure that's not deleted.
        fixed_ips = oslodbutils.get_table(engine, 'fixed_ips')
        fake_fixed_ip = {'id': 1}
        fixed_ips.insert().execute(fake_fixed_ip)
        # Create an instance record with a valid (non-null) UUID so we make
        # sure we don't do something stupid and delete valid records.
        instances = oslodbutils.get_table(engine, 'instances')
        fake_instance = {'id': 1, 'uuid': 'fake-non-null-uuid'}
        instances.insert().execute(fake_instance)
        # Add a null instance_uuid entry for the volumes table
        # since it doesn't have a foreign key back to the instances table.
        volumes = oslodbutils.get_table(engine, 'volumes')
        fake_volume = {'id': '9c3c317e-24db-4d57-9a6f-96e6d477c1da'}
        volumes.insert().execute(fake_volume)

    def _check_267(self, engine, data):
        # Make sure the column is non-nullable and the UC exists.
        fixed_ips = oslodbutils.get_table(engine, 'fixed_ips')
        self.assertTrue(fixed_ips.c.instance_uuid.nullable)
        fixed_ip = fixed_ips.select(fixed_ips.c.id == 1).execute().first()
        self.assertIsNone(fixed_ip.instance_uuid)

        instances = oslodbutils.get_table(engine, 'instances')
        self.assertFalse(instances.c.uuid.nullable)

        inspector = reflection.Inspector.from_engine(engine)
        constraints = inspector.get_unique_constraints('instances')
        constraint_names = [constraint['name'] for constraint in constraints]
        self.assertIn('uniq_instances0uuid', constraint_names)

        # Make sure the instances record with the valid uuid is still there.
        instance = instances.select(instances.c.id == 1).execute().first()
        self.assertIsNotNone(instance)

        # Check that the null entry in the volumes table is still there since
        # we skipped tables that don't have FK's back to the instances table.
        volumes = oslodbutils.get_table(engine, 'volumes')
        self.assertTrue(volumes.c.instance_uuid.nullable)
        volume = fixed_ips.select(
            volumes.c.id == '9c3c317e-24db-4d57-9a6f-96e6d477c1da'
        ).execute().first()
        self.assertIsNone(volume.instance_uuid)

    def _post_downgrade_267(self, engine):
        # Make sure the UC is gone and the column is nullable again.
        instances = oslodbutils.get_table(engine, 'instances')
        self.assertTrue(instances.c.uuid.nullable)

        inspector = reflection.Inspector.from_engine(engine)
        constraints = inspector.get_unique_constraints('instances')
        constraint_names = [constraint['name'] for constraint in constraints]
        self.assertNotIn('uniq_instances0uuid', constraint_names)

    def test_migration_267(self):
        # This is separate from test_walk_versions so we can test the case
        # where there are non-null instance_uuid entries in the database which
        # cause the 267 migration to fail.
        engine = self.migrate_engine
        self.migration_api.version_control(
            engine, self.REPOSITORY, self.INIT_VERSION)
        self.migration_api.upgrade(engine, self.REPOSITORY, 266)
        # Create a consoles record with a null instance_uuid so
        # we can test that the upgrade fails if that entry is found.
        # NOTE(mriedem): We use the consoles table since that's the only table
        # created in the 216 migration with a ForeignKey created on the
        # instance_uuid table for sqlite.
        consoles = oslodbutils.get_table(engine, 'consoles')
        fake_console = {'id': 1}
        consoles.insert().execute(fake_console)

        # NOTE(mriedem): We handle the 267 migration where we expect to
        # hit a ValidationError on the consoles table to have
        # a null instance_uuid entry
        ex = self.assertRaises(exception.ValidationError,
                               self.migration_api.upgrade,
                               engine, self.REPOSITORY, 267)

        self.assertIn("There are 1 records in the "
                      "'consoles' table where the uuid or "
                      "instance_uuid column is NULL.",
                      ex.kwargs['detail'])

        # Remove the consoles entry with the null instance_uuid column.
        rows = consoles.delete().where(
            consoles.c['instance_uuid'] == null()).execute().rowcount
        self.assertEqual(1, rows)
        # Now run the 267 upgrade again.
        self.migration_api.upgrade(engine, self.REPOSITORY, 267)

        # Make sure the consoles entry with the null instance_uuid
        # was deleted.
        console = consoles.select(consoles.c.id == 1).execute().first()
        self.assertIsNone(console)

    def _check_268(self, engine, data):
        # We can only assert that the col exists, not the unique constraint
        # as the engine is running sqlite
        self.assertColumnExists(engine, 'compute_nodes', 'host')
        self.assertColumnExists(engine, 'shadow_compute_nodes', 'host')
        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        shadow_compute_nodes = oslodbutils.get_table(
            engine, 'shadow_compute_nodes')
        self.assertIsInstance(compute_nodes.c.host.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(shadow_compute_nodes.c.host.type,
                              sqlalchemy.types.String)

    def _post_downgrade_268(self, engine):
        self.assertColumnNotExists(engine, 'compute_nodes', 'host')
        self.assertColumnNotExists(engine, 'shadow_compute_nodes', 'host')

    def _check_269(self, engine, data):

        self.assertColumnExists(engine, 'pci_devices', 'numa_node')
        self.assertColumnExists(engine, 'shadow_pci_devices', 'numa_node')
        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        shadow_pci_devices = oslodbutils.get_table(
            engine, 'shadow_pci_devices')
        self.assertIsInstance(pci_devices.c.numa_node.type,
                              sqlalchemy.types.Integer)
        self.assertTrue(pci_devices.c.numa_node.nullable)
        self.assertIsInstance(shadow_pci_devices.c.numa_node.type,
                              sqlalchemy.types.Integer)
        self.assertTrue(shadow_pci_devices.c.numa_node.nullable)

    def _post_downgrade_269(self, engine):
        self.assertColumnNotExists(engine, 'pci_devices', 'numa_node')
        self.assertColumnNotExists(engine, 'shadow_pci_devices', 'numa_node')

    def _check_270(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'flavor')
        self.assertColumnExists(engine, 'shadow_instance_extra', 'flavor')

        instance_extra = oslodbutils.get_table(engine, 'instance_extra')
        shadow_instance_extra = oslodbutils.get_table(
                engine, 'shadow_instance_extra')
        self.assertIsInstance(instance_extra.c.flavor.type,
                              sqlalchemy.types.Text)
        self.assertIsInstance(shadow_instance_extra.c.flavor.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_270(self, engine):
        self.assertColumnNotExists(engine, 'instance_extra', 'flavor')
        self.assertColumnNotExists(engine, 'shadow_instance_extra', 'flavor')

    def _check_271(self, engine, data):
        self.assertIndexMembers(engine, 'block_device_mapping',
                                'snapshot_id', ['snapshot_id'])
        self.assertIndexMembers(engine, 'block_device_mapping',
                                'volume_id', ['volume_id'])
        self.assertIndexMembers(engine, 'dns_domains',
                                'dns_domains_project_id_idx',
                                ['project_id'])
        self.assertIndexMembers(engine, 'fixed_ips',
                                'network_id', ['network_id'])
        self.assertIndexMembers(engine, 'fixed_ips',
                                'fixed_ips_instance_uuid_fkey',
                                ['instance_uuid'])
        self.assertIndexMembers(engine, 'fixed_ips',
                                'fixed_ips_virtual_interface_id_fkey',
                                ['virtual_interface_id'])
        self.assertIndexMembers(engine, 'floating_ips',
                                'fixed_ip_id', ['fixed_ip_id'])
        self.assertIndexMembers(engine, 'iscsi_targets',
                                'iscsi_targets_volume_id_fkey', ['volume_id'])
        self.assertIndexMembers(engine, 'virtual_interfaces',
                                'virtual_interfaces_network_id_idx',
                                ['network_id'])
        self.assertIndexMembers(engine, 'virtual_interfaces',
                                'virtual_interfaces_instance_uuid_fkey',
                                ['instance_uuid'])

        # Removed on MySQL, never existed on other databases
        self.assertIndexNotExists(engine, 'dns_domains', 'project_id')
        self.assertIndexNotExists(engine, 'virtual_interfaces', 'network_id')

    def _post_downgrade_271(self, engine):
        self.assertIndexNotExists(engine, 'dns_domains',
                                  'dns_domains_project_id_idx')
        self.assertIndexNotExists(engine, 'virtual_interfaces',
                                  'virtual_interfaces_network_id_idx')
        if engine.name == 'mysql':
            self.assertIndexMembers(engine, 'dns_domains',
                                    'project_id',
                                    ['project_id'])
            self.assertIndexMembers(engine, 'virtual_interfaces',
                                    'network_id',
                                    ['network_id'])
            # Rest of indexes will still exist on MySQL
            return

        # Never existed on non-MySQL databases, so shouldn't exist now
        self.assertIndexNotExists(engine, 'dns_domains', 'project_id')
        self.assertIndexNotExists(engine, 'virtual_interfaces', 'network_id')

        for table_name, index_name in [
                ('block_device_mapping', 'snapshot_id'),
                ('block_device_mapping', 'volume_id'),
                ('dns_domains', 'dns_domains_project_id_idx'),
                ('fixed_ips', 'network_id'),
                ('fixed_ips', 'fixed_ips_instance_uuid_fkey'),
                ('fixed_ips', 'fixed_ips_virtual_interface_id_fkey'),
                ('floating_ips', 'fixed_ip_id'),
                ('iscsi_targets', 'iscsi_targets_volume_id_fkey'),
                ('virtual_interfaces', 'virtual_interfaces_network_id_idx'),
                ('virtual_interfaces',
                 'virtual_interfaces_instance_uuid_fkey')]:
            self.assertIndexNotExists(engine, table_name, index_name)

    def _pre_upgrade_273(self, engine):
        if engine.name != 'sqlite':
            return

        # Drop a variety of unique constraints to ensure that the script
        # properly readds them back
        for table_name, constraint_name in [
                ('compute_nodes', 'uniq_compute_nodes0'
                                  'host0hypervisor_hostname'),
                ('fixed_ips', 'uniq_fixed_ips0address0deleted'),
                ('instance_info_caches', 'uniq_instance_info_caches0'
                                         'instance_uuid'),
                ('instance_type_projects', 'uniq_instance_type_projects0'
                                           'instance_type_id0project_id0'
                                           'deleted'),
                ('pci_devices', 'uniq_pci_devices0compute_node_id0'
                                'address0deleted'),
                ('virtual_interfaces', 'uniq_virtual_interfaces0'
                                       'address0deleted')]:
            table = oslodbutils.get_table(engine, table_name)
            constraints = [c for c in table.constraints
                           if c.name == constraint_name]
            for cons in constraints:
                # Need to use sqlalchemy-migrate UniqueConstraint
                cons = UniqueConstraint(*[c.name for c in cons.columns],
                                        name=cons.name,
                                        table=table)
                cons.drop()

    def _check_273(self, engine, data):
        for src_table, src_column, dst_table, dst_column in [
                ('fixed_ips', 'instance_uuid', 'instances', 'uuid'),
                ('block_device_mapping', 'instance_uuid', 'instances', 'uuid'),
                ('instance_info_caches', 'instance_uuid', 'instances', 'uuid'),
                ('instance_metadata', 'instance_uuid', 'instances', 'uuid'),
                ('instance_system_metadata', 'instance_uuid',
                 'instances', 'uuid'),
                ('instance_type_projects', 'instance_type_id',
                 'instance_types', 'id'),
                ('iscsi_targets', 'volume_id', 'volumes', 'id'),
                ('reservations', 'usage_id', 'quota_usages', 'id'),
                ('security_group_instance_association', 'instance_uuid',
                 'instances', 'uuid'),
                ('security_group_instance_association', 'security_group_id',
                 'security_groups', 'id'),
                ('virtual_interfaces', 'instance_uuid', 'instances', 'uuid'),
                ('compute_nodes', 'service_id', 'services', 'id'),
                ('instance_actions', 'instance_uuid', 'instances', 'uuid'),
                ('instance_faults', 'instance_uuid', 'instances', 'uuid'),
                ('migrations', 'instance_uuid', 'instances', 'uuid')]:
            src_table = oslodbutils.get_table(engine, src_table)
            fkeys = {fk.parent.name: fk.column
                     for fk in src_table.foreign_keys}
            self.assertIn(src_column, fkeys)
            self.assertEqual(fkeys[src_column].table.name, dst_table)
            self.assertEqual(fkeys[src_column].name, dst_column)

    def _post_downgrade_273(self, engine):
        # NOTE(johannes): No downgrade implemented, so nothing to check
        pass

    def _check_274(self, engine, data):
        self.assertIndexMembers(engine, 'instances',
                                'instances_project_id_deleted_idx',
                                ['project_id', 'deleted'])
        self.assertIndexNotExists(engine, 'instances', 'project_id')

    def _post_downgrade_274(self, engine):
        self.assertIndexMembers(engine, 'instances',
                                'project_id', ['project_id'])
        self.assertIndexNotExists(engine, 'instances',
                                  'instances_project_id_deleted_idx')

    def _pre_upgrade_275(self, engine):
        # Create a keypair record so we can test that the upgrade will set
        # 'ssh' as default value in the new column for the previous keypair
        # entries.
        key_pairs = oslodbutils.get_table(engine, 'key_pairs')
        fake_keypair = {'name': 'test-migr'}
        key_pairs.insert().execute(fake_keypair)

    def _check_275(self, engine, data):
        self.assertColumnExists(engine, 'key_pairs', 'type')
        self.assertColumnExists(engine, 'shadow_key_pairs', 'type')

        key_pairs = oslodbutils.get_table(engine, 'key_pairs')
        shadow_key_pairs = oslodbutils.get_table(engine, 'shadow_key_pairs')
        self.assertIsInstance(key_pairs.c.type.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(shadow_key_pairs.c.type.type,
                              sqlalchemy.types.String)

        # Make sure the keypair entry will have the type 'ssh'
        key_pairs = oslodbutils.get_table(engine, 'key_pairs')
        keypair = key_pairs.select(
            key_pairs.c.name == 'test-migr').execute().first()
        self.assertEqual('ssh', keypair.type)

    def _post_downgrade_275(self, engine):
        self.assertColumnNotExists(engine, 'key_pairs', 'type')
        self.assertColumnNotExists(engine, 'shadow_key_pairs', 'type')

    def _check_276(self, engine, data):
        self.assertColumnExists(engine, 'instance_extra', 'vcpu_model')
        self.assertColumnExists(engine, 'shadow_instance_extra', 'vcpu_model')

        instance_extra = oslodbutils.get_table(engine, 'instance_extra')
        shadow_instance_extra = oslodbutils.get_table(
                engine, 'shadow_instance_extra')
        self.assertIsInstance(instance_extra.c.vcpu_model.type,
                              sqlalchemy.types.Text)
        self.assertIsInstance(shadow_instance_extra.c.vcpu_model.type,
                              sqlalchemy.types.Text)

    def _post_downgrade_276(self, engine):
        self.assertColumnNotExists(engine, 'instance_extra', 'vcpu_model')
        self.assertColumnNotExists(engine, 'shadow_instance_extra',
                                   'vcpu_model')


class TestNovaMigrationsSQLite(NovaMigrationsCheckers,
                               test.TestCase,
                               test_base.DbTestCase):
    pass


class TestNovaMigrationsMySQL(NovaMigrationsCheckers,
                              test.TestCase,
                              test_base.MySQLOpportunisticTestCase):
    def test_innodb_tables(self):
        with mock.patch.object(sa_migration, 'get_engine',
                               return_value=self.migrate_engine):
            sa_migration.db_sync()

        total = self.migrate_engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = '%(database)s'" %
            {'database': self.migrate_engine.url.database})
        self.assertTrue(total.scalar() > 0, "No tables found. Wrong schema?")

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
                                   test.TestCase,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass


class ProjectTestCase(test.NoDBTestCase):

    def test_all_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../../')
        py_glob = os.path.join(topdir, "nova", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")

        missing_downgrade = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and not has_downgrade:
                    fname = os.path.basename(path)
                    missing_downgrade.append(fname)

        helpful_msg = ("The following migrations are missing a downgrade:"
                       "\n\t%s" % '\n\t'.join(sorted(missing_downgrade)))
        self.assertFalse(missing_downgrade, helpful_msg)

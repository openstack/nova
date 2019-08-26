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

from migrate import UniqueConstraint
from migrate.versioning import repository
import mock
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import test_fixtures
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as oslodbutils
import sqlalchemy
from sqlalchemy.engine import reflection
import sqlalchemy.exc
from sqlalchemy.sql import null
import testtools

from nova.db import migration
from nova.db.sqlalchemy import migrate_repo
from nova.db.sqlalchemy import migration as sa_migration
from nova.db.sqlalchemy import models
from nova.db.sqlalchemy import utils as db_utils
from nova import exception
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
        # NOTE(rpodolyaka): we need to repeat the functionality of the base
        # test case a bit here as this gets overridden by oslotest base test
        # case and nova base test case cleanup must be the last one (as it
        # deletes attributes of test case instances)
        self.useFixture(nova_fixtures.Timeout(
            os.environ.get('OS_TEST_TIMEOUT', 0),
            self.TIMEOUT_SCALING_FACTOR))
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
            216,  # Havana
            272,  # NOOP migration due to revert
        ]

        havana_placeholders = list(range(217, 227))
        icehouse_placeholders = list(range(235, 244))
        juno_placeholders = list(range(255, 265))
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

        return (special +
                havana_placeholders +
                icehouse_placeholders +
                juno_placeholders +
                kilo_placeholders +
                liberty_placeholders +
                mitaka_placeholders +
                newton_placeholders +
                ocata_placeholders +
                pike_placeholders +
                queens_placeholders +
                stein_placeholders)

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
            # 267 enforces non-nullable instance.uuid. This was mostly
            # a special case because instance.uuid shouldn't be able
            # to be nullable
            267,

            # 278 removes a FK restriction, so it's an alter operation
            # that doesn't break existing users
            278,

            # 280 enforces non-null keypair name. This is really not
            # something we should allow, but it's in the past
            280,

            # 292 drops completely orphaned tables with no users, so
            # it can be done without affecting anything.
            292,

            # 346 Drops column scheduled_at from instances table since it
            # is no longer used. The field value is always NULL so
            # it does not affect anything.
            346,
        ]
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE

        # NOTE(danms): We only started requiring things be additive in
        # kilo, so ignore all migrations before that point.
        KILO_START = 265

        if version >= KILO_START and version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with nova_fixtures.BannedDBSchemaOperations(banned):
            super(NovaMigrationsCheckers, self).migrate_up(version, with_data)

    def test_walk_versions(self):
        self.walk_versions(snake_walk=False, downgrade=False)

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

    def _check_229(self, engine, data):
        self.assertColumnExists(engine, 'compute_nodes', 'extra_resources')

        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        self.assertIsInstance(compute_nodes.c.extra_resources.type,
                              sqlalchemy.types.Text)

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

    def _check_231(self, engine, data):
        self.assertColumnExists(engine, 'instances', 'ephemeral_key_uuid')

        instances = oslodbutils.get_table(engine, 'instances')
        self.assertIsInstance(instances.c.ephemeral_key_uuid.type,
                              sqlalchemy.types.String)
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

    def _check_234(self, engine, data):
        self.assertIndexMembers(engine, 'reservations',
                                'reservations_deleted_expire_idx',
                                ['deleted', 'expire'])

    def _check_244(self, engine, data):
        volume_usage_cache = oslodbutils.get_table(
            engine, 'volume_usage_cache')
        self.assertEqual(64, volume_usage_cache.c.user_id.type.length)

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

    def _check_246(self, engine, data):
        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertEqual(1, len([fk for fk in pci_devices.foreign_keys
                                 if fk.parent.name == 'compute_node_id']))

    def _check_247(self, engine, data):
        quota_usages = oslodbutils.get_table(engine, 'quota_usages')
        self.assertFalse(quota_usages.c.resource.nullable)

        pci_devices = oslodbutils.get_table(engine, 'pci_devices')
        self.assertTrue(pci_devices.c.deleted.nullable)
        self.assertFalse(pci_devices.c.product_id.nullable)
        self.assertFalse(pci_devices.c.vendor_id.nullable)
        self.assertFalse(pci_devices.c.dev_type.nullable)

    def _check_248(self, engine, data):
        self.assertIndexMembers(engine, 'reservations',
                                'reservations_deleted_expire_idx',
                                ['deleted', 'expire'])

    def _check_249(self, engine, data):
        # Assert that only one index exists that covers columns
        # instance_uuid and device_name
        bdm = oslodbutils.get_table(engine, 'block_device_mapping')
        self.assertEqual(1, len([i for i in bdm.indexes
                                 if [c.name for c in i.columns] ==
                                    ['instance_uuid', 'device_name']]))

    def _check_250(self, engine, data):
        self.assertTableNotExists(engine, 'instance_group_metadata')
        self.assertTableNotExists(engine, 'shadow_instance_group_metadata')

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

    def _check_252(self, engine, data):
        oslodbutils.get_table(engine, 'instance_extra')
        oslodbutils.get_table(engine, 'shadow_instance_extra')
        self.assertIndexMembers(engine, 'instance_extra',
                                'instance_extra_idx',
                                ['instance_uuid'])

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

    def _check_266(self, engine, data):
        self.assertColumnExists(engine, 'tags', 'resource_id')
        self.assertColumnExists(engine, 'tags', 'tag')

        table = oslodbutils.get_table(engine, 'tags')

        self.assertIsInstance(table.c.resource_id.type,
                              sqlalchemy.types.String)
        self.assertIsInstance(table.c.tag.type,
                              sqlalchemy.types.String)

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

    def _check_274(self, engine, data):
        self.assertIndexMembers(engine, 'instances',
                                'instances_project_id_deleted_idx',
                                ['project_id', 'deleted'])
        self.assertIndexNotExists(engine, 'instances', 'project_id')

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

    def _check_277(self, engine, data):
        self.assertIndexMembers(engine, 'fixed_ips',
                                'fixed_ips_deleted_allocated_updated_at_idx',
                                ['deleted', 'allocated', 'updated_at'])

    def _check_278(self, engine, data):
        compute_nodes = oslodbutils.get_table(engine, 'compute_nodes')
        self.assertEqual(0, len([fk for fk in compute_nodes.foreign_keys
                                 if fk.parent.name == 'service_id']))
        self.assertTrue(compute_nodes.c.service_id.nullable)

    def _check_279(self, engine, data):
        inspector = reflection.Inspector.from_engine(engine)
        constraints = inspector.get_unique_constraints('compute_nodes')
        constraint_names = [constraint['name'] for constraint in constraints]
        self.assertNotIn('uniq_compute_nodes0host0hypervisor_hostname',
                         constraint_names)
        self.assertIn('uniq_compute_nodes0host0hypervisor_hostname0deleted',
                      constraint_names)

    def _check_280(self, engine, data):
        key_pairs = oslodbutils.get_table(engine, 'key_pairs')
        self.assertFalse(key_pairs.c.name.nullable)

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

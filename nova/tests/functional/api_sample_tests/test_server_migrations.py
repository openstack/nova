# Copyright 2016 OpenStack Foundation
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

import datetime

import futurist
import mock

from nova.conductor import manager as conductor_manager
from nova import context
from nova.db import api as db
from nova import objects
from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit import fake_instance


class ServerMigrationsSampleJsonTest(test_servers.ServersSampleBase):
    sample_dir = 'server-migrations'
    scenarios = [('v2_22', {'api_major_version': 'v2.1'})]
    microversion = '2.22'
    USE_NEUTRON = True

    def setUp(self):
        """setUp method for server usage."""
        super(ServerMigrationsSampleJsonTest, self).setUp()
        self.uuid = self._post_server()

    @mock.patch.object(conductor_manager.ComputeTaskManager, '_live_migrate')
    @mock.patch.object(db, 'service_get_by_compute_host')
    @mock.patch.object(objects.Migration, 'get_by_id_and_instance')
    @mock.patch('nova.compute.manager.ComputeManager.'
                'live_migration_force_complete')
    def test_live_migrate_force_complete(self, live_migration_pause_instance,
                                         get_by_id_and_instance,
                                         service_get_by_compute_host,
                                         _live_migrate):
        migration = objects.Migration()
        migration.id = 1
        migration.status = 'running'
        migration.source_compute = self.compute.host
        get_by_id_and_instance.return_value = migration
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        response = self._do_post('servers/%s/migrations/%s/action'
                                 % (self.uuid, '3'), 'force_complete', {})
        self.assertEqual(202, response.status_code)

    def test_get_migration(self):
        response = self._do_get('servers/fake_id/migrations/1234')
        self.assertEqual(404, response.status_code)

    def test_list_migrations(self):
        response = self._do_get('servers/fake_id/migrations')
        self.assertEqual(404, response.status_code)


class ServerMigrationsSamplesJsonTestV2_23(test_servers.ServersSampleBase):
    ADMIN_API = True
    sample_dir = "server-migrations"
    microversion = '2.23'
    scenarios = [('v2_23', {'api_major_version': 'v2.1'})]
    UUID_1 = '4cfba335-03d8-49b2-8c52-e69043d1e8fe'
    UUID_2 = '058fc419-a8a8-4e08-b62c-a9841ef9cd3f'

    fake_migrations = [
        {
            'source_node': 'node1',
            'dest_node': 'node2',
            'source_compute': 'compute1',
            'dest_compute': 'compute2',
            'dest_host': '1.2.3.4',
            'status': 'running',
            'instance_uuid': UUID_1,
            'migration_type': 'live-migration',
            'hidden': False,
            'memory_total': 123456,
            'memory_processed': 12345,
            'memory_remaining': 111111,
            'disk_total': 234567,
            'disk_processed': 23456,
            'disk_remaining': 211111,
            'created_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        },
        {
            'source_node': 'node10',
            'dest_node': 'node20',
            'source_compute': 'compute10',
            'dest_compute': 'compute20',
            'dest_host': '5.6.7.8',
            'status': 'migrating',
            'instance_uuid': UUID_2,
            'migration_type': 'resize',
            'hidden': False,
            'memory_total': 456789,
            'memory_processed': 56789,
            'memory_remaining': 400000,
            'disk_total': 96789,
            'disk_processed': 6789,
            'disk_remaining': 90000,
            'created_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        }
    ]

    def setUp(self):
        super(ServerMigrationsSamplesJsonTestV2_23, self).setUp()
        fake_context = context.RequestContext('fake', 'fake')

        self.mig1 = objects.Migration(
            context=fake_context, **self.fake_migrations[0])
        self.mig1.create()

        self.mig2 = objects.Migration(
            context=fake_context, **self.fake_migrations[1])
        self.mig2.create()

        fake_ins = fake_instance.fake_db_instance(uuid=self.UUID_1)
        fake_ins.pop("pci_devices")
        fake_ins.pop("security_groups")
        fake_ins.pop("services")
        fake_ins.pop("tags")
        fake_ins.pop("info_cache")
        fake_ins.pop("id")
        self.instance = objects.Instance(
            context=fake_context,
            **fake_ins)
        self.instance.create()

    def test_get_migration(self):
        response = self._do_get('servers/%s/migrations/%s' %
                                (self.fake_migrations[0]["instance_uuid"],
                                 self.mig1.id))
        self.assertEqual(200, response.status_code)

        self._verify_response('migrations-get',
                              {"server_uuid": self.UUID_1},
                              response, 200)

    def test_list_migrations(self):
        response = self._do_get('servers/%s/migrations' %
                                self.fake_migrations[0]["instance_uuid"])
        self.assertEqual(200, response.status_code)

        self._verify_response('migrations-index',
                              {"server_uuid_1": self.UUID_1},
                              response, 200)


class ServerMigrationsSampleJsonTestV2_24(test_servers.ServersSampleBase):
    ADMIN_API = True
    microversion = '2.24'
    sample_dir = "server-migrations"
    scenarios = [('v2_24', {'api_major_version': 'v2.1'})]
    USE_NEUTRON = True

    def setUp(self):
        """setUp method for server usage."""
        super(ServerMigrationsSampleJsonTestV2_24, self).setUp()
        self.uuid = self._post_server()
        self.context = context.RequestContext('fake', 'fake')
        fake_migration = {
            'source_node': self.compute.host,
            'dest_node': 'node10',
            'source_compute': 'compute1',
            'dest_compute': 'compute12',
            'migration_type': 'live-migration',
            'instance_uuid': self.uuid,
            'status': 'running'}

        self.migration = objects.Migration(context=self.context,
                                           **fake_migration)
        self.migration.create()

    @mock.patch.object(conductor_manager.ComputeTaskManager, '_live_migrate')
    def test_live_migrate_abort(self, _live_migrate):
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        uri = 'servers/%s/migrations/%s' % (self.uuid, self.migration.id)
        response = self._do_delete(uri)
        self.assertEqual(202, response.status_code)

    @mock.patch.object(conductor_manager.ComputeTaskManager, '_live_migrate')
    def test_live_migrate_abort_migration_not_found(self, _live_migrate):
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        uri = 'servers/%s/migrations/%s' % (self.uuid, '45')
        response = self._do_delete(uri)
        self.assertEqual(404, response.status_code)

    @mock.patch.object(conductor_manager.ComputeTaskManager, '_live_migrate')
    def test_live_migrate_abort_migration_not_running(self, _live_migrate):
        self.migration.status = 'completed'
        self.migration.save()
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        uri = 'servers/%s/migrations/%s' % (self.uuid, self.migration.id)
        response = self._do_delete(uri)
        self.assertEqual(400, response.status_code)


class ServerMigrationsSamplesJsonTestV2_59(
    ServerMigrationsSamplesJsonTestV2_23
):
    ADMIN_API = True
    microversion = '2.59'
    scenarios = [('v2_59', {'api_major_version': 'v2.1'})]

    def setUp(self):
        # Add UUIDs to the fake migrations used in the tests.
        self.fake_migrations[0][
            'uuid'] = '12341d4b-346a-40d0-83c6-5f4f6892b650'
        self.fake_migrations[1][
            'uuid'] = '22341d4b-346a-40d0-83c6-5f4f6892b650'
        super(ServerMigrationsSamplesJsonTestV2_59, self).setUp()


class ServerMigrationsSampleJsonTestV2_65(ServerMigrationsSampleJsonTestV2_24):
    ADMIN_API = True
    microversion = '2.65'
    scenarios = [('v2_65', {'api_major_version': 'v2.1'})]
    USE_NEUTRON = True

    @mock.patch.object(conductor_manager.ComputeTaskManager, '_live_migrate')
    def test_live_migrate_abort_migration_queued(self, _live_migrate):
        self.migration.status = 'queued'
        self.migration.save()
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        self.compute._waiting_live_migrations[self.uuid] = (
            self.migration, futurist.Future())
        uri = 'servers/%s/migrations/%s' % (self.uuid, self.migration.id)
        response = self._do_delete(uri)
        self.assertEqual(202, response.status_code)

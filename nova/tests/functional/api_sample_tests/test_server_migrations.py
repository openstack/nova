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

import mock

from nova.conductor import manager as conductor_manager
from nova import db
from nova import objects
from nova.tests.functional.api_sample_tests import test_servers


class ServerMigrationsSampleJsonTest(test_servers.ServersSampleBase):
    extension_name = 'server-migrations'
    scenarios = [('v2_22', {'api_major_version': 'v2.1'})]
    extra_extensions_to_load = ["os-migrate-server", "os-access-ips"]

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
        get_by_id_and_instance.return_value = migration
        self._do_post('servers/%s/action' % self.uuid, 'live-migrate-server',
                      {'hostname': self.compute.host})
        response = self._do_post('servers/%s/migrations/%s/action'
                                 % (self.uuid, '3'), 'force_complete',
                                 {}, api_version='2.22')
        self.assertEqual(202, response.status_code)

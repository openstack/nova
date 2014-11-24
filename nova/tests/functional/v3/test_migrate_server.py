# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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
from nova.tests.functional.v3 import test_servers
from nova import utils


class MigrateServerSamplesJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-migrate-server"
    ctype = 'json'

    def setUp(self):
        """setUp Method for MigrateServer api samples extension

        This method creates the server that will be used in each tests
        """
        super(MigrateServerSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    @mock.patch('nova.conductor.manager.ComputeTaskManager._cold_migrate')
    def test_post_migrate(self, mock_cold_migrate):
        # Get api samples to migrate server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'migrate-server', {})
        self.assertEqual(202, response.status_code)

    def test_post_live_migrate_server(self):
        # Get api samples to server live migrate request.
        def fake_live_migrate(_self, context, instance, scheduler_hint,
                              block_migration, disk_over_commit):
            self.assertEqual(self.uuid, instance["uuid"])
            host = scheduler_hint["host"]
            self.assertEqual(self.compute.host, host)

        self.stubs.Set(conductor_manager.ComputeTaskManager,
                       '_live_migrate',
                       fake_live_migrate)

        def fake_get_compute(context, host):
            service = dict(host=host,
                           binary='nova-compute',
                           topic='compute',
                           report_count=1,
                           updated_at='foo',
                           hypervisor_type='bar',
                           hypervisor_version=utils.convert_version_to_int(
                               '1.0'),
                           disabled=False)
            return {'compute_node': [service]}
        self.stubs.Set(db, "service_get_by_compute_host", fake_get_compute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'live-migrate-server',
                                 {'hostname': self.compute.host})
        self.assertEqual(202, response.status_code)

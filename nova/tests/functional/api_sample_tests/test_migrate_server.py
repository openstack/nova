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
from oslo_utils import versionutils

from nova import exception
from nova import objects
from nova.tests.functional.api_sample_tests import test_servers


class MigrateServerSamplesJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-migrate-server"

    def setUp(self):
        """setUp Method for MigrateServer api samples extension

        This method creates the server that will be used in each tests
        """
        super(MigrateServerSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()
        self.host_attended = self.compute.host

    @mock.patch('nova.conductor.manager.ComputeTaskManager._cold_migrate')
    def test_post_migrate(self, mock_cold_migrate):
        # Get api samples to migrate server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'migrate-server', {})
        self.assertEqual(202, response.status_code)

    def _check_post_live_migrate_server(self, req_subs=None):
        if not req_subs:
            req_subs = {'hostname': self.compute.host}

        def fake_live_migrate(_self, context, instance, scheduler_hint,
                              block_migration, disk_over_commit, request_spec):
            self.assertEqual(self.uuid, instance["uuid"])
            host = scheduler_hint["host"]
            self.assertEqual(self.host_attended, host)

        self.stub_out(
            'nova.conductor.manager.ComputeTaskManager._live_migrate',
            fake_live_migrate)

        def fake_get_compute(context, host):
            service = dict(host=host,
                           binary='nova-compute',
                           topic='compute',
                           report_count=1,
                           updated_at='foo',
                           hypervisor_type='bar',
                           hypervisor_version=(
                                versionutils.convert_version_to_int('1.0')),
                           disabled=False)
            return {'compute_node': [service]}
        self.stub_out("nova.db.service_get_by_compute_host", fake_get_compute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'live-migrate-server',
                                 req_subs)
        self.assertEqual(202, response.status_code)

    def test_post_live_migrate_server(self):
        # Get api samples to server live migrate request.
        self._check_post_live_migrate_server()

    def test_live_migrate_compute_host_not_found(self):
        hostname = 'dummy-host'

        def fake_execute(_self):
            raise exception.ComputeHostNotFound(host=hostname)
        self.stub_out('nova.conductor.tasks.live_migrate.'
                      'LiveMigrationTask._execute', fake_execute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'live-migrate-server',
                                 {'hostname': hostname})
        self.assertEqual(400, response.status_code)


class MigrateServerSamplesJsonTestV225(MigrateServerSamplesJsonTest):
    sample_dir = "os-migrate-server"
    microversion = '2.25'
    scenarios = [('v2_25', {'api_major_version': 'v2.1'})]

    def test_post_migrate(self):
        # no changes for migrate-server
        pass


class MigrateServerSamplesJsonTestV230(MigrateServerSamplesJsonTest):
    sample_dir = "os-migrate-server"
    microversion = '2.30'
    scenarios = [('v2_30', {'api_major_version': 'v2.1'})]

    def test_post_migrate(self):
        # no changes for migrate-server
        pass

    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_post_live_migrate_server(self, compute_node_get_all_by_host):
        # Get api samples to server live migrate request.

        fake_computes = objects.ComputeNodeList(
            objects=[objects.ComputeNode(host='testHost',
                                         hypervisor_hostname='host')])
        compute_node_get_all_by_host.return_value = fake_computes
        self.host_attended = None
        self._check_post_live_migrate_server(
            req_subs={'hostname': self.compute.host,
                      'force': 'False'})

    def test_post_live_migrate_server_with_force(self):
        self.host_attended = self.compute.host
        self._check_post_live_migrate_server(
            req_subs={'hostname': self.compute.host,
                      'force': 'True'})

    def test_live_migrate_compute_host_not_found(self):
        hostname = 'dummy-host'

        def fake_execute(_self):
            raise exception.ComputeHostNotFound(host=hostname)
        self.stub_out('nova.conductor.tasks.live_migrate.'
                      'LiveMigrationTask._execute', fake_execute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'live-migrate-server',
                                 {'hostname': hostname,
                                  'force': 'False'})
        self.assertEqual(400, response.status_code)

# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from nova.conductor import manager as conductor_manager
from nova import db
from nova.tests.image import fake
from nova.tests.integrated.v3 import test_servers


class AdminActionsSamplesJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-admin-actions"

    def setUp(self):
        """setUp Method for AdminActions api samples extension

        This method creates the server that will be used in each tests
        """
        super(AdminActionsSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    def test_post_pause(self):
        # Get api samples to pause server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-pause', {})
        self.assertEqual(response.status, 202)

    def test_post_unpause(self):
        # Get api samples to unpause server request.
        self.test_post_pause()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unpause', {})
        self.assertEqual(response.status, 202)

    def test_post_suspend(self):
        # Get api samples to suspend server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-suspend', {})
        self.assertEqual(response.status, 202)

    def test_post_resume(self):
        # Get api samples to server resume request.
        self.test_post_suspend()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-resume', {})
        self.assertEqual(response.status, 202)

    def test_post_migrate(self):
        # Get api samples to migrate server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-migrate', {})
        self.assertEqual(response.status, 202)

    def test_post_reset_network(self):
        # Get api samples to reset server network request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-network', {})
        self.assertEqual(response.status, 202)

    def test_post_inject_network_info(self):
        # Get api samples to inject network info request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-inject-network-info', {})
        self.assertEqual(response.status, 202)

    def test_post_lock_server(self):
        # Get api samples to lock server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-lock-server', {})
        self.assertEqual(response.status, 202)

    def test_post_unlock_server(self):
        # Get api samples to unlock server request.
        self.test_post_lock_server()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unlock-server', {})
        self.assertEqual(response.status, 202)

    def test_post_backup_server(self):
        # Get api samples to backup server request.
        def image_details(self, context, **kwargs):
            """This stub is specifically used on the backup action."""
            # NOTE(maurosr): I've added this simple stub cause backup action
            # was trapped in infinite loop during fetch image phase since the
            # fake Image Service always returns the same set of images
            return []

        self.stubs.Set(fake._FakeImageService, 'detail', image_details)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-backup-server', {})
        self.assertEqual(response.status, 202)

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
                           hypervisor_version='1',
                           disabled=False)
            return {'compute_node': [service]}
        self.stubs.Set(db, "service_get_by_compute_host", fake_get_compute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-live-migrate',
                                 {'hostname': self.compute.host})
        self.assertEqual(response.status, 202)

    def test_post_reset_state(self):
        # get api samples to server reset state request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-server-state', {})
        self.assertEqual(response.status, 202)


class AdminActionsSamplesXmlTest(AdminActionsSamplesJsonTest):
    ctype = 'xml'

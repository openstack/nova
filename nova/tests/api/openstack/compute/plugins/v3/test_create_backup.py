# Copyright 2011 OpenStack Foundation
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

from nova.api.openstack import common
from nova.api.openstack.compute.plugins.v3 import create_backup
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack.compute.plugins.v3 import \
     admin_only_action_common
from nova.tests.api.openstack import fakes


class CreateBackupTests(admin_only_action_common.CommonMixin,
                        test.NoDBTestCase):
    def setUp(self):
        super(CreateBackupTests, self).setUp()
        self.controller = create_backup.CreateBackupController()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(create_backup, 'CreateBackupController',
                       _fake_controller)
        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-create-backup'),
                                     fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')
        self.mox.StubOutWithMock(common,
                                 'check_img_metadata_properties_quota')
        self.mox.StubOutWithMock(self.compute_api, 'backup')

    def _make_url(self, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        return '/servers/%s/action' % uuid

    def test_create_backup_with_metadata(self):
        metadata = {'123': 'asdf'}
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': metadata,
            },
        }

        image = dict(id='fake-image-id', status='ACTIVE', name='Backup 1',
                     properties=metadata)

        common.check_img_metadata_properties_quota(self.context, metadata)
        instance = self._stub_instance_get()
        self.compute_api.backup(self.context, instance, 'Backup 1',
                                'daily', 1,
                                extra_properties=metadata).AndReturn(image)

        self.mox.ReplayAll()

        res = self._make_request(self._make_url(instance.uuid), body)
        self.assertEqual(202, res.status_int)
        self.assertIn('fake-image-id', res.headers['Location'])

    def test_create_backup_no_name(self):
        # Name is required for backups.
        body = {
            'create_backup': {
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_no_rotation(self):
        # Rotation is required for backup requests.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_negative_rotation(self):
        """Rotation must be greater than or equal to zero
        for backup requests
        """
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': -1,
            },
        }
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_no_backup_type(self):
        # Backup Type (daily or weekly) is required for backup requests.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_bad_entity(self):
        body = {'create_backup': 'go'}
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_rotation_is_zero(self):
        # The happy path for creating backups if rotation is zero.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 0,
            },
        }

        image = dict(id='fake-image-id', status='ACTIVE', name='Backup 1',
                     properties={})
        common.check_img_metadata_properties_quota(self.context, {})
        instance = self._stub_instance_get()
        self.compute_api.backup(self.context, instance, 'Backup 1',
                                'daily', 0,
                                extra_properties={}).AndReturn(image)

        self.mox.ReplayAll()

        res = self._make_request(self._make_url(instance.uuid), body)
        self.assertEqual(202, res.status_int)
        self.assertNotIn('Location', res.headers)

    def test_create_backup_rotation_is_positive(self):
        # The happy path for creating backups if rotation is positive.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        image = dict(id='fake-image-id', status='ACTIVE', name='Backup 1',
                     properties={})
        common.check_img_metadata_properties_quota(self.context, {})
        instance = self._stub_instance_get()
        self.compute_api.backup(self.context, instance, 'Backup 1',
                                'daily', 1,
                                extra_properties={}).AndReturn(image)

        self.mox.ReplayAll()

        res = self._make_request(self._make_url(instance.uuid), body)
        self.assertEqual(202, res.status_int)
        self.assertIn('fake-image-id', res.headers['Location'])

    def test_create_backup_raises_conflict_on_invalid_state(self):
        body_map = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        args_map = {
            'create_backup': (
                ('Backup 1', 'daily', 1), {'extra_properties': {}}
            ),
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_invalid_state('create_backup', method='backup',
                                 body_map=body_map,
                                 compute_api_args_map=args_map)

    def test_create_backup_with_non_existed_instance(self):
        body_map = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_non_existing_instance('create_backup',
                                         body_map=body_map)

    def test_create_backup_with_invalid_create_backup(self):
        body = {
            'create_backupup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        res = self._make_request(self._make_url(), body)
        self.assertEqual(400, res.status_int)

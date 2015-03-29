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

import webob

from nova.api.openstack import common
from nova.api.openstack.compute.contrib import admin_actions as \
    create_backup_v2
from nova.api.openstack.compute.plugins.v3 import create_backup as \
    create_backup_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class CreateBackupTestsV21(admin_only_action_common.CommonMixin,
                        test.NoDBTestCase):
    create_backup = create_backup_v21
    controller_name = 'CreateBackupController'
    validation_error = exception.ValidationError

    def setUp(self):
        super(CreateBackupTestsV21, self).setUp()
        self.controller = getattr(self.create_backup, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.create_backup, self.controller_name,
                       _fake_controller)
        self.mox.StubOutWithMock(self.compute_api, 'get')
        self.mox.StubOutWithMock(common,
                                 'check_img_metadata_properties_quota')
        self.mox.StubOutWithMock(self.compute_api, 'backup')

    def test_create_backup_with_metadata(self):
        metadata = {'123': 'asdf'}
        body = {
            'createBackup': {
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
        res = self.controller._create_backup(self.req, instance.uuid,
                                             body=body)
        self.assertEqual(202, res.status_int)
        self.assertIn('fake-image-id', res.headers['Location'])

    def test_create_backup_no_name(self):
        # Name is required for backups.
        body = {
            'createBackup': {
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_no_rotation(self):
        # Rotation is required for backup requests.
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_negative_rotation(self):
        """Rotation must be greater than or equal to zero
        for backup requests
        """
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': -1,
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_negative_rotation_with_string_number(self):
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': '-1',
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_no_backup_type(self):
        # Backup Type (daily or weekly) is required for backup requests.
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_non_dict_metadata(self):
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': 'non_dict',
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_bad_entity(self):
        body = {'createBackup': 'go'}
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_rotation_is_zero(self):
        # The happy path for creating backups if rotation is zero.
        body = {
            'createBackup': {
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

        res = self.controller._create_backup(self.req, instance.uuid,
                                             body=body)
        self.assertEqual(202, res.status_int)
        self.assertNotIn('Location', res.headers)

    def test_create_backup_rotation_is_positive(self):
        # The happy path for creating backups if rotation is positive.
        body = {
            'createBackup': {
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

        res = self.controller._create_backup(self.req, instance.uuid,
                                             body=body)
        self.assertEqual(202, res.status_int)
        self.assertIn('fake-image-id', res.headers['Location'])

    def test_create_backup_rotation_is_string_number(self):
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': '1',
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

        res = self.controller._create_backup(self.req, instance['uuid'],
                                             body=body)
        self.assertEqual(202, res.status_int)
        self.assertIn('fake-image-id', res.headers['Location'])

    def test_create_backup_raises_conflict_on_invalid_state(self):
        body_map = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        args_map = {
            '_create_backup': (
                ('Backup 1', 'daily', 1), {'extra_properties': {}}
            ),
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_invalid_state('_create_backup', method='backup',
                                 body_map=body_map,
                                 compute_api_args_map=args_map,
                                 exception_arg='createBackup')

    def test_create_backup_with_non_existed_instance(self):
        body_map = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_non_existing_instance('_create_backup',
                                         body_map=body_map)

    def test_create_backup_with_invalid_create_backup(self):
        body = {
            'createBackupup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        self.assertRaises(self.validation_error,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_backup_volume_backed_instance(self):
        body = {
            'createBackup': {
                'name': 'BackupMe',
                'backup_type': 'daily',
                'rotation': 3
            },
        }

        common.check_img_metadata_properties_quota(self.context, {})
        instance = self._stub_instance_get()
        instance.image_ref = None

        self.compute_api.backup(self.context, instance, 'BackupMe', 'daily', 3,
                extra_properties={}).AndRaise(exception.InvalidRequest())

        self.mox.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._create_backup,
                          self.req, instance['uuid'], body=body)


class CreateBackupTestsV2(CreateBackupTestsV21):
    create_backup = create_backup_v2
    controller_name = 'AdminActionsController'
    validation_error = webob.exc.HTTPBadRequest

    def test_create_backup_with_invalid_create_backup(self):
        # NOTE(gmann):V2 API does not raise bad request for below type of
        # invalid body in controller method.
        body = {
            'createBackupup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        self.assertRaises(KeyError,
                          self.controller._create_backup,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_backup_non_dict_metadata(self):
        pass


class CreateBackupPolicyEnforcementv21(test.NoDBTestCase):

    def setUp(self):
        super(CreateBackupPolicyEnforcementv21, self).setUp()
        self.controller = create_backup_v21.CreateBackupController()
        self.req = fakes.HTTPRequest.blank('')

    def test_create_backup_policy_failed(self):
        rule_name = "os_compute_api:os-create-backup"
        self.policy.set_rules({rule_name: "project:non_fake"})
        metadata = {'123': 'asdf'}
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': metadata,
            },
        }
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._create_backup, self.req, fakes.FAKE_UUID,
            body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

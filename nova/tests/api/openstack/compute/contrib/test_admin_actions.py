#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import webob

from nova.api.openstack import common
from nova.api.openstack.compute.contrib import admin_actions
from nova.compute import vm_states
import nova.context
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


class CommonMixin(object):
    def setUp(self):
        super(CommonMixin, self).setUp()
        self.controller = admin_actions.AdminActionsController()
        self.compute_api = self.controller.compute_api
        self.context = nova.context.RequestContext('fake', 'fake')

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(admin_actions, 'AdminActionsController',
                       _fake_controller)

        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Admin_actions'])

        self.app = fakes.wsgi_app(init_only=('servers',),
                                  fake_auth_context=self.context)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def _make_request(self, url, body):
        req = webob.Request.blank('/v2/fake' + url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        return req.get_response(self.app)

    def _stub_instance_get(self, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_db_instance(
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        instance = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), instance)
        self.compute_api.get(self.context, uuid,
                             want_objects=True).AndReturn(instance)
        return instance

    def _stub_instance_get_failure(self, exc_info, uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        self.compute_api.get(self.context, uuid,
                             want_objects=True).AndRaise(exc_info)
        return uuid

    def _test_non_existing_instance(self, action, body_map=None):
        uuid = uuidutils.generate_uuid()
        self._stub_instance_get_failure(
                exception.InstanceNotFound(instance_id=uuid), uuid=uuid)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % uuid,
                                 {action: body_map.get(action)})
        self.assertEqual(404, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_action(self, action, body=None, method=None):
        if method is None:
            method = action

        instance = self._stub_instance_get()
        getattr(self.compute_api, method)(self.context, instance)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: None})
        self.assertEqual(202, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_invalid_state(self, action, method=None, body_map=None,
                            compute_api_args_map=None):
        if method is None:
            method = action
        if body_map is None:
            body_map = {}
        if compute_api_args_map is None:
            compute_api_args_map = {}

        instance = self._stub_instance_get()

        args, kwargs = compute_api_args_map.get(action, ((), {}))

        getattr(self.compute_api, method)(self.context, instance,
                                          *args, **kwargs).AndRaise(
                exception.InstanceInvalidState(
                    attr='vm_state', instance_uuid=instance['uuid'],
                    state='foo', method=method))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: body_map.get(action)})
        self.assertEqual(409, res.status_int)
        self.assertIn("Cannot \'%s\' while instance" % action, res.body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_not_implemented_state(self, action, method=None,
                                    error_text=None):
        if method is None:
            method = action
        body_map = {}
        compute_api_args_map = {}
        instance = self._stub_instance_get()
        args, kwargs = compute_api_args_map.get(action, ((), {}))
        getattr(self.compute_api, method)(self.context, instance,
                                          *args, **kwargs).AndRaise(
                NotImplementedError())
        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: body_map.get(action)})
        self.assertEqual(501, res.status_int)
        self.assertIn(error_text, res.body)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def _test_locked_instance(self, action, method=None):
        if method is None:
            method = action

        instance = self._stub_instance_get()
        getattr(self.compute_api, method)(self.context, instance).AndRaise(
                exception.InstanceIsLocked(instance_uuid=instance['uuid']))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: None})
        self.assertEqual(409, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()


class AdminActionsTest(CommonMixin, test.NoDBTestCase):
    def test_actions(self):
        actions = ['pause', 'unpause', 'suspend', 'resume', 'migrate',
                   'resetNetwork', 'injectNetworkInfo', 'lock',
                   'unlock']
        method_translations = {'migrate': 'resize',
                               'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        for action in actions:
            method = method_translations.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_action(action, method=method)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_raise_conflict_on_invalid_state(self):
        actions = ['pause', 'unpause', 'suspend', 'resume', 'migrate',
                   'os-migrateLive']
        method_translations = {'migrate': 'resize',
                               'os-migrateLive': 'live_migrate'}
        body_map = {'os-migrateLive':
                        {'host': 'hostname',
                         'block_migration': False,
                         'disk_over_commit': False}}
        args_map = {'os-migrateLive': ((False, False, 'hostname'), {})}

        for action in actions:
            method = method_translations.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_invalid_state(action, method=method, body_map=body_map,
                                     compute_api_args_map=args_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_raise_on_not_implemented(self):
        tests = [
            ('pause', 'Virt driver does not implement pause function.'),
            ('unpause', 'Virt driver does not implement unpause function.')
        ]
        for (action, error_text) in tests:
            self.mox.StubOutWithMock(self.compute_api, action)
            self._test_not_implemented_state(action, error_text=error_text)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_with_non_existed_instance(self):
        actions = ['pause', 'unpause', 'suspend', 'resume',
                   'resetNetwork', 'injectNetworkInfo', 'lock',
                   'unlock', 'os-resetState', 'migrate', 'os-migrateLive']
        body_map = {'os-resetState': {'state': 'active'},
                    'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}}
        for action in actions:
            self._test_non_existing_instance(action,
                                             body_map=body_map)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_actions_with_locked_instance(self):
        actions = ['pause', 'unpause', 'suspend', 'resume', 'migrate',
                   'resetNetwork', 'injectNetworkInfo']
        method_translations = {'migrate': 'resize',
                               'resetNetwork': 'reset_network',
                               'injectNetworkInfo': 'inject_network_info'}

        for action in actions:
            method = method_translations.get(action)
            self.mox.StubOutWithMock(self.compute_api, method or action)
            self._test_locked_instance(action, method=method)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

    def _test_migrate_exception(self, exc_info, expected_result):
        self.mox.StubOutWithMock(self.compute_api, 'resize')
        instance = self._stub_instance_get()
        self.compute_api.resize(self.context, instance).AndRaise(exc_info)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {'migrate': None})
        self.assertEqual(expected_result, res.status_int)

    def _test_migrate_live_succeeded(self, param):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')
        instance = self._stub_instance_get()
        self.compute_api.live_migrate(self.context, instance, False,
                                      False, 'hostname')

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {'os-migrateLive': param})
        self.assertEqual(202, res.status_int)

    def test_migrate_live_enabled(self):
        param = {'host': 'hostname',
                 'block_migration': False,
                 'disk_over_commit': False}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_enabled_with_string_param(self):
        param = {'host': 'hostname',
                 'block_migration': "False",
                 'disk_over_commit': "False"}
        self._test_migrate_live_succeeded(param)

    def test_migrate_live_missing_dict_param(self):
        body = {'os-migrateLive': {'dummy': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}}
        res = self._make_request('/servers/FAKE/action', body)
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_block_migration(self):
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': "foo",
                                   'disk_over_commit': False}}
        res = self._make_request('/servers/FAKE/action', body)
        self.assertEqual(400, res.status_int)

    def test_migrate_live_with_invalid_disk_over_commit(self):
        body = {'os-migrateLive': {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': "foo"}}
        res = self._make_request('/servers/FAKE/action', body)
        self.assertEqual(400, res.status_int)

    def _test_migrate_live_failed_with_exception(self, fake_exc,
                                                 uuid=None):
        self.mox.StubOutWithMock(self.compute_api, 'live_migrate')

        instance = self._stub_instance_get(uuid=uuid)
        self.compute_api.live_migrate(self.context, instance, False,
                                      False, 'hostname').AndRaise(fake_exc)

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance.uuid,
                                 {'os-migrateLive':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(400, res.status_int)
        self.assertIn(unicode(fake_exc), res.body)

    def test_migrate_live_compute_service_unavailable(self):
        self._test_migrate_live_failed_with_exception(
            exception.ComputeServiceUnavailable(host='host'))

    def test_migrate_live_invalid_hypervisor_type(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidHypervisorType())

    def test_migrate_live_unable_to_migrate_to_self(self):
        uuid = uuidutils.generate_uuid()
        self._test_migrate_live_failed_with_exception(
                exception.UnableToMigrateToSelf(instance_id=uuid,
                                                host='host'),
                uuid=uuid)

    def test_migrate_live_destination_hypervisor_too_old(self):
        self._test_migrate_live_failed_with_exception(
            exception.DestinationHypervisorTooOld())

    def test_migrate_live_no_valid_host(self):
        self._test_migrate_live_failed_with_exception(
            exception.NoValidHost(reason=''))

    def test_migrate_live_invalid_local_storage(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidLocalStorage(path='', reason=''))

    def test_migrate_live_invalid_shared_storage(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidSharedStorage(path='', reason=''))

    def test_migrate_live_migration_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_unlock_not_authorized(self):
        self.mox.StubOutWithMock(self.compute_api, 'unlock')

        instance = self._stub_instance_get()

        self.compute_api.unlock(self.context, instance).AndRaise(
                exception.PolicyNotAuthorized(action='unlock'))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {'unlock': None})
        self.assertEqual(403, res.status_int)


class CreateBackupTests(CommonMixin, test.NoDBTestCase):
    def setUp(self):
        super(CreateBackupTests, self).setUp()
        self.mox.StubOutWithMock(common,
                                 'check_img_metadata_properties_quota')
        self.mox.StubOutWithMock(self.compute_api,
                                 'backup')

    def _make_url(self, uuid):
        return '/servers/%s/action' % uuid

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

        res = self._make_request(self._make_url(instance['uuid']), body)
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
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_no_rotation(self):
        # Rotation is required for backup requests.
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)

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
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_no_backup_type(self):
        # Backup Type (daily or weekly) is required for backup requests.
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)

    def test_create_backup_bad_entity(self):
        body = {'createBackup': 'go'}
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)

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

        res = self._make_request(self._make_url(instance['uuid']), body)
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

        res = self._make_request(self._make_url(instance['uuid']), body)
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
            'createBackup': (
                ('Backup 1', 'daily', 1), {'extra_properties': {}}
            ),
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_invalid_state('createBackup', method='backup',
                                 body_map=body_map,
                                 compute_api_args_map=args_map)

    def test_create_backup_with_non_existed_instance(self):
        body_map = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        common.check_img_metadata_properties_quota(self.context, {})
        self._test_non_existing_instance('createBackup',
                                         body_map=body_map)

    def test_create_backup_with_invalid_createBackup(self):
        body = {
            'createBackupup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        res = self._make_request(self._make_url('fake'), body)
        self.assertEqual(400, res.status_int)


class ResetStateTests(test.NoDBTestCase):
    def setUp(self):
        super(ResetStateTests, self).setUp()

        self.uuid = uuidutils.generate_uuid()

        self.admin_api = admin_actions.AdminActionsController()
        self.compute_api = self.admin_api.compute_api

        url = '/fake/servers/%s/action' % self.uuid
        self.request = fakes.HTTPRequest.blank(url)
        self.context = self.request.environ['nova.context']

    def test_no_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"os-resetState": None})

    def test_bad_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"os-resetState": {"state": "spam"}})

    def test_no_instance(self):
        self.mox.StubOutWithMock(self.compute_api, 'get')
        exc = exception.InstanceNotFound(instance_id='inst_id')
        self.compute_api.get(self.context, self.uuid,
                             want_objects=True).AndRaise(exc)

        self.mox.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"os-resetState": {"state": "active"}})

    def _setup_mock(self, expected):
        instance = instance_obj.Instance()
        instance.uuid = self.uuid
        instance.vm_state = 'fake'
        instance.task_state = 'fake'
        instance.obj_reset_changes()

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api, 'get')

        def check_state(admin_state_reset=True):
            self.assertEqual(set(expected.keys()),
                             instance.obj_what_changed())
            for k, v in expected.items():
                self.assertEqual(v, getattr(instance, k),
                                 "Instance.%s doesn't match" % k)
            instance.obj_reset_changes()

        self.compute_api.get(self.context, instance.uuid,
                             want_objects=True).AndReturn(instance)
        instance.save(admin_state_reset=True).WithSideEffects(check_state)

    def test_reset_active(self):
        self._setup_mock(dict(vm_state=vm_states.ACTIVE,
                              task_state=None))
        self.mox.ReplayAll()

        body = {"os-resetState": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(result.status_int, 202)

    def test_reset_error(self):
        self._setup_mock(dict(vm_state=vm_states.ERROR,
                              task_state=None))
        self.mox.ReplayAll()
        body = {"os-resetState": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(result.status_int, 202)

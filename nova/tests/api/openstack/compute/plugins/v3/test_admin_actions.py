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

import datetime

from oslo.config import cfg
import webob

from nova.api.openstack import compute
from nova.api.openstack.compute.plugins.v3 import admin_actions
from nova.compute import api as compute_api
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


CONF = cfg.CONF

INSTANCE = {
             "id": 1,
             "name": "fake",
             "display_name": "test_server",
             "uuid": "abcd",
             "user_id": 'fake_user_id',
             "tenant_id": 'fake_tenant_id',
             "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
             "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
             "launched_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
             "security_groups": [{"id": 1, "name": "test"}],
             "progress": 0,
             "image_ref": 'http://foo.com/123',
             "fixed_ips": [],
             "instance_type": {"flavorid": '124'},
        }


def fake_compute_api(*args, **kwargs):
    return True


def fake_compute_api_raises_invalid_state(*args, **kwargs):
    raise exception.InstanceInvalidState(attr='fake_attr',
            state='fake_state', method='fake_method',
            instance_uuid='fake')


def fake_compute_api_get(self, context, instance_uuid, want_objects=False):
    instance = fake_instance.fake_db_instance(
            id=1, uuid=instance_uuid, vm_state=vm_states.ACTIVE,
            task_state=None, launched_at=timeutils.utcnow())
    if want_objects:
        instance = instance_obj.Instance._from_db_object(
                context, instance_obj.Instance(), instance)
    return instance


def fake_compute_api_get_non_found(self, context, instance_id,
                                   want_objects=False):
    raise exception.InstanceNotFound(instance_id=instance_id)


def fake_compute_api_raises_instance_is_locked(*args, **kwargs):
    raise exception.InstanceIsLocked(instance_uuid='')


def fake_compute_api_resize_non_found_flavor(self, context, instance_id):
    raise exception.FlavorNotFound(flavor_id='')


def fake_compute_api_can_not_resize_to_same_flavor(self, context,
                                                   instance_id):
    raise exception.CannotResizeToSameFlavor()


def fake_compute_api_too_many_instaces(self, context, instance_id):
    raise exception.TooManyInstances(overs='', req='', used=0, allowed=0,
                                     resource='')


class AdminActionsTest(test.TestCase):

    _actions = ('pause', 'unpause', 'suspend', 'resume', 'migrate',
                'reset_network', 'inject_network_info', 'lock', 'unlock')

    _methods = ('pause', 'unpause', 'suspend', 'resume', 'resize',
                'reset_network', 'inject_network_info', 'lock', 'unlock')

    _actions_that_check_state = (
            # action, method
            ('pause', 'pause'),
            ('unpause', 'unpause'),
            ('suspend', 'suspend'),
            ('resume', 'resume'),
            ('migrate', 'resize'))

    _actions_that_check_non_existed_instance = ('pause', 'unpause', 'suspend',
         'resume', 'migrate', 'reset_network', 'inject_network_info', 'lock',
         'unlock')

    _actions_that_check_is_locked = zip(
        ('pause', 'unpause', 'suspend',
         'resume', 'migrate', 'reset_network', 'inject_network_info'),
        ('pause', 'unpause', 'suspend',
         'resume', 'resize', 'reset_network', 'inject_network_info'))

    def setUp(self):
        super(AdminActionsTest, self).setUp()
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        self.UUID = uuidutils.generate_uuid()
        self.app = fakes.wsgi_app_v3(init_only=('servers',
                                                'os-admin-actions'))
        for _method in self._methods:
            self.stubs.Set(compute_api.API, _method, fake_compute_api)

    def _make_request(self, url, body):
        req = webob.Request.blank(url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        return req.get_response(self.app)

    def test_admin_api_actions(self):
        for _action in self._actions:
            res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                     {_action: None})
            self.assertEqual(res.status_int, 202)

    def test_admin_api_actions_raise_conflict_on_invalid_state(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        for _action, _method in self._actions_that_check_state:
            self.stubs.Set(compute_api.API, _method,
                fake_compute_api_raises_invalid_state)
            res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                     {_action: None})
            self.assertEqual(res.status_int, 409)
            self.assertIn("Cannot \'%(_action)s\' while instance" % locals(),
                    res.body)

    def test_admin_api_actions_with_non_existed_instance(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get_non_found)
        for _action in self._actions_that_check_non_existed_instance:
            res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                     {_action: None})
            self.assertEqual(res.status_int, 404)

    def test_admin_api_actions_with_locked_instance(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        for _action, _method in self._actions_that_check_is_locked:
            self.stubs.Set(compute_api.API, _method,
                           fake_compute_api_raises_instance_is_locked)
            res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                     {_action: None})
            self.assertEqual(res.status_int, 409)

    def test_reset_state_with_non_existed_instance(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get_non_found)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'reset_state': {'state': 'active'}})
        self.assertEqual(res.status_int, 404)

    def test_migrate_with_non_existed_flavor(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'resize',
            fake_compute_api_resize_non_found_flavor)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate': None})
        self.assertEqual(res.status_int, 404)

    def test_migrate_resize_to_same_flavor(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'resize',
            fake_compute_api_can_not_resize_to_same_flavor)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate': None})
        self.assertEqual(res.status_int, 400)

    def test_migrate_too_many_instances(self):
        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        self.stubs.Set(compute_api.API, 'resize',
            fake_compute_api_too_many_instaces)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate': None})
        self.assertEqual(res.status_int, 413)

    def test_migrate_live_enabled(self):
        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        def fake_migrate_server(self, context, instance,
                scheduler_hint, live, rebuild, flavor,
                block_migration, disk_over_commit):
            return None

        self.stubs.Set(compute_api.API, 'update', fake_update)
        self.stubs.Set(conductor_api.ComputeTaskAPI,
                       'migrate_server',
                       fake_migrate_server)

        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate_live':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(res.status_int, 202)

    def test_migrate_live_with_non_existed_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get_non_found)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate_live':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(res.status_int, 404)

    def test_migrate_live_missing_dict_param(self):
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate_live':
                                  {'dummy': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(res.status_int, 400)

    def _test_migrate_live_failed_with_exception(self, fake_exc):
        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        def fake_migrate_server(self, context, instance,
                scheduler_hint, live, rebuild, flavor,
                block_migration, disk_over_commit):
            raise fake_exc

        self.stubs.Set(compute_api.API, 'update', fake_update)
        self.stubs.Set(conductor_api.ComputeTaskAPI,
                       'migrate_server',
                       fake_migrate_server)

        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate_live':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(res.status_int, 400)
        self.assertIn(unicode(fake_exc), res.body)

    def test_migrate_live_compute_service_unavailable(self):
        self._test_migrate_live_failed_with_exception(
            exception.ComputeServiceUnavailable(host='host'))

    def test_migrate_live_invalid_hypervisor_type(self):
        self._test_migrate_live_failed_with_exception(
            exception.InvalidHypervisorType())

    def test_migrate_live_unable_to_migrate_to_self(self):
        self._test_migrate_live_failed_with_exception(
            exception.UnableToMigrateToSelf(instance_id=self.UUID,
                                            host='host'))

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

    def test_migrate_live_pre_check_error(self):
        self._test_migrate_live_failed_with_exception(
            exception.MigrationPreCheckError(reason=''))

    def test_migrate_live_with_instance_invalid_state(self):
        def fake_live_migrate(self, context, instance, block_migration,
                              disk_over_commit, host_name):
            raise exception.InstanceInvalidState(instance_uuid='', attr='',
                                                 state='', method='')

        self.stubs.Set(compute_api.API, 'live_migrate', fake_live_migrate)
        res = self._make_request('/v3/servers/%s/action' % self.UUID,
                                 {'migrate_live':
                                  {'host': 'hostname',
                                   'block_migration': False,
                                   'disk_over_commit': False}})
        self.assertEqual(res.status_int, 409)

    def test_unlock_not_authorized(self):
        def fake_unlock(*args, **kwargs):
            raise exception.PolicyNotAuthorized(action='unlock')

        self.stubs.Set(compute_api.API, 'unlock', fake_unlock)

        app = fakes.wsgi_app_v3(init_only=('servers', 'os-admin-actions'))
        req = webob.Request.blank('/v3/servers/%s/action' %
                self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({'unlock': None})
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 403)


class CreateBackupTests(test.TestCase):

    def setUp(self):
        super(CreateBackupTests, self).setUp()

        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        self.backup_stubs = fakes.stub_out_compute_api_backup(self.stubs)
        self.app = compute.APIRouterV3(init_only=('servers',
                                                  'os-admin-actions'))
        self.uuid = uuidutils.generate_uuid()

    def _get_request(self, body):
        url = '/servers/%s/action' % self.uuid
        req = fakes.HTTPRequestV3.blank(url)
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = jsonutils.dumps(body)
        return req

    def test_create_backup_with_metadata(self):
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': {'123': 'asdf'},
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)

        self.assertEqual(response.status_int, 202)
        self.assertTrue(response.headers['Location'])

    def test_create_backup_with_too_much_metadata(self):
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': {'123': 'asdf'},
            },
        }
        for num in range(CONF.quota_metadata_items + 1):
            body['create_backup']['metadata']['foo%i' % num] = "bar"

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 413)

    def test_create_backup_no_name(self):
        # Name is required for backups.
        body = {
            'create_backup': {
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_no_rotation(self):
        # Rotation is required for backup requests.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

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

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_no_backup_type(self):
        # Backup Type (daily or weekly) is required for backup requests.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_bad_entity(self):
        body = {'create_backup': 'go'}

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_rotation_is_zero(self):
        # The happy path for creating backups if rotation is zero.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 0,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)

        self.assertEqual(response.status_int, 202)
        self.assertFalse('Location' in response.headers)

    def test_create_backup_rotation_is_positive(self):
        # The happy path for creating backups if rotation is positive.
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)

        self.assertEqual(response.status_int, 202)
        self.assertTrue(response.headers['Location'])

    def test_create_backup_raises_conflict_on_invalid_state(self):
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        self.stubs.Set(compute_api.API, 'backup',
                fake_compute_api_raises_invalid_state)

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 409)

    def test_create_backup_with_non_existed_instance(self):
        body = {
            'create_backup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get_non_found)
        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 404)


class ResetStateTests(test.TestCase):
    def setUp(self):
        super(ResetStateTests, self).setUp()

        self.uuid = uuidutils.generate_uuid()

        self.admin_api = admin_actions.AdminActionsController()
        self.compute_api = self.admin_api.compute_api

        url = '/servers/%s/action' % self.uuid
        self.request = fakes.HTTPRequestV3.blank(url)
        self.context = self.request.environ['nova.context']

    def test_no_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": None})

    def test_bad_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": {"state": "spam"}})

    def test_no_instance(self):
        self.mox.StubOutWithMock(self.compute_api, 'get')
        exc = exception.InstanceNotFound(instance_id='inst_ud')
        self.compute_api.get(self.context, self.uuid,
                             want_objects=True).AndRaise(exc)

        self.mox.ReplayAll()

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, self.uuid,
                          {"reset_state": {"state": "active"}})

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

        body = {"reset_state": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(result.status_int, 202)

    def test_reset_error(self):
        self._setup_mock(dict(vm_state=vm_states.ERROR,
                              task_state=None))
        self.mox.ReplayAll()
        body = {"reset_state": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, self.uuid, body)

        self.assertEqual(result.status_int, 202)

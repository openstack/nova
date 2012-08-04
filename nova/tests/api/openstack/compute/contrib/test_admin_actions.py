#   Copyright 2011 OpenStack LLC.
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

import webob

from nova.api.openstack import compute as compute_api
from nova.api.openstack.compute.contrib import admin_actions
from nova import compute
from nova.compute import vm_states
from nova import context
from nova import exception
from nova import flags
from nova.openstack.common import jsonutils
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


FLAGS = flags.FLAGS

INSTANCE = {
             "id": 1,
             "name": "fake",
             "display_name": "test_server",
             "uuid": "abcd",
             "user_id": 'fake_user_id',
             "tenant_id": 'fake_tenant_id',
             "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
             "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
             "security_groups": [{"id": 1, "name": "test"}],
             "progress": 0,
             "image_ref": 'http://foo.com/123',
             "fixed_ips": [],
             "instance_type": {"flavorid": '124'},
        }


def fake_compute_api(*args, **kwargs):
    return True


def fake_compute_api_raises_invalid_state(*args, **kwargs):
    raise exception.InstanceInvalidState


def fake_compute_api_get(self, context, instance_id):
    return {'id': 1, 'uuid': instance_id, 'vm_state': vm_states.ACTIVE,
            'task_state': None}


def fake_scheduler_api_live_migration(self, context, dest,
                                      block_migration=False,
                                      disk_over_commit=False, instance=None,
                                      instance_id=None):
    return None


class AdminActionsTest(test.TestCase):

    _actions = ('pause', 'unpause', 'suspend', 'resume', 'migrate',
                'resetNetwork', 'injectNetworkInfo', 'lock', 'unlock')

    _methods = ('pause', 'unpause', 'suspend', 'resume', 'resize',
                'reset_network', 'inject_network_info', 'lock', 'unlock')

    _actions_that_check_state = (
            # action, method
            ('pause', 'pause'),
            ('unpause', 'unpause'),
            ('suspend', 'suspend'),
            ('resume', 'resume'),
            ('migrate', 'resize'))

    def setUp(self):
        super(AdminActionsTest, self).setUp()
        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        self.UUID = utils.gen_uuid()
        for _method in self._methods:
            self.stubs.Set(compute.API, _method, fake_compute_api)
        self.stubs.Set(scheduler_rpcapi.SchedulerAPI,
                       'live_migration',
                       fake_scheduler_api_live_migration)

    def test_admin_api_actions(self):
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/servers/%s/action' %
                    self.UUID)
            req.method = 'POST'
            req.body = jsonutils.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_admin_api_actions_raise_conflict_on_invalid_state(self):
        app = fakes.wsgi_app()

        for _action, _method in self._actions_that_check_state:
            self.stubs.Set(compute.API, _method,
                fake_compute_api_raises_invalid_state)

            req = webob.Request.blank('/v2/fake/servers/%s/action' %
                    self.UUID)
            req.method = 'POST'
            req.body = jsonutils.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 409)
            self.assertIn("invalid state for '%(_action)s'" % locals(),
                    res.body)

    def test_migrate_live_enabled(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'os-migrateLive': {
                'host': 'hostname',
                'block_migration': False,
                'disk_over_commit': False,
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 202)

    def test_migrate_live_missing_dict_param(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'os-migrateLive': {
                'dummy': 'hostname',
                'block_migration': False,
                'disk_over_commit': False,
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 400)


class CreateBackupTests(test.TestCase):

    def setUp(self):
        super(CreateBackupTests, self).setUp()

        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        self.backup_stubs = fakes.stub_out_compute_api_backup(self.stubs)
        self.app = compute_api.APIRouter()
        self.uuid = utils.gen_uuid()

    def _get_request(self, body):
        url = '/fake/servers/%s/action' % self.uuid
        req = fakes.HTTPRequest.blank(url)
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = jsonutils.dumps(body)
        return req

    def test_create_backup_with_metadata(self):
        body = {
            'createBackup': {
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
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': {'123': 'asdf'},
            },
        }
        for num in range(FLAGS.quota_metadata_items + 1):
            body['createBackup']['metadata']['foo%i' % num] = "bar"

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 413)

    def test_create_backup_no_name(self):
        """Name is required for backups"""
        body = {
            'createBackup': {
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_no_rotation(self):
        """Rotation is required for backup requests"""
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_no_backup_type(self):
        """Backup Type (daily or weekly) is required for backup requests"""
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup_bad_entity(self):
        body = {'createBackup': 'go'}

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 400)

    def test_create_backup(self):
        """The happy path for creating backups"""
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        request = self._get_request(body)
        response = request.get_response(self.app)

        self.assertTrue(response.headers['Location'])

    def test_create_backup_raises_conflict_on_invalid_state(self):
        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        self.stubs.Set(compute.API, 'backup',
                fake_compute_api_raises_invalid_state)

        request = self._get_request(body)
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 409)


class ResetStateTests(test.TestCase):
    def setUp(self):
        super(ResetStateTests, self).setUp()

        self.exists = True
        self.kwargs = None
        self.uuid = utils.gen_uuid()

        def fake_get(inst, context, instance_id):
            if self.exists:
                return dict(id=1, uuid=instance_id, vm_state=vm_states.ACTIVE)
            raise exception.InstanceNotFound()

        def fake_update(inst, context, instance, **kwargs):
            self.kwargs = kwargs

        self.stubs.Set(compute.API, 'get', fake_get)
        self.stubs.Set(compute.API, 'update', fake_update)
        self.admin_api = admin_actions.AdminActionsController()

        url = '/fake/servers/%s/action' % self.uuid
        self.request = fakes.HTTPRequest.blank(url)

    def test_no_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, 'inst_id',
                          {"os-resetState": None})

    def test_bad_state(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.admin_api._reset_state,
                          self.request, 'inst_id',
                          {"os-resetState": {"state": "spam"}})

    def test_no_instance(self):
        self.exists = False
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.admin_api._reset_state,
                          self.request, 'inst_id',
                          {"os-resetState": {"state": "active"}})

    def test_reset_active(self):
        body = {"os-resetState": {"state": "active"}}
        result = self.admin_api._reset_state(self.request, 'inst_id', body)

        self.assertEqual(result.status_int, 202)
        self.assertEqual(self.kwargs, dict(vm_state=vm_states.ACTIVE,
                                           task_state=None))

    def test_reset_error(self):
        body = {"os-resetState": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, 'inst_id', body)

        self.assertEqual(result.status_int, 202)
        self.assertEqual(self.kwargs, dict(vm_state=vm_states.ERROR,
                                           task_state=None))

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
import json

import webob

from nova.api.openstack import v2
from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.tests.api.openstack import fakes


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
    return {'id': 1, 'uuid': instance_id}


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
        self.flags(allow_admin_api=True)
        for _method in self._methods:
            self.stubs.Set(compute.API, _method, fake_compute_api)

    def test_admin_api_actions(self):
        self.maxDiff = None
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/servers/%s/action' %
                    self.UUID)
            req.method = 'POST'
            req.body = json.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_admin_api_actions_raise_conflict_on_invalid_state(self):
        self.maxDiff = None
        app = fakes.wsgi_app()

        for _action, _method in self._actions_that_check_state:
            self.stubs.Set(compute.API, _method,
                fake_compute_api_raises_invalid_state)

            req = webob.Request.blank('/v2/fake/servers/%s/action' %
                    self.UUID)
            req.method = 'POST'
            req.body = json.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 409)
            self.assertIn("invalid state for '%(_action)s'" % locals(),
                    res.body)


class CreateBackupTests(test.TestCase):

    def setUp(self):
        super(CreateBackupTests, self).setUp()

        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        self.backup_stubs = fakes.stub_out_compute_api_backup(self.stubs)

        self.flags(allow_admin_api=True)
        router = v2.APIRouter()
        ext_middleware = extensions.ExtensionMiddleware(router)
        self.app = wsgi.LazySerializationMiddleware(ext_middleware)

        self.uuid = utils.gen_uuid()

    def _get_request(self, body):
        url = '/fake/servers/%s/action' % self.uuid
        req = fakes.HTTPRequest.blank(url)
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
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
        instance_ref = self.backup_stubs.extra_props_last_call['instance_ref']
        expected_server_location = 'http://localhost/v2/servers/%s' % self.uuid
        self.assertEqual(expected_server_location, instance_ref)

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

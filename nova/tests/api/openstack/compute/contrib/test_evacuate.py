#   Copyright 2013 OpenStack Foundation
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

import uuid

from oslo.config import cfg
import webob

from nova.compute import api as compute_api
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')


def fake_compute_api(*args, **kwargs):
    return True


def fake_compute_api_get(self, context, instance_id):
    # BAD_UUID is something that does not exist
    if instance_id == 'BAD_UUID':
        raise exception.InstanceNotFound(instance_id=instance_id)
    else:
        return {
            'id': 1,
            'uuid': instance_id,
            'vm_state': vm_states.ACTIVE,
            'task_state': None, 'host': 'host1'
        }


def fake_service_get_by_compute_host(self, context, host):
    if host == 'bad_host':
        raise exception.ComputeHostNotFound(host=host)
    else:
        return {
            'host_name': host,
            'service': 'compute',
            'zone': 'nova'
            }


class EvacuateTest(test.TestCase):

    _methods = ('resize', 'evacuate')

    def setUp(self):
        super(EvacuateTest, self).setUp()
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        self.stubs.Set(compute_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)
        self.UUID = uuid.uuid4()
        for _method in self._methods:
            self.stubs.Set(compute_api.API, _method, fake_compute_api)

    def test_evacuate_with_valid_instance(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'false',
                'adminPass': 'MyNewPass'
                }
            })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 200)

    def test_evacuate_with_invalid_instance(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % 'BAD_UUID')
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'false',
                'adminPass': 'MyNewPass'
                }
            })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 404)

    def test_evacuate_with_active_service(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'false',
                'adminPass': 'MyNewPass'
                }
            })

        def fake_evacuate(*args, **kwargs):
            raise exception.ComputeServiceUnavailable("Service Unavailable")

        self.stubs.Set(compute_api.API, 'evacuate', fake_evacuate)

        res = req.get_response(app)
        self.assertEqual(res.status_int, 400)

    def test_evacuate_instance_with_no_target(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'onSharedStorage': 'False',
                'adminPass': 'MyNewPass'
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 400)

    def test_evacuate_instance_with_bad_target(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'bad_host',
                'onSharedStorage': 'false',
                'adminPass': 'MyNewPass'
                }
            })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 404)

    def test_evacuate_instance_with_target(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        uuid1 = self.UUID
        req = webob.Request.blank('/v2/fake/servers/%s/action' % uuid1)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'false',
                'adminPass': 'MyNewPass'
            }
        })
        req.content_type = 'application/json'

        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        self.stubs.Set(compute_api.API, 'update', fake_update)

        resp = req.get_response(app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual("MyNewPass", resp_json['adminPass'])

    def test_evacuate_shared_and_pass(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        uuid1 = self.UUID
        req = webob.Request.blank('/v2/fake/servers/%s/action' % uuid1)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'True',
                'adminPass': 'MyNewPass'
            }
        })
        req.content_type = 'application/json'

        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        self.stubs.Set(compute_api.API, 'update', fake_update)

        res = req.get_response(app)
        self.assertEqual(res.status_int, 400)

    def test_evacuate_not_shared_pass_generated(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        uuid1 = self.UUID
        req = webob.Request.blank('/v2/fake/servers/%s/action' % uuid1)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'False',
            }
        })

        req.content_type = 'application/json'

        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        self.stubs.Set(compute_api.API, 'update', fake_update)

        resp = req.get_response(app)
        self.assertEqual(resp.status_int, 200)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual(CONF.password_length, len(resp_json['adminPass']))

    def test_evacuate_shared(self):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = True
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        uuid1 = self.UUID
        req = webob.Request.blank('/v2/fake/servers/%s/action' % uuid1)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'True',
            }
        })
        req.content_type = 'application/json'

        def fake_update(inst, context, instance,
                        task_state, expected_task_state):
            return None

        self.stubs.Set(compute_api.API, 'update', fake_update)

        res = req.get_response(app)
        self.assertEqual(res.status_int, 200)

    def test_not_admin(self):
        ctxt = context.RequestContext('fake', 'fake', is_admin=False)
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        uuid1 = self.UUID
        req = webob.Request.blank('/v2/fake/servers/%s/action' % uuid1)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'host': 'my_host',
                'onSharedStorage': 'True',
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(res.status_int, 403)

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

from nova import compute
from nova import flags
from nova import test
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


def fake_compute_api(cls, req, id):
    return True


def fake_compute_api_get(self, context, instance_id):
    return {'id': 1, 'uuid': instance_id}


class AdminActionsTest(test.TestCase):

    _actions = ('pause', 'unpause', 'suspend', 'resume', 'migrate',
                'resetNetwork', 'injectNetworkInfo', 'lock', 'unlock')

    _methods = ('pause', 'unpause', 'suspend', 'resume', 'resize',
                'reset_network', 'inject_network_info', 'lock', 'unlock')

    def setUp(self):
        super(AdminActionsTest, self).setUp()
        self.flags(allow_admin_api=True)
        self.stubs.Set(compute.API, 'get', fake_compute_api_get)
        for _method in self._methods:
            self.stubs.Set(compute.API, _method, fake_compute_api)

    def test_admin_api_enabled(self):
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/servers/abcd/action')
            req.method = 'POST'
            req.body = json.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_admin_api_disabled(self):
        FLAGS.allow_admin_api = False
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/servers/abcd/action')
            req.method = 'POST'
            req.body = json.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 404)

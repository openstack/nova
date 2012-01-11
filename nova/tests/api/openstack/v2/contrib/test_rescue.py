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

import json

import webob

from nova import compute
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes

FLAGS = flags.FLAGS


def rescue(self, context, instance, rescue_password=None):
    pass


def unrescue(self, context, instance):
    pass


class RescueTest(test.TestCase):
    def setUp(self):
        super(RescueTest, self).setUp()

        def fake_compute_get(*args, **kwargs):
            uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
            return {'id': 1, 'uuid': uuid}

        self.stubs.Set(compute.api.API, "get", fake_compute_get)
        self.stubs.Set(compute.api.API, "rescue", rescue)
        self.stubs.Set(compute.api.API, "unrescue", unrescue)

    def test_rescue_with_preset_password(self):
        body = {"rescue": {"adminPass": "AABBCC112233"}}
        req = webob.Request.blank('/v2/fake/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        resp_json = json.loads(resp.body)
        self.assertEqual("AABBCC112233", resp_json['adminPass'])

    def test_rescue_generates_password(self):
        body = dict(rescue=None)
        req = webob.Request.blank('/v2/fake/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        resp_json = json.loads(resp.body)
        self.assertEqual(FLAGS.password_length, len(resp_json['adminPass']))

    def test_unrescue(self):
        body = dict(unrescue=None)
        req = webob.Request.blank('/v2/fake/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 202)

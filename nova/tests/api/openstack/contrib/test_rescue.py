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
from nova import test
from nova.tests.api.openstack import fakes


def rescue(self, context, instance_id):
    pass


def unrescue(self, context, instance_id):
    pass


class RescueTest(test.TestCase):
    def setUp(self):
        super(RescueTest, self).setUp()
        self.stubs.Set(compute.api.API, "rescue", rescue)
        self.stubs.Set(compute.api.API, "unrescue", unrescue)

    def test_rescue(self):
        body = dict(rescue=None)
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_unrescue(self):
        body = dict(unrescue=None)
        req = webob.Request.blank('/v1.1/123/servers/test_inst/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

# Copyright 2010 OpenStack LLC.
# All Rights Reserved.
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

import unittest

import stubout
import webob

import nova.api
from nova.api.openstack import zones
from nova.tests.api.openstack import fakes


class ZonesTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.auth_data = {}
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_zone_list(self):
        req = webob.Request.blank('/v1.0/zones')
        res = req.get_response(fakes.wsgi_app())

    def test_get_zone_by_id(self):
        req = webob.Request.blank('/v1.0/zones/1')
        res = req.get_response(fakes.wsgi_app())

    def test_zone_delete(self):
        req = webob.Request.blank('/v1.0/zones/1')
        res = req.get_response(fakes.wsgi_app())

    def test_zone_create(self):
        body = dict(server=dict(api_url='http://blah.zoo', username='bob',
                        password='qwerty'))
        req = webob.Request.blank('/v1.0/zones')
        req.method = 'POST'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)

    def test_zone_update(self):
        body = dict(server=dict(api_url='http://blah.zoo', username='zeb',
                        password='sneaky'))
        req = webob.Request.blank('/v1.0/zones/1')
        req.method = 'PUT'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)


if __name__ == '__main__':
    unittest.main()

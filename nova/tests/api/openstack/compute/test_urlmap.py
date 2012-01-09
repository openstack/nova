# Copyright 2011 OpenStack LLC.
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

import json
import webob

from nova import log as logging
from nova import test
from nova.tests.api.openstack import fakes

LOG = logging.getLogger('nova.tests.api.openstack.compute.test_urlmap')


class UrlmapTest(test.TestCase):
    def setUp(self):
        super(UrlmapTest, self).setUp()
        fakes.stub_out_rate_limiting(self.stubs)

    def test_path_version_v1_1(self):
        """Test URL path specifying v1.1 returns v2 content."""
        req = webob.Request.blank('/v1.1/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_content_type_version_v1_1(self):
        """Test Content-Type specifying v1.1 returns v2 content."""
        req = webob.Request.blank('/')
        req.content_type = "application/json;version=1.1"
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_accept_version_v1_1(self):
        """Test Accept header specifying v1.1 returns v2 content."""
        req = webob.Request.blank('/')
        req.accept = "application/json;version=1.1"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_path_version_v2(self):
        """Test URL path specifying v2 returns v2 content."""
        req = webob.Request.blank('/v2/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_content_type_version_v2(self):
        """Test Content-Type specifying v2 returns v2 content."""
        req = webob.Request.blank('/')
        req.content_type = "application/json;version=2"
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_accept_version_v2(self):
        """Test Accept header specifying v2 returns v2 content."""
        req = webob.Request.blank('/')
        req.accept = "application/json;version=2"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['version']['id'], 'v2.0')

    def test_path_content_type(self):
        """Test URL path specifying JSON returns JSON content."""
        url = '/v2/fake/images/cedef40a-ed67-4d10-800e-17455edce175.json'
        req = webob.Request.blank(url)
        req.accept = "application/xml"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['image']['id'],
                         'cedef40a-ed67-4d10-800e-17455edce175')

    def test_accept_content_type(self):
        """Test Accept header specifying JSON returns JSON content."""
        url = '/v2/fake/images/cedef40a-ed67-4d10-800e-17455edce175'
        req = webob.Request.blank(url)
        req.accept = "application/xml;q=0.8, application/json"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/json")
        body = json.loads(res.body)
        self.assertEqual(body['image']['id'],
                         'cedef40a-ed67-4d10-800e-17455edce175')

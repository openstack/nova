# Copyright 2011 OpenStack Foundation
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

from oslo_serialization import jsonutils

from nova import test
from nova.tests.unit.api.openstack import fakes
import nova.tests.unit.image.fake


class UrlmapTest(test.NoDBTestCase):
    def setUp(self):
        super(UrlmapTest, self).setUp()
        nova.tests.unit.image.fake.stub_out_image_service(self)

    def tearDown(self):
        super(UrlmapTest, self).tearDown()
        nova.tests.unit.image.fake.FakeImageService_reset()

    def test_path_version_v2(self):
        # Test URL path specifying v2 returns v2 content.
        req = fakes.HTTPRequest.blank('/v2/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21(v2_compatible=True))
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.0', body['version']['id'])

    def test_content_type_version_v2(self):
        # Test Content-Type specifying v2 returns v2 content.
        req = fakes.HTTPRequest.blank('/')
        req.content_type = "application/json;version=2"
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21(v2_compatible=True))
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.0', body['version']['id'])

    def test_accept_version_v2(self):
        # Test Accept header specifying v2 returns v2 content.
        req = fakes.HTTPRequest.blank('/')
        req.accept = "application/json;version=2"
        res = req.get_response(fakes.wsgi_app_v21(v2_compatible=True))
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.0', body['version']['id'])

    def test_accept_content_type(self):
        # Test Accept header specifying JSON returns JSON content.
        url = ('/v2/%s/images/cedef40a-ed67-4d10-800e-17455edce175' %
               fakes.FAKE_PROJECT_ID)
        req = fakes.HTTPRequest.blank(url)
        req.accept = "application/xml;q=0.8, application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('cedef40a-ed67-4d10-800e-17455edce175',
                         body['image']['id'])

    def test_path_version_v21(self):
        # Test URL path specifying v2.1 returns v2.1 content.
        req = fakes.HTTPRequest.blank('/v2.1/')
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.1', body['version']['id'])

    def test_content_type_version_v21(self):
        # Test Content-Type specifying v2.1 returns v2 content.
        req = fakes.HTTPRequest.blank('/')
        req.content_type = "application/json;version=2.1"
        req.accept = "application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.1', body['version']['id'])

    def test_accept_version_v21(self):
        # Test Accept header specifying v2.1 returns v2.1 content.
        req = fakes.HTTPRequest.blank('/')
        req.accept = "application/json;version=2.1"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.1', body['version']['id'])

    def test_accept_content_type_v21(self):
        # Test Accept header specifying JSON returns JSON content.
        req = fakes.HTTPRequest.blank('/')
        req.content_type = "application/json;version=2.1"
        req.accept = "application/xml;q=0.8, application/json"
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(200, res.status_int)
        self.assertEqual("application/json", res.content_type)
        body = jsonutils.loads(res.body)
        self.assertEqual('v2.1', body['version']['id'])

    def test_script_name_path_info(self):
        """Ensure URLMap preserves SCRIPT_NAME and PATH_INFO correctly."""
        data = (
            ('', '', ''),
            ('/', '', '/'),
            ('/v2', '/v2', ''),
            ('/v2/', '/v2', '/'),
            ('/v2.1', '/v2.1', ''),
            ('/v2.1/', '/v2.1', '/'),
            ('/v2/foo', '/v2', '/foo'),
            ('/v2.1/foo', '/v2.1', '/foo'),
            ('/bar/baz', '', '/bar/baz')
        )
        app = fakes.wsgi_app_v21()
        for url, exp_script_name, exp_path_info in data:
            req = fakes.HTTPRequest.blank(url)
            req.get_response(app)
            # The app uses /v2 as the base URL :(
            exp_script_name = '/v2' + exp_script_name
            self.assertEqual(exp_script_name, req.environ['SCRIPT_NAME'])
            self.assertEqual(exp_path_info, req.environ['PATH_INFO'])

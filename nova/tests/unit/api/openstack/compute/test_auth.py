# Copyright 2013 IBM Corp.
# Copyright 2010 OpenStack Foundation
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

import testscenarios

from nova.api import openstack as openstack_api
from nova.api.openstack import auth
from nova.api.openstack import compute
from nova.api.openstack import urlmap
from nova import test
from nova.tests.unit.api.openstack import fakes


class TestNoAuthMiddleware(testscenarios.WithScenarios, test.NoDBTestCase):

    scenarios = [
        ('project_id', {
            'expected_url': 'http://localhost/v2.1/user1_project',
            'auth_middleware': auth.NoAuthMiddleware}),
        ('no_project_id', {
            'expected_url': 'http://localhost/v2.1',
            'auth_middleware': auth.NoAuthMiddlewareV2_18}),
    ]

    def setUp(self):
        super(TestNoAuthMiddleware, self).setUp()
        fakes.stub_out_networking(self)
        api_v21 = openstack_api.FaultWrapper(
            self.auth_middleware(
                compute.APIRouterV21()
            )
        )
        self.wsgi_app = urlmap.URLMap()
        self.wsgi_app['/v2.1'] = api_v21
        self.req_url = '/v2.1'

    def test_authorize_user(self):
        req = fakes.HTTPRequest.blank(self.req_url, base_url='')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(self.wsgi_app)
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(result.headers['X-Server-Management-Url'],
            self.expected_url)

    def test_authorize_user_trailing_slash(self):
        # make sure it works with trailing slash on the request
        self.req_url = self.req_url + '/'
        req = fakes.HTTPRequest.blank(self.req_url, base_url='')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(self.wsgi_app)
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(result.headers['X-Server-Management-Url'],
            self.expected_url)

    def test_auth_token_no_empty_headers(self):
        req = fakes.HTTPRequest.blank(self.req_url, base_url='')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(self.wsgi_app)
        self.assertEqual(result.status, '204 No Content')
        self.assertNotIn('X-CDN-Management-Url', result.headers)
        self.assertNotIn('X-Storage-Url', result.headers)

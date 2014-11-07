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

import webob
import webob.dec

from nova import context
from nova import test
from nova.tests.unit.api.openstack import fakes


class TestNoAuthMiddleware(test.NoDBTestCase):

    def setUp(self):
        super(TestNoAuthMiddleware, self).setUp()
        self.stubs.Set(context, 'RequestContext', fakes.FakeRequestContext)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_networking(self.stubs)

    def test_authorize_user(self):
        req = webob.Request.blank('/v2')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(fakes.wsgi_app(use_no_auth=True))
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "http://localhost/v2/user1_project")

    def test_authorize_user_trailing_slash(self):
        # make sure it works with trailing slash on the request
        req = webob.Request.blank('/v2/')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(fakes.wsgi_app(use_no_auth=True))
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "http://localhost/v2/user1_project")

    def test_auth_token_no_empty_headers(self):
        req = webob.Request.blank('/v2')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(fakes.wsgi_app(use_no_auth=True))
        self.assertEqual(result.status, '204 No Content')
        self.assertNotIn('X-CDN-Management-Url', result.headers)
        self.assertNotIn('X-Storage-Url', result.headers)

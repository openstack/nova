# Copyright (c) 2012 OpenStack, LLC
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

import nova.api.auth
from nova import test


class TestNovaKeystoneContextMiddleware(test.TestCase):

    def setUp(self):
        super(TestNovaKeystoneContextMiddleware, self).setUp()

        @webob.dec.wsgify()
        def fake_app(req):
            self.context = req.environ['nova.context']
            return webob.Response()

        self.context = None
        self.middleware = nova.api.auth.NovaKeystoneContext(fake_app)
        self.request = webob.Request.blank('/')
        self.request.headers['X_TENANT_ID'] = 'testtenantid'
        self.request.headers['X_AUTH_TOKEN'] = 'testauthtoken'

    def test_no_user_or_user_id(self):
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '401 Unauthorized')

    def test_user_only(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(self.context.user_id, 'testuserid')

    def test_user_id_only(self):
        self.request.headers['X_USER'] = 'testuser'
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(self.context.user_id, 'testuser')

    def test_user_id_trumps_user(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.headers['X_USER'] = 'testuser'
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(self.context.user_id, 'testuserid')

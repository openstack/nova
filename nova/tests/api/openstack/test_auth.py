# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import datetime

import webob
import webob.dec

import nova.api
import nova.api.openstack.auth
import nova.auth.manager
from nova import context
from nova import db
from nova import test
from nova.tests.api.openstack import fakes


class Test(test.TestCase):

    def setUp(self):
        super(Test, self).setUp()
        self.stubs.Set(nova.api.openstack.auth.AuthMiddleware,
            '__init__', fakes.fake_auth_init)
        self.stubs.Set(context, 'RequestContext', fakes.FakeRequestContext)
        fakes.FakeAuthManager.clear_fakes()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_networking(self.stubs)

    def tearDown(self):
        fakes.fake_data_store = {}
        super(Test, self).tearDown()

    def test_authorize_user(self):
        f = fakes.FakeAuthManager()
        user = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user)

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        req.headers['X-Auth-Project-Id'] = 'user1_project'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "")
        self.assertEqual(result.headers['X-Storage-Url'], "")

    def test_authorize_token(self):
        f = fakes.FakeAuthManager()
        user = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user)
        f.create_project('user1_project', user)

        req = webob.Request.blank('/v1.0/', {'HTTP_HOST': 'foo'})
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "http://foo/v1.0")
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "")
        self.assertEqual(result.headers['X-Storage-Url'], "")

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.openstack, 'APIRouterV10', fakes.FakeRouter)
        req = webob.Request.blank('/v1.0/user1_project')
        req.headers['X-Auth-Token'] = token
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '200 OK')
        self.assertEqual(result.headers['X-Test-Success'], 'True')

    def test_token_expiry(self):
        self.destroy_called = False
        token_hash = 'token_hash'

        def destroy_token_mock(meh, context, token):
            self.destroy_called = True

        def bad_token(meh, context, token_hash):
            return fakes.FakeToken(
                    token_hash=token_hash,
                    created_at=datetime.datetime(1990, 1, 1))

        self.stubs.Set(fakes.FakeAuthDatabase, 'auth_token_destroy',
            destroy_token_mock)

        self.stubs.Set(fakes.FakeAuthDatabase, 'auth_token_get',
            bad_token)

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'token_hash'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')
        self.assertEqual(self.destroy_called, True)

    def test_authorize_project(self):
        f = fakes.FakeAuthManager()
        user = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user)
        f.create_project('user1_project', user)
        f.create_project('user2_project', user)

        req = webob.Request.blank('/v1.0/', {'HTTP_HOST': 'foo'})
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '204 No Content')

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.openstack, 'APIRouterV10', fakes.FakeRouter)
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = token
        req.headers['X-Auth-Project-Id'] = 'user2_project'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '200 OK')
        self.assertEqual(result.headers['X-Test-Success'], 'True')

    def test_bad_user_bad_key(self):
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'unknown_user'
        req.headers['X-Auth-Key'] = 'unknown_user_key'
        req.headers['X-Auth-Project-Id'] = 'user_project'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_bad_user_good_key(self):
        f = fakes.FakeAuthManager()
        user = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user)

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'unknown_user'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_no_user(self):
        req = webob.Request.blank('/v1.0/')
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_bad_token(self):
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'unknown_token'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_bad_project(self):
        f = fakes.FakeAuthManager()
        user1 = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        user2 = nova.auth.manager.User('id2', 'user2', 'user2_key', None, None)
        f.add_user(user1)
        f.add_user(user2)
        f.create_project('user1_project', user1)
        f.create_project('user2_project', user2)

        req = webob.Request.blank('/v1.0/', {'HTTP_HOST': 'foo'})
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '204 No Content')

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.openstack, 'APIRouterV10', fakes.FakeRouter)
        req = webob.Request.blank('/v1.0/fake')
        req.headers['X-Auth-Token'] = token
        req.headers['X-Auth-Project-Id'] = 'user2_project'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_not_existing_project(self):
        f = fakes.FakeAuthManager()
        user1 = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user1)
        f.create_project('user1_project', user1)

        req = webob.Request.blank('/v1.0/', {'HTTP_HOST': 'foo'})
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '204 No Content')

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.openstack, 'APIRouterV10', fakes.FakeRouter)
        req = webob.Request.blank('/v1.0/fake')
        req.headers['X-Auth-Token'] = token
        req.headers['X-Auth-Project-Id'] = 'unknown_project'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')


class TestFunctional(test.TestCase):
    def test_token_expiry(self):
        ctx = context.get_admin_context()
        tok = db.auth_token_create(ctx, dict(
                token_hash='test_token_hash',
                cdn_management_url='',
                server_management_url='',
                storage_url='',
                user_id='user1',
                ))

        db.auth_token_update(ctx, tok.token_hash, dict(
                created_at=datetime.datetime(2000, 1, 1, 12, 0, 0),
                ))

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'test_token_hash'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')

    def test_token_doesnotexist(self):
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'nonexistant_token_hash'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '401 Unauthorized')


class TestLimiter(test.TestCase):
    def setUp(self):
        super(TestLimiter, self).setUp()
        self.stubs.Set(nova.api.openstack.auth.AuthMiddleware,
            '__init__', fakes.fake_auth_init)
        self.stubs.Set(context, 'RequestContext', fakes.FakeRequestContext)
        fakes.FakeAuthManager.clear_fakes()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)

    def tearDown(self):
        fakes.fake_data_store = {}
        super(TestLimiter, self).tearDown()

    def test_authorize_token(self):
        f = fakes.FakeAuthManager()
        user = nova.auth.manager.User('id1', 'user1', 'user1_key', None, None)
        f.add_user(user)
        f.create_project('test', user)

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'user1'
        req.headers['X-Auth-Key'] = 'user1_key'
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.openstack, 'APIRouterV10', fakes.FakeRouter)
        req = webob.Request.blank('/v1.0/fake')
        req.method = 'POST'
        req.headers['X-Auth-Token'] = token
        result = req.get_response(fakes.wsgi_app(fake_auth=False))
        self.assertEqual(result.status, '200 OK')
        self.assertEqual(result.headers['X-Test-Success'], 'True')

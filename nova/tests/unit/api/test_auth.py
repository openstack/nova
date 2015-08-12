# Copyright (c) 2012 OpenStack Foundation
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

from oslo_config import cfg
from oslo_middleware import request_id
from oslo_serialization import jsonutils
import webob
import webob.exc

import nova.api.auth
from nova import test

CONF = cfg.CONF


class TestNovaKeystoneContextMiddleware(test.NoDBTestCase):

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
        self.request.headers['X_SERVICE_CATALOG'] = jsonutils.dumps({})

    def test_no_user_or_user_id(self):
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '401 Unauthorized')

    def test_user_id_only(self):
        self.request.headers['X_USER_ID'] = 'testuserid'
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(self.context.user_id, 'testuserid')

    def test_user_only(self):
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

    def test_invalid_service_catalog(self):
        self.request.headers['X_USER'] = 'testuser'
        self.request.headers['X_SERVICE_CATALOG'] = "bad json"
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '500 Internal Server Error')

    def test_request_id_extracted_from_env(self):
        req_id = 'dummy-request-id'
        self.request.headers['X_PROJECT_ID'] = 'testtenantid'
        self.request.headers['X_USER_ID'] = 'testuserid'
        self.request.environ[request_id.ENV_REQUEST_ID] = req_id
        self.request.get_response(self.middleware)
        self.assertEqual(req_id, self.context.request_id)


class TestKeystoneMiddlewareRoles(test.NoDBTestCase):

    def setUp(self):
        super(TestKeystoneMiddlewareRoles, self).setUp()

        @webob.dec.wsgify()
        def role_check_app(req):
            context = req.environ['nova.context']

            if "knight" in context.roles and "bad" not in context.roles:
                return webob.Response(status="200 Role Match")
            elif context.roles == ['']:
                return webob.Response(status="200 No Roles")
            else:
                raise webob.exc.HTTPBadRequest("unexpected role header")

        self.middleware = nova.api.auth.NovaKeystoneContext(role_check_app)
        self.request = webob.Request.blank('/')
        self.request.headers['X_USER'] = 'testuser'
        self.request.headers['X_TENANT_ID'] = 'testtenantid'
        self.request.headers['X_AUTH_TOKEN'] = 'testauthtoken'
        self.request.headers['X_SERVICE_CATALOG'] = jsonutils.dumps({})

        self.roles = "pawn, knight, rook"

    def test_roles(self):
        self.request.headers['X_ROLES'] = 'pawn,knight,rook'

        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 Role Match')

    def test_roles_empty(self):
        self.request.headers['X_ROLES'] = ''
        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 No Roles')

    def test_no_role_headers(self):
        # Test with no role headers set.

        response = self.request.get_response(self.middleware)
        self.assertEqual(response.status, '200 No Roles')


class TestPipeLineFactory(test.NoDBTestCase):

    class FakeFilter(object):
        def __init__(self, name):
            self.name = name
            self.obj = None

        def __call__(self, obj):
            self.obj = obj
            return self

    class FakeApp(object):
        def __init__(self, name):
            self.name = name

    class FakeLoader(object):
        def get_filter(self, name):
            return TestPipeLineFactory.FakeFilter(name)

        def get_app(self, name):
            return TestPipeLineFactory.FakeApp(name)

    def _test_pipeline(self, pipeline, app):
        for p in pipeline.split()[:-1]:
            self.assertEqual(app.name, p)
            self.assertIsInstance(app, TestPipeLineFactory.FakeFilter)
            app = app.obj
        self.assertEqual(app.name, pipeline.split()[-1])
        self.assertIsInstance(app, TestPipeLineFactory.FakeApp)

    def test_pipeline_factory(self):
        fake_pipeline = 'test1 test2 test3'
        CONF.set_override('auth_strategy', 'noauth2')
        app = nova.api.auth.pipeline_factory(
            TestPipeLineFactory.FakeLoader(), None, noauth2=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)

    def test_pipeline_factory_v21(self):
        fake_pipeline = 'test1 test2 test3'
        CONF.set_override('auth_strategy', 'noauth2')
        app = nova.api.auth.pipeline_factory_v21(
            TestPipeLineFactory.FakeLoader(), None, noauth2=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)

    def test_pipeline_factory_with_rate_limits(self):
        CONF.set_override('api_rate_limit', True)
        CONF.set_override('auth_strategy', 'keystone')
        fake_pipeline = 'test1 test2 test3'
        app = nova.api.auth.pipeline_factory(
            TestPipeLineFactory.FakeLoader(), None, keystone=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)

    def test_pipeline_factory_without_rate_limits(self):
        CONF.set_override('auth_strategy', 'keystone')
        fake_pipeline1 = 'test1 test2 test3'
        fake_pipeline2 = 'test4 test5 test6'
        app = nova.api.auth.pipeline_factory(
            TestPipeLineFactory.FakeLoader(), None,
            keystone_nolimit=fake_pipeline1,
            keystone=fake_pipeline2)
        self._test_pipeline(fake_pipeline1, app)

    def test_pipeline_factory_missing_nolimits_pipeline(self):
        CONF.set_override('api_rate_limit', False)
        CONF.set_override('auth_strategy', 'keystone')
        fake_pipeline = 'test1 test2 test3'
        app = nova.api.auth.pipeline_factory(
            TestPipeLineFactory.FakeLoader(), None, keystone=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)

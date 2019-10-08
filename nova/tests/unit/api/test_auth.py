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

import mock
from oslo_middleware import request_id
from oslo_serialization import jsonutils
import webob
import webob.exc

import nova.api.auth
import nova.conf
from nova import test

CONF = nova.conf.CONF


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

    def test_invalid_service_catalog(self):
        self.request.headers['X_USER_ID'] = 'testuser'
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
            elif not context.roles:
                return webob.Response(status="200 No Roles")
            else:
                raise webob.exc.HTTPBadRequest("unexpected role header")

        self.middleware = nova.api.auth.NovaKeystoneContext(role_check_app)
        self.request = webob.Request.blank('/')
        self.request.headers['X_USER_ID'] = 'testuser'
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

    @mock.patch('oslo_log.versionutils.report_deprecated_feature',
                new=mock.NonCallableMock())
    def test_pipeline_factory_v21(self):
        fake_pipeline = 'test1 test2 test3'
        CONF.set_override('auth_strategy', 'keystone', group='api')
        app = nova.api.auth.pipeline_factory_v21(
            TestPipeLineFactory.FakeLoader(), None, keystone=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)

    @mock.patch('oslo_log.versionutils.report_deprecated_feature')
    def test_pipeline_factory_v21_noauth2(self, mock_report_deprecated):
        fake_pipeline = 'test1 test2 test3'
        CONF.set_override('auth_strategy', 'noauth2', group='api')
        app = nova.api.auth.pipeline_factory_v21(
            TestPipeLineFactory.FakeLoader(), None, noauth2=fake_pipeline)
        self._test_pipeline(fake_pipeline, app)
        self.assertTrue(mock_report_deprecated.called)

    @mock.patch('oslo_log.versionutils.report_deprecated_feature')
    def test_pipeline_factory_legacy_v2_deprecated(self,
                                                   mock_report_deprecated):
        fake_pipeline = 'test1 test2 test3'
        nova.api.auth.pipeline_factory(TestPipeLineFactory.FakeLoader(),
            None, noauth2=fake_pipeline)
        self.assertTrue(mock_report_deprecated.called)

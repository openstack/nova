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

import json

from lxml import etree
import webob
import webob.exc
import webob.dec

import nova.context
from nova import exception
from nova import test
from nova.api import openstack as openstack_api
from nova.api.openstack import wsgi
from nova.rpc import common as rpc_common
from nova.tests.api.openstack import fakes


class APITest(test.TestCase):

    def _wsgi_app(self, inner_app):
        # simpler version of the app than fakes.wsgi_app
        return openstack_api.FaultWrapper(inner_app)

    def test_malformed_json(self):
        req = webob.Request.blank('/')
        req.method = 'POST'
        req.body = '{'
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_malformed_xml(self):
        req = webob.Request.blank('/')
        req.method = 'POST'
        req.body = '<hi im not xml>'
        req.headers["content-type"] = "application/xml"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_vendor_content_type_json(self):
        ctype = 'application/vnd.openstack.compute+json'

        req = webob.Request.blank('/')
        req.headers['Accept'] = ctype

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, ctype)

        body = json.loads(res.body)

    def test_vendor_content_type_xml(self):
        ctype = 'application/vnd.openstack.compute+xml'

        req = webob.Request.blank('/')
        req.headers['Accept'] = ctype

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, ctype)

        body = etree.XML(res.body)

    def test_exceptions_are_converted_to_faults_webob_exc(self):
        @webob.dec.wsgify
        def raise_webob_exc(req):
            raise webob.exc.HTTPNotFound(explanation='Raised a webob.exc')

        #api.application = raise_webob_exc
        api = self._wsgi_app(raise_webob_exc)
        resp = webob.Request.blank('/').get_response(api)
        self.assertEqual(resp.status_int, 404, resp.body)

    def test_exceptions_are_converted_to_faults_api_fault(self):
        @webob.dec.wsgify
        def raise_api_fault(req):
            exc = webob.exc.HTTPNotFound(explanation='Raised a webob.exc')
            return wsgi.Fault(exc)

        #api.application = raise_api_fault
        api = self._wsgi_app(raise_api_fault)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue('itemNotFound' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 404, resp.body)

    def test_exceptions_are_converted_to_faults_exception(self):
        @webob.dec.wsgify
        def fail(req):
            raise Exception("Threw an exception")

        #api.application = fail
        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue('{"computeFault' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def test_exceptions_are_converted_to_faults_exception_xml(self):
        @webob.dec.wsgify
        def fail(req):
            raise Exception("Threw an exception")

        #api.application = fail
        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/.xml').get_response(api)
        self.assertTrue('<computeFault' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def _do_test_exception_safety_reflected_in_faults(self, expose):
        class ExceptionWithSafety(exception.NovaException):
            safe = expose

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithSafety('some explanation')

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue('{"computeFault' in resp.body, resp.body)
        expected = ('ExceptionWithSafety: some explanation' if expose else
                    'The server has either erred or is incapable '
                    'of performing the requested operation.')
        self.assertTrue(expected in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def test_safe_exceptions_are_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(True)

    def test_unsafe_exceptions_are_not_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(False)

    def _do_test_exception_mapping(self, exception_value, exception_type):
        @webob.dec.wsgify
        def fail(req):
            raise exception_value

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertTrue('too many used' in resp.body, resp.body)
        self.assertEqual(resp.status_int, exception_type.code, resp.body)
        for (key, value) in exception_type.headers.iteritems():
            self.assertTrue(key in resp.headers)
            self.assertEquals(resp.headers[key], value)

    def test_local_quota_error_mapping(self):
        exception_value = exception.QuotaError('too many used')
        self._do_test_exception_mapping(exception_value, exception.QuotaError)

    def test_remote_quota_error_mapping(self):
        exception_value = rpc_common.RemoteError('QuotaError',
                                                 'too many used')
        self._do_test_exception_mapping(exception_value, exception.QuotaError)

    def test_remote_unknown_error_mapping(self):
        @webob.dec.wsgify
        def fail(req):
            raise rpc_common.RemoteError('UnknownError', 'whatevs')

        api = self._wsgi_app(fail)
        resp = webob.Request.blank('/').get_response(api)
        self.assertFalse('whatevs' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def test_request_id_in_response(self):
        req = webob.Request.blank('/')
        req.method = 'GET'
        context = nova.context.RequestContext('bob', 1)
        context.request_id = 'test-req-id'
        req.environ['nova.context'] = context

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.headers['x-compute-request-id'], 'test-req-id')

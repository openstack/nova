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

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob.dec
import webob.exc

from nova.api import openstack as openstack_api
from nova.api.openstack import wsgi
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


class APITest(test.NoDBTestCase):

    @property
    def wsgi_app(self):
        return fakes.wsgi_app_v21()

    def _wsgi_app(self, inner_app):
        return openstack_api.FaultWrapper(inner_app)

    def test_malformed_json(self):
        req = fakes.HTTPRequest.blank('/')
        req.method = 'POST'
        req.body = b'{'
        req.headers["content-type"] = "application/json"

        res = req.get_response(self.wsgi_app)
        self.assertEqual(res.status_int, 400)

    def test_malformed_xml(self):
        req = fakes.HTTPRequest.blank('/')
        req.method = 'POST'
        req.body = b'<hi im not xml>'
        req.headers["content-type"] = "application/xml"

        res = req.get_response(self.wsgi_app)
        self.assertEqual(res.status_int, 415)

    def test_vendor_content_type_json(self):
        ctype = 'application/vnd.openstack.compute+json'

        req = fakes.HTTPRequest.blank('/')
        req.headers['Accept'] = ctype

        res = req.get_response(self.wsgi_app)
        self.assertEqual(res.status_int, 200)
        # NOTE(scottynomad): Webob's Response assumes that header values are
        # strings so the `res.content_type` property is broken in python3.
        #
        # Consider changing `api.openstack.wsgi.Resource._process_stack`
        # to encode header values in ASCII rather than UTF-8.
        # https://tools.ietf.org/html/rfc7230#section-3.2.4
        content_type = res.headers.get('Content-Type')
        self.assertEqual(ctype, encodeutils.safe_decode(content_type))

        jsonutils.loads(res.body)

    def test_exceptions_are_converted_to_faults_webob_exc(self):
        @webob.dec.wsgify
        def raise_webob_exc(req):
            raise webob.exc.HTTPNotFound(explanation='Raised a webob.exc')

        # api.application = raise_webob_exc
        api = self._wsgi_app(raise_webob_exc)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertEqual(resp.status_int, 404, resp.text)

    def test_exceptions_are_converted_to_faults_api_fault(self):
        @webob.dec.wsgify
        def raise_api_fault(req):
            exc = webob.exc.HTTPNotFound(explanation='Raised a webob.exc')
            return wsgi.Fault(exc)

        # api.application = raise_api_fault
        api = self._wsgi_app(raise_api_fault)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertIn('itemNotFound', resp.text)
        self.assertEqual(resp.status_int, 404, resp.text)

    def test_exceptions_are_converted_to_faults_exception(self):
        @webob.dec.wsgify
        def fail(req):
            raise Exception("Threw an exception")

        # api.application = fail
        api = self._wsgi_app(fail)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertIn('{"computeFault', resp.text)
        self.assertEqual(resp.status_int, 500, resp.text)

    def _do_test_exception_safety_reflected_in_faults(self, expose):
        class ExceptionWithSafety(exception.NovaException):
            safe = expose

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithSafety('some explanation')

        api = self._wsgi_app(fail)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertIn('{"computeFault', resp.text)
        expected = ('ExceptionWithSafety: some explanation' if expose else
                    'The server has either erred or is incapable '
                    'of performing the requested operation.')
        self.assertIn(expected, resp.text)
        self.assertEqual(resp.status_int, 500, resp.text)

    def test_safe_exceptions_are_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(True)

    def test_unsafe_exceptions_are_not_described_in_faults(self):
        self._do_test_exception_safety_reflected_in_faults(False)

    def _do_test_exception_mapping(self, exception_type, msg):
        @webob.dec.wsgify
        def fail(req):
            raise exception_type(msg)

        api = self._wsgi_app(fail)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertIn(msg, resp.text)
        self.assertEqual(resp.status_int, exception_type.code, resp.text)

        if hasattr(exception_type, 'headers'):
            for (key, value) in exception_type.headers.items():
                self.assertIn(key, resp.headers)
                self.assertEqual(resp.headers[key], str(value))

    def test_quota_error_mapping(self):
        self._do_test_exception_mapping(exception.QuotaError, 'too many used')

    def test_non_nova_notfound_exception_mapping(self):
        class ExceptionWithCode(Exception):
            code = 404

        self._do_test_exception_mapping(ExceptionWithCode,
                                        'NotFound')

    def test_non_nova_exception_mapping(self):
        class ExceptionWithCode(Exception):
            code = 417

        self._do_test_exception_mapping(ExceptionWithCode,
                                        'Expectation failed')

    def test_exception_with_none_code_throws_500(self):
        class ExceptionWithNoneCode(Exception):
            code = None

        @webob.dec.wsgify
        def fail(req):
            raise ExceptionWithNoneCode()

        api = self._wsgi_app(fail)
        resp = fakes.HTTPRequest.blank('/').get_response(api)
        self.assertEqual(500, resp.status_int)

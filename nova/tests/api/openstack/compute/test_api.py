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
import webob.exc
import webob.dec
from webob import Request

from nova import test
from nova.api import openstack as openstack_api
from nova.api.openstack.compute import wsgi
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
        resp = Request.blank('/').get_response(api)
        self.assertEqual(resp.status_int, 404, resp.body)

    def test_exceptions_are_converted_to_faults_api_fault(self):
        @webob.dec.wsgify
        def raise_api_fault(req):
            exc = webob.exc.HTTPNotFound(explanation='Raised a webob.exc')
            return wsgi.Fault(exc)

        #api.application = raise_api_fault
        api = self._wsgi_app(raise_api_fault)
        resp = Request.blank('/').get_response(api)
        self.assertTrue('itemNotFound' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 404, resp.body)

    def test_exceptions_are_converted_to_faults_exception(self):
        @webob.dec.wsgify
        def fail(req):
            raise Exception("Threw an exception")

        #api.application = fail
        api = self._wsgi_app(fail)
        resp = Request.blank('/').get_response(api)
        self.assertTrue('{"computeFault' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

    def test_exceptions_are_converted_to_faults_exception_xml(self):
        @webob.dec.wsgify
        def fail(req):
            raise Exception("Threw an exception")

        #api.application = fail
        api = self._wsgi_app(fail)
        resp = Request.blank('/.xml').get_response(api)
        self.assertTrue('<computeFault' in resp.body, resp.body)
        self.assertEqual(resp.status_int, 500, resp.body)

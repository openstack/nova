# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
import stubout
import unittest
import webob
import os.path

from nova import context
from nova import flags
from nova.api import openstack
from nova.api.openstack import extensions
from nova.api.openstack import flavors
from nova.tests.api.openstack import fakes
import nova.wsgi

FLAGS = flags.FLAGS


class StubController(nova.wsgi.Controller):

    def __init__(self, body):
        self.body = body

    def index(self, req):
        return self.body


class StubExtensionManager(object):

    def __init__(self, resource_ext=None, action_ext=None, response_ext=None):
        self.resource_ext = resource_ext
        self.action_ext = action_ext
        self.response_ext = response_ext

    def get_name(self):
        return "Tweedle Beetle Extension"

    def get_alias(self):
        return "TWDLBETL"

    def get_description(self):
        return "Provides access to Tweedle Beetles"

    def get_resources(self):
        resource_exts = []
        if self.resource_ext:
            resource_exts.append(self.resource_ext)
        return resource_exts

    def get_actions(self):
        action_exts = []
        if self.action_ext:
            action_exts.append(self.action_ext)
        return action_exts

    def get_response_extensions(self):
        response_exts = []
        if self.response_ext:
            response_exts.append(self.response_ext)
        return response_exts


class ExtensionControllerTest(unittest.TestCase):

    def test_index(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/extensions")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)

    def test_get_by_alias(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/extensions/FOXNSOX")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)

response_body = "Try to say this Mr. Knox, sir..."

class ResourceExtensionTest(unittest.TestCase):


    def test_no_extension_present(self):
        manager = StubExtensionManager(None)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/blah")
        response = request.get_response(ext_midware)
        self.assertEqual(404, response.status_int)

    def test_get_resources(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/tweedles")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_get_resources_with_controller(self):
        res_ext = extensions.ResourceExtension('tweedles',
                                               StubController(response_body))
        manager = StubExtensionManager(res_ext)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/tweedles")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)


class ExtensionManagerTest(unittest.TestCase):

    response_body = "Try to say this Mr. Knox, sir..."

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def test_get_resources(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/foxnsocks")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)


class ActionExtensionTest(unittest.TestCase):

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def _send_server_action_request(self, url, body):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank(url)
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(ext_midware)
        return response

    def test_extended_action(self):
        body = dict(add_tweedle=dict(name="test"))
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Added.", response.body)

        body = dict(delete_tweedle=dict(name="test"))
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Tweedle Beetle Deleted.", response.body)

    def test_invalid_action_body(self):
        body = dict(blah=dict(name="test"))  # Doesn't exist
        response = self._send_server_action_request("/servers/1/action", body)
        self.assertEqual(501, response.status_int)

    def test_invalid_action(self):
        body = dict(blah=dict(name="test"))
        response = self._send_server_action_request("/asdf/1/action", body)
        self.assertEqual(404, response.status_int)


class ResponseExtensionTest(unittest.TestCase):

    def setUp(self):
        super(ResponseExtensionTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.context = context.get_admin_context()

    def test_get_resources(self):

        test_resp = "Gooey goo for chewy chewing!"

        def _resp_handler(res):
            # only handle JSON responses
            data = json.loads(res.body)
            data['flavor']['googoose'] = test_resp
            return data

        resp_ext = extensions.ResponseExtension('/v1.0/flavors/:(id)', 'GET',
                                                _resp_handler)
        manager = StubExtensionManager(None, None, resp_ext)
        app = fakes.wsgi_app()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/v1.0/flavors/1")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        response_data = json.loads(response.body)
        self.assertEqual(test_resp, response_data['flavor']['googoose'])

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
import unittest
import webob
import os.path

from nova import flags
from nova.api import openstack
from nova.api.openstack import extensions
import nova.wsgi

FLAGS = flags.FLAGS


class StubController(nova.wsgi.Controller):

    def __init__(self, body):
        self.body = body

    def index(self, req):
        return self.body


class StubExtensionManager(object):

    def __init__(self, resource):
        self.resource = resource

    def get_resources(self):
        resources = []
        if self.resource:
            resources.append(self.resource)
        return resources

    def get_actions(self):
        actions = []
        return actions


class ExtensionResourceTest(unittest.TestCase):

    def test_no_extension_present(self):
        manager = StubExtensionManager(None)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/widgets")
        response = request.get_response(ext_midware)
        self.assertEqual(404, response.status_int)

    def test_get_resources(self):
        response_body = "Buy more widgets!"
        widgets = extensions.ExtensionResource('widget', 'widgets',
                                               StubController(response_body))
        manager = StubExtensionManager(widgets)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/widgets")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)

    def test_get_resources_with_controller(self):
        response_body = "Buy more widgets!"
        widgets = extensions.ExtensionResource('widget', 'widgets',
                                               StubController(response_body))
        manager = StubExtensionManager(widgets)
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app, manager)
        request = webob.Request.blank("/widgets")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual(response_body, response.body)


class ExtensionManagerTest(unittest.TestCase):

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def test_get_resources(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/widgets")
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Buy more widgets!", response.body)


class ExtendedActionTest(unittest.TestCase):

    def setUp(self):
        FLAGS.osapi_extensions_path = os.path.join(os.path.dirname(__file__),
                                                    "extensions")

    def test_extended_action(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        body = dict(add_widget=dict(name="test"))
        request = webob.Request.blank("/servers/1/action")
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(ext_midware)
        self.assertEqual(200, response.status_int)
        self.assertEqual("Widget Added.", response.body)

    def test_invalid_action_body(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        body = dict(blah=dict(name="test"))  # Doesn't exist
        request = webob.Request.blank("/servers/1/action")
        request.method = 'POST'
        request.content_type = 'application/json'
        request.body = json.dumps(body)
        response = request.get_response(ext_midware)
        self.assertEqual(501, response.status_int)

    def test_invalid_action(self):
        app = openstack.APIRouter()
        ext_midware = extensions.ExtensionMiddleware(app)
        request = webob.Request.blank("/asdf/1/action")
        request.method = 'POST'
        request.content_type = 'application/json'
        response = request.get_response(ext_midware)
        self.assertEqual(404, response.status_int)

# Copyright 2012 OpenStack LLC.
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

import webob

from nova import compute
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes


def fake_get_vnc_console(self, _context, _instance, _console_type):
    return {'url': 'http://fake'}


def fake_get_vnc_console_invalid_type(self, _context,
                                      _instance, _console_type):
    raise exception.ConsoleTypeInvalid()


def fake_get(self, context, instance_uuid):
    return {'uuid': instance_uuid}


def fake_get_not_found(*args, **kwargs):
    raise exception.NotFound()


class ConsolesExtensionTest(test.TestCase):

    def setUp(self):
        super(ConsolesExtensionTest, self).setUp()
        self.stubs.Set(compute.API, 'get_vnc_console',
                       fake_get_vnc_console)
        self.stubs.Set(compute.API, 'get', fake_get)

    def test_get_vnc_console(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        output = json.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'novnc'}})

    def test_get_vnc_console_no_type(self):
        self.stubs.Set(compute.API, 'get', fake_get)
        body = {'os-getVNCConsole': {}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_get_vnc_console_no_instance(self):
        self.stubs.Set(compute.API, 'get', fake_get_not_found)
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_vnc_console_no_instance_on_console_get(self):
        self.stubs.Set(compute.API, 'get_vnc_console', fake_get_not_found)
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_vnc_console_invalid_type(self):
        self.stubs.Set(compute.API, 'get', fake_get)
        body = {'os-getVNCConsole': {'type': 'invalid'}}
        self.stubs.Set(compute.API, 'get_vnc_console',
                       fake_get_vnc_console_invalid_type)
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

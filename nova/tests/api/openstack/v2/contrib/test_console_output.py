# Copyright 2011 Eldar Nugaev
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


def fake_get_console_output(self, _context, _instance, tail_length):
    fixture = [str(i) for i in range(5)]

    if tail_length is None:
        pass
    elif tail_length == 0:
        fixture = []
    else:
        fixture = fixture[-int(tail_length):]

    return '\n'.join(fixture)


def fake_get(self, context, instance_uuid):
    return {'uuid': instance_uuid}


def fake_get_not_found(self, context, instance_uuid):
    raise exception.NotFound()


class ConsoleOutputExtensionTest(test.TestCase):

    def setUp(self):
        super(ConsoleOutputExtensionTest, self).setUp()
        self.stubs.Set(compute.API, 'get_console_output',
                       fake_get_console_output)
        self.stubs.Set(compute.API, 'get', fake_get)

    def test_get_text_console_instance_action(self):
        body = {'os-getConsoleOutput': {}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        output = json.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output, {'output': '0\n1\n2\n3\n4'})

    def test_get_console_output_with_tail(self):
        body = {'os-getConsoleOutput': {'length': 3}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(fakes.wsgi_app())
        output = json.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output, {'output': '2\n3\n4'})

    def test_get_text_console_no_instance(self):
        self.stubs.Set(compute.API, 'get', fake_get_not_found)
        body = {'os-getConsoleOutput': {}}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_get_text_console_bad_body(self):
        body = {}
        req = webob.Request.blank('/v2/fake/servers/1/action')
        req.method = "POST"
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

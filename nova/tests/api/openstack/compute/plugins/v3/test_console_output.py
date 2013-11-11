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

import string
import webob

from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common import jsonutils
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


def fake_get_console_output_not_ready(self, _context, _instance, tail_length):
    raise exception.InstanceNotReady(instance_id=_instance["uuid"])


def fake_get_console_output_all_characters(self, _ctx, _instance, _tail_len):
    return string.printable


def fake_get(self, context, instance_uuid):
    return {'uuid': instance_uuid}


def fake_get_not_found(*args, **kwargs):
    raise exception.InstanceNotFound(instance_id='')


class ConsoleOutputExtensionTest(test.NoDBTestCase):
    application_type = "application/json"

    def setUp(self):
        super(ConsoleOutputExtensionTest, self).setUp()
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.app = fakes.wsgi_app_v3(init_only=('servers', 'console-output'))

    def _create_request(self, length_dict={}):
        body = {'get_console_output': length_dict}
        req = fakes.HTTPRequestV3.blank('/v3/servers/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = self.application_type
        return req

    def test_get_text_console_instance_action(self):
        req = self._create_request(length_dict={})
        res = req.get_response(self.app)
        output = jsonutils.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output, {'output': '0\n1\n2\n3\n4'})

    def test_get_console_output_with_tail(self):
        req = self._create_request(length_dict={'length': 3})
        res = req.get_response(self.app)
        output = jsonutils.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output, {'output': '2\n3\n4'})

    def test_get_console_output_with_length_as_str(self):
        req = self._create_request(length_dict={'length': '3'})
        res = req.get_response(self.app)
        output = jsonutils.loads(res.body)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(output, {'output': '2\n3\n4'})

    def test_get_console_output_filtered_characters(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output_all_characters)
        body = {'get_console_output': {}}
        req = webob.Request.blank('/v3/servers/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(self.app)
        output = jsonutils.loads(res.body)
        self.assertEqual(res.status_int, 200)
        expect = string.digits + string.letters + string.punctuation + ' \t\n'
        self.assertEqual(output, {'output': expect})

    def test_get_console_output_with_non_integer_length(self):
        req = self._create_request(length_dict={'length': 'NaN'})
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)

    def test_get_text_console_no_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_get_not_found)
        req = self._create_request(length_dict={})
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 404)

    def test_get_text_console_bad_body(self):
        body = {}
        req = fakes.HTTPRequestV3.blank('/v3/servers/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = self.application_type

        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)

    def test_get_console_output_not_ready(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output_not_ready)
        req = self._create_request(length_dict={'length': 3})
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 409)

    def test_get_console_output_with_lenght_as_float(self):
        req = self._create_request(length_dict={'length': 2.5})
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)

    def test_get_console_output_not_implemented(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fakes.fake_not_implemented)
        req = self._create_request()
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 501)

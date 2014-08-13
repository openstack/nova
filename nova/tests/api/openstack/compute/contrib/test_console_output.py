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

from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


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


def fake_get(self, context, instance_uuid, want_objects=False,
             expected_attrs=None):
    return fake_instance.fake_instance_obj(context, **{'uuid': instance_uuid})


def fake_get_not_found(*args, **kwargs):
    raise exception.InstanceNotFound(instance_id='fake')


class ConsoleOutputExtensionTestV21(test.NoDBTestCase):
    application_type = "application/json"
    action_url = '/v3/servers/1/action'

    def setUp(self):
        super(ConsoleOutputExtensionTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.app = self._get_app()

    def _get_app(self):
        return fakes.wsgi_app_v3(init_only=('servers',
                                            'os-console-output'))

    def _get_response(self, length_dict=None):
        length_dict = length_dict or {}
        body = {'os-getConsoleOutput': length_dict}
        req = fakes.HTTPRequest.blank(self.action_url)
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = self.application_type
        res = req.get_response(self.app)
        return res

    def test_get_text_console_instance_action(self):
        res = self._get_response()
        output = jsonutils.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual({'output': '0\n1\n2\n3\n4'}, output)

    def test_get_console_output_with_tail(self):
        res = self._get_response(length_dict={'length': 3})
        output = jsonutils.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual({'output': '2\n3\n4'}, output)

    def test_get_console_output_with_none_length(self):
        res = self._get_response(length_dict={'length': None})
        output = jsonutils.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual({'output': '0\n1\n2\n3\n4'}, output)

    def test_get_console_output_with_length_as_str(self):
        res = self._get_response(length_dict={'length': '3'})
        output = jsonutils.loads(res.body)
        self.assertEqual(200, res.status_int)
        self.assertEqual({'output': '2\n3\n4'}, output)

    def test_get_console_output_filtered_characters(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output_all_characters)
        res = self._get_response()
        output = jsonutils.loads(res.body)
        self.assertEqual(200, res.status_int)
        expect = string.digits + string.letters + string.punctuation + ' \t\n'
        self.assertEqual({'output': expect}, output)

    def test_get_text_console_no_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_get_not_found)
        res = self._get_response()
        self.assertEqual(404, res.status_int)

    def test_get_text_console_no_instance_on_get_output(self):
        self.stubs.Set(compute_api.API,
                       'get_console_output',
                       fake_get_not_found)
        res = self._get_response()
        self.assertEqual(404, res.status_int)

    def _get_console_output_bad_request_case(self, body):
        req = fakes.HTTPRequest.blank(self.action_url)
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)

    def test_get_console_output_with_non_integer_length(self):
        body = {'os-getConsoleOutput': {'length': 'NaN'}}
        self._get_console_output_bad_request_case(body)

    def test_get_text_console_bad_body(self):
        body = {}
        self._get_console_output_bad_request_case(body)

    def test_get_console_output_with_length_as_float(self):
        body = {'os-getConsoleOutput': {'length': 2.5}}
        self._get_console_output_bad_request_case(body)

    def test_get_console_output_not_ready(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fake_get_console_output_not_ready)
        res = self._get_response(length_dict={'length': 3})
        self.assertEqual(409, res.status_int)

    def test_not_implemented(self):
        self.stubs.Set(compute_api.API, 'get_console_output',
                       fakes.fake_not_implemented)
        res = self._get_response()
        self.assertEqual(501, res.status_int)

    def test_get_console_output_with_boolean_length(self):
        res = self._get_response(length_dict={'length': True})
        self.assertEqual(400, res.status_int)


class ConsoleOutputExtensionTestV2(ConsoleOutputExtensionTestV21):
    need_osapi_compute_extension = True
    action_url = '/v2/fake/servers/1/action'

    def _get_app(self):
        self.flags(osapi_compute_extension=[
            'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Console_output'])
        return fakes.wsgi_app(init_only=('servers',))

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

import mock
import webob

from nova.api.openstack.compute import console_output \
        as console_output_v21
from nova.compute import api as compute_api
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


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


def fake_get(self, context, instance_uuid, expected_attrs=None,
             cell_down_support=False):
    return fake_instance.fake_instance_obj(context, **{'uuid': instance_uuid})


def fake_get_not_found(*args, **kwargs):
    raise exception.InstanceNotFound(instance_id='fake')


class ConsoleOutputExtensionTestV21(test.NoDBTestCase):
    controller_class = console_output_v21
    validation_error = exception.ValidationError

    def setUp(self):
        super(ConsoleOutputExtensionTestV21, self).setUp()
        self.stub_out('nova.compute.api.API.get_console_output',
                      fake_get_console_output)
        self.stub_out('nova.compute.api.API.get', fake_get)
        self.controller = self.controller_class.ConsoleOutputController()
        self.req = fakes.HTTPRequest.blank('')

    def _get_console_output(self, length_dict=None):
        length_dict = length_dict or {}
        body = {'os-getConsoleOutput': length_dict}
        return self.controller.get_console_output(self.req, fakes.FAKE_UUID,
                                                    body=body)

    def _check_console_output_failure(self, exception, body):
        self.assertRaises(exception,
                          self.controller.get_console_output,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_get_text_console_instance_action(self):
        output = self._get_console_output()
        self.assertEqual({'output': '0\n1\n2\n3\n4'}, output)

    def test_get_console_output_with_tail(self):
        output = self._get_console_output(length_dict={'length': 3})
        self.assertEqual({'output': '2\n3\n4'}, output)

    def test_get_console_output_with_none_length(self):
        output = self._get_console_output(length_dict={'length': None})
        self.assertEqual({'output': '0\n1\n2\n3\n4'}, output)

    def test_get_console_output_with_length_as_str(self):
        output = self._get_console_output(length_dict={'length': '3'})
        self.assertEqual({'output': '2\n3\n4'}, output)

    def test_get_console_output_filtered_characters(self):
        self.stub_out('nova.compute.api.API.get_console_output',
                      fake_get_console_output_all_characters)
        output = self._get_console_output()
        expect = (string.digits + string.ascii_letters +
                  string.punctuation + ' \t\n')
        self.assertEqual({'output': expect}, output)

    def test_get_text_console_no_instance(self):
        self.stub_out('nova.compute.api.API.get', fake_get_not_found)
        body = {'os-getConsoleOutput': {}}
        self._check_console_output_failure(webob.exc.HTTPNotFound, body)

    def test_get_text_console_no_instance_on_get_output(self):
        self.stub_out('nova.compute.api.API.get_console_output',
                      fake_get_not_found)
        body = {'os-getConsoleOutput': {}}
        self._check_console_output_failure(webob.exc.HTTPNotFound, body)

    def test_get_console_output_with_non_integer_length(self):
        body = {'os-getConsoleOutput': {'length': 'NaN'}}
        self._check_console_output_failure(self.validation_error, body)

    def test_get_text_console_bad_body(self):
        body = {}
        self._check_console_output_failure(self.validation_error, body)

    def test_get_console_output_with_length_as_float(self):
        body = {'os-getConsoleOutput': {'length': 2.5}}
        self._check_console_output_failure(self.validation_error, body)

    def test_get_console_output_not_ready(self):
        self.stub_out('nova.compute.api.API.get_console_output',
                      fake_get_console_output_not_ready)
        body = {'os-getConsoleOutput': {}}
        self._check_console_output_failure(webob.exc.HTTPConflict, body)

    def test_not_implemented(self):
        self.stub_out('nova.compute.api.API.get_console_output',
                      fakes.fake_not_implemented)
        body = {'os-getConsoleOutput': {}}
        self._check_console_output_failure(webob.exc.HTTPNotImplemented, body)

    def test_get_console_output_with_boolean_length(self):
        body = {'os-getConsoleOutput': {'length': True}}
        self._check_console_output_failure(self.validation_error, body)

    @mock.patch.object(compute_api.API, 'get_console_output',
                       side_effect=exception.ConsoleNotAvailable(
                           instance_uuid='fake_uuid'))
    def test_get_console_output_not_available(self, mock_get_console_output):
        body = {'os-getConsoleOutput': {}}
        self._check_console_output_failure(webob.exc.HTTPNotFound, body)


class ConsoleOutputPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ConsoleOutputPolicyEnforcementV21, self).setUp()
        self.controller = console_output_v21.ConsoleOutputController()

    def test_get_console_output_policy_failed(self):
        rule_name = "os_compute_api:os-console-output"
        self.policy.set_rules({rule_name: "project:non_fake"})
        req = fakes.HTTPRequest.blank('')
        body = {'os-getConsoleOutput': {}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.get_console_output, req, fakes.FAKE_UUID,
            body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

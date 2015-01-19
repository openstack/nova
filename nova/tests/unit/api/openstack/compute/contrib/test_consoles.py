# Copyright 2012 OpenStack Foundation
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

import mock
import webob

from nova.api.openstack.compute.contrib import consoles \
    as console_v2
from nova.api.openstack.compute.plugins.v3 import remote_consoles \
    as console_v21
from nova.compute import api as compute_api
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_get_vnc_console(self, _context, _instance, _console_type):
    return {'url': 'http://fake'}


def fake_get_spice_console(self, _context, _instance, _console_type):
    return {'url': 'http://fake'}


def fake_get_rdp_console(self, _context, _instance, _console_type):
    return {'url': 'http://fake'}


def fake_get_serial_console(self, _context, _instance, _console_type):
    return {'url': 'http://fake'}


def fake_get_vnc_console_invalid_type(self, _context,
                                      _instance, _console_type):
    raise exception.ConsoleTypeInvalid(console_type=_console_type)


def fake_get_spice_console_invalid_type(self, _context,
                                      _instance, _console_type):
    raise exception.ConsoleTypeInvalid(console_type=_console_type)


def fake_get_rdp_console_invalid_type(self, _context,
                                      _instance, _console_type):
    raise exception.ConsoleTypeInvalid(console_type=_console_type)


def fake_get_vnc_console_type_unavailable(self, _context,
                                          _instance, _console_type):
    raise exception.ConsoleTypeUnavailable(console_type=_console_type)


def fake_get_spice_console_type_unavailable(self, _context,
                                            _instance, _console_type):
    raise exception.ConsoleTypeUnavailable(console_type=_console_type)


def fake_get_rdp_console_type_unavailable(self, _context,
                                            _instance, _console_type):
    raise exception.ConsoleTypeUnavailable(console_type=_console_type)


def fake_get_vnc_console_not_ready(self, _context, instance, _console_type):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_get_spice_console_not_ready(self, _context, instance, _console_type):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_get_rdp_console_not_ready(self, _context, instance, _console_type):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_get_vnc_console_not_found(self, _context, instance, _console_type):
    raise exception.InstanceNotFound(instance_id=instance["uuid"])


def fake_get_spice_console_not_found(self, _context, instance, _console_type):
    raise exception.InstanceNotFound(instance_id=instance["uuid"])


def fake_get_rdp_console_not_found(self, _context, instance, _console_type):
    raise exception.InstanceNotFound(instance_id=instance["uuid"])


def fake_get(self, context, instance_uuid, want_objects=False,
             expected_attrs=None):
    return {'uuid': instance_uuid}


def fake_get_not_found(self, context, instance_uuid, want_objects=False,
                       expected_attrs=None):
    raise exception.InstanceNotFound(instance_id=instance_uuid)


class ConsolesExtensionTestV21(test.NoDBTestCase):
    controller_class = console_v21.RemoteConsolesController
    validation_error = exception.ValidationError

    def setUp(self):
        super(ConsolesExtensionTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console)
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console)
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console)
        self.stubs.Set(compute_api.API, 'get_serial_console',
                       fake_get_serial_console)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.controller = self.controller_class()

    def _check_console_failure(self, func, exception, body):
        req = fakes.HTTPRequest.blank('')
        self.assertRaises(exception,
                          eval(func),
                          req, fakes.FAKE_UUID, body=body)

    def test_get_vnc_console(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_vnc_console(req, fakes.FAKE_UUID,
                                                 body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'novnc'}})

    def test_get_vnc_console_not_ready(self):
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console_not_ready)
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    webob.exc.HTTPConflict,
                                    body)

    def test_get_vnc_console_no_type(self):
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console_invalid_type)
        body = {'os-getVNCConsole': {}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    self.validation_error,
                                    body)

    def test_get_vnc_console_no_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_get_not_found)
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_vnc_console_no_instance_on_console_get(self):
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console_not_found)
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_vnc_console_invalid_type(self):
        body = {'os-getVNCConsole': {'type': 'invalid'}}
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console_invalid_type)
        self._check_console_failure('self.controller.get_vnc_console',
                                    self.validation_error,
                                    body)

    def test_get_vnc_console_type_unavailable(self):
        body = {'os-getVNCConsole': {'type': 'unavailable'}}
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fake_get_vnc_console_type_unavailable)
        self._check_console_failure('self.controller.get_vnc_console',
                                    self.validation_error,
                                    body)

    def test_get_vnc_console_not_implemented(self):
        self.stubs.Set(compute_api.API, 'get_vnc_console',
                       fakes.fake_not_implemented)

        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    webob.exc.HTTPNotImplemented,
                                    body)

    def test_get_spice_console(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_spice_console(req, fakes.FAKE_UUID,
                                                   body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'spice-html5'}})

    def test_get_spice_console_not_ready(self):
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console_not_ready)
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure('self.controller.get_spice_console',
                                    webob.exc.HTTPConflict,
                                    body)

    def test_get_spice_console_no_type(self):
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console_invalid_type)
        body = {'os-getSPICEConsole': {}}
        self._check_console_failure('self.controller.get_spice_console',
                                    self.validation_error,
                                    body)

    def test_get_spice_console_no_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_get_not_found)
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure('self.controller.get_spice_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_spice_console_no_instance_on_console_get(self):
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console_not_found)
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure('self.controller.get_spice_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_spice_console_invalid_type(self):
        body = {'os-getSPICEConsole': {'type': 'invalid'}}
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console_invalid_type)
        self._check_console_failure('self.controller.get_spice_console',
                                    self.validation_error,
                                    body)

    def test_get_spice_console_not_implemented(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fakes.fake_not_implemented)
        self._check_console_failure('self.controller.get_spice_console',
                                    webob.exc.HTTPNotImplemented,
                                    body)

    def test_get_spice_console_type_unavailable(self):
        body = {'os-getSPICEConsole': {'type': 'unavailable'}}
        self.stubs.Set(compute_api.API, 'get_spice_console',
                       fake_get_spice_console_type_unavailable)
        self._check_console_failure('self.controller.get_spice_console',
                                    self.validation_error,
                                    body)

    def test_get_rdp_console(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_rdp_console(req, fakes.FAKE_UUID,
                                                 body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'rdp-html5'}})

    def test_get_rdp_console_not_ready(self):
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console_not_ready)
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure('self.controller.get_rdp_console',
                                    webob.exc.HTTPConflict,
                                    body)

    def test_get_rdp_console_no_type(self):
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console_invalid_type)
        body = {'os-getRDPConsole': {}}
        self._check_console_failure('self.controller.get_rdp_console',
                                    self.validation_error,
                                    body)

    def test_get_rdp_console_no_instance(self):
        self.stubs.Set(compute_api.API, 'get', fake_get_not_found)
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure('self.controller.get_rdp_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_rdp_console_no_instance_on_console_get(self):
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console_not_found)
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure('self.controller.get_rdp_console',
                                    webob.exc.HTTPNotFound,
                                    body)

    def test_get_rdp_console_invalid_type(self):
        body = {'os-getRDPConsole': {'type': 'invalid'}}
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console_invalid_type)
        self._check_console_failure('self.controller.get_rdp_console',
                                    self.validation_error,
                                    body)

    def test_get_rdp_console_type_unavailable(self):
        body = {'os-getRDPConsole': {'type': 'unavailable'}}
        self.stubs.Set(compute_api.API, 'get_rdp_console',
                       fake_get_rdp_console_type_unavailable)
        self._check_console_failure('self.controller.get_rdp_console',
                                    self.validation_error,
                                    body)

    def test_get_vnc_console_with_undefined_param(self):
        body = {'os-getVNCConsole': {'type': 'novnc', 'undefined': 'foo'}}
        self._check_console_failure('self.controller.get_vnc_console',
                                    self.validation_error,
                                    body)

    def test_get_spice_console_with_undefined_param(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5',
                                      'undefined': 'foo'}}
        self._check_console_failure('self.controller.get_spice_console',
                                    self.validation_error,
                                    body)

    def test_get_rdp_console_with_undefined_param(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5', 'undefined': 'foo'}}
        self._check_console_failure('self.controller.get_rdp_console',
                                    self.validation_error,
                                    body)

    def test_get_serial_console(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_serial_console(req, fakes.FAKE_UUID,
                                                    body=body)
        self.assertEqual({u'console': {u'url': u'http://fake',
                                       u'type': u'serial'}},
                         output)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_not_enable(self, get_serial_console):
        get_serial_console.side_effect = exception.ConsoleTypeUnavailable(
            console_type="serial")

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPBadRequest,
                                    body)
        self.assertTrue(get_serial_console.called)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_invalid_type(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.ConsoleTypeInvalid(console_type='invalid'))

        body = {'os-getSerialConsole': {'type': 'invalid'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    self.validation_error,
                                    body)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_no_type(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.ConsoleTypeInvalid(console_type=''))

        body = {'os-getSerialConsole': {}}
        self._check_console_failure('self.controller.get_serial_console',
                                    self.validation_error,
                                    body)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_no_instance(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.InstanceNotFound(instance_id='xxx'))

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPNotFound,
                                    body)
        self.assertTrue(get_serial_console.called)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_instance_not_ready(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.InstanceNotReady(instance_id='xxx'))

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPConflict,
                                    body)
        self.assertTrue(get_serial_console.called)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_socket_exhausted(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.SocketPortRangeExhaustedException(
                host='127.0.0.1'))

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPBadRequest,
                                    body)
        self.assertTrue(get_serial_console.called)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_image_nport_invalid(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.ImageSerialPortNumberInvalid(
                num_ports='x', property="hw_serial_port_count"))

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPBadRequest,
                                    body)
        self.assertTrue(get_serial_console.called)

    @mock.patch.object(compute_api.API, 'get_serial_console')
    def test_get_serial_console_image_nport_exceed(self, get_serial_console):
        get_serial_console.side_effect = (
            exception.ImageSerialPortNumberExceedFlavorValue())

        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure('self.controller.get_serial_console',
                                    webob.exc.HTTPBadRequest,
                                    body)
        self.assertTrue(get_serial_console.called)


class ConsolesExtensionTestV2(ConsolesExtensionTestV21):
    controller_class = console_v2.ConsolesController
    validation_error = webob.exc.HTTPBadRequest

    def test_get_vnc_console_with_undefined_param(self):
        pass

    def test_get_spice_console_with_undefined_param(self):
        pass

    def test_get_rdp_console_with_undefined_param(self):
        pass

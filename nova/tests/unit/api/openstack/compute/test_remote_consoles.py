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

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import remote_consoles \
    as console_v21
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class ConsolesExtensionTestV21(test.NoDBTestCase):
    controller_class = console_v21.RemoteConsolesController
    validation_error = exception.ValidationError

    def setUp(self):
        super(ConsolesExtensionTestV21, self).setUp()
        self.instance = objects.Instance(uuid=fakes.FAKE_UUID)
        self.stub_out('nova.compute.api.API.get',
                      lambda *a, **kw: self.instance)
        self.controller = self.controller_class()

    def _check_console_failure(self, func, expected_exception, body,
                               mocked_method=None, raised_exception=None):
        req = fakes.HTTPRequest.blank('')

        if mocked_method:
            @mock.patch.object(compute_api.API, mocked_method,
                               side_effect=raised_exception)
            def _do_test(mock_method):
                self.assertRaises(expected_exception,
                                  func,
                                  req, fakes.FAKE_UUID, body=body)
                self.assertTrue(mock_method.called)

            _do_test()
        else:
            self.assertRaises(expected_exception,
                              func,
                              req, fakes.FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'get_vnc_console',
                       return_value={'url': 'http://fake'})
    def test_get_vnc_console(self, mock_get_vnc_console):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_vnc_console(req, fakes.FAKE_UUID,
                                                 body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'novnc'}})
        mock_get_vnc_console.assert_called_once_with(
            req.environ['nova.context'], self.instance, 'novnc')

    def test_get_vnc_console_not_ready(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            webob.exc.HTTPConflict,
            body,
            'get_vnc_console',
            exception.InstanceNotReady(instance_id=fakes.FAKE_UUID))

    def test_get_vnc_console_no_type(self):
        body = {'os-getVNCConsole': {}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            self.validation_error,
            body)

    def test_get_vnc_console_no_instance(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            webob.exc.HTTPNotFound,
            body,
            'get',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_vnc_console_no_instance_on_console_get(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            webob.exc.HTTPNotFound,
            body,
            'get_vnc_console',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_vnc_console_invalid_type(self):
        body = {'os-getVNCConsole': {'type': 'invalid'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            self.validation_error,
            body)

    def test_get_vnc_console_type_unavailable(self):
        body = {'os-getVNCConsole': {'type': 'unavailable'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            self.validation_error,
            body)

    def test_get_vnc_console_not_implemented(self):
        body = {'os-getVNCConsole': {'type': 'novnc'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            webob.exc.HTTPNotImplemented,
            body,
            'get_vnc_console',
            NotImplementedError())

    @mock.patch.object(compute_api.API, 'get_spice_console',
                       return_value={'url': 'http://fake'})
    def test_get_spice_console(self, mock_get_spice_console):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_spice_console(req, fakes.FAKE_UUID,
                                                   body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'spice-html5'}})
        mock_get_spice_console.assert_called_once_with(
            req.environ['nova.context'], self.instance, 'spice-html5')

    def test_get_spice_console_not_ready(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            webob.exc.HTTPConflict,
            body,
            'get_spice_console',
            exception.InstanceNotReady(instance_id=fakes.FAKE_UUID))

    def test_get_spice_console_no_type(self):
        body = {'os-getSPICEConsole': {}}
        self._check_console_failure(
            self.controller.get_spice_console,
            self.validation_error,
            body)

    def test_get_spice_console_no_instance(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            webob.exc.HTTPNotFound,
            body,
            'get',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_spice_console_no_instance_on_console_get(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            webob.exc.HTTPNotFound,
            body,
            'get_spice_console',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_spice_console_invalid_type(self):
        body = {'os-getSPICEConsole': {'type': 'invalid'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            self.validation_error,
            body)

    def test_get_spice_console_not_implemented(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            webob.exc.HTTPNotImplemented,
            body,
            'get_spice_console',
            NotImplementedError())

    def test_get_spice_console_type_unavailable(self):
        body = {'os-getSPICEConsole': {'type': 'unavailable'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            self.validation_error,
            body)

    @mock.patch.object(compute_api.API, 'get_rdp_console',
                       return_value={'url': 'http://fake'})
    def test_get_rdp_console(self, mock_get_rdp_console):
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_rdp_console(req, fakes.FAKE_UUID,
                                                 body=body)
        self.assertEqual(output,
            {u'console': {u'url': u'http://fake', u'type': u'rdp-html5'}})
        mock_get_rdp_console.assert_called_once_with(
            req.environ['nova.context'], self.instance, 'rdp-html5')

    def test_get_rdp_console_not_ready(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            webob.exc.HTTPConflict,
            body,
            'get_rdp_console',
            exception.InstanceNotReady(instance_id=fakes.FAKE_UUID))

    def test_get_rdp_console_no_type(self):
        body = {'os-getRDPConsole': {}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            self.validation_error,
            body)

    def test_get_rdp_console_no_instance(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            webob.exc.HTTPNotFound,
            body,
            'get',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_rdp_console_no_instance_on_console_get(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            webob.exc.HTTPNotFound,
            body,
            'get_rdp_console',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_rdp_console_invalid_type(self):
        body = {'os-getRDPConsole': {'type': 'invalid'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            self.validation_error,
            body)

    def test_get_rdp_console_type_unavailable(self):
        body = {'os-getRDPConsole': {'type': 'unavailable'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            self.validation_error,
            body)

    def test_get_vnc_console_with_undefined_param(self):
        body = {'os-getVNCConsole': {'type': 'novnc', 'undefined': 'foo'}}
        self._check_console_failure(
            self.controller.get_vnc_console,
            self.validation_error,
            body)

    def test_get_spice_console_with_undefined_param(self):
        body = {'os-getSPICEConsole': {'type': 'spice-html5',
                                      'undefined': 'foo'}}
        self._check_console_failure(
            self.controller.get_spice_console,
            self.validation_error,
            body)

    def test_get_rdp_console_with_undefined_param(self):
        body = {'os-getRDPConsole': {'type': 'rdp-html5', 'undefined': 'foo'}}
        self._check_console_failure(
            self.controller.get_rdp_console,
            self.validation_error,
            body)

    @mock.patch.object(compute_api.API, 'get_serial_console',
                       return_value={'url': 'ws://fake'})
    def test_get_serial_console(self, mock_get_serial_console):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        req = fakes.HTTPRequest.blank('')
        output = self.controller.get_serial_console(req, fakes.FAKE_UUID,
                                                    body=body)
        self.assertEqual({u'console': {u'url': u'ws://fake',
                                       u'type': u'serial'}},
                         output)
        mock_get_serial_console.assert_called_once_with(
            req.environ['nova.context'], self.instance, 'serial')

    def test_get_serial_console_not_enable(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPBadRequest,
            body,
            'get_serial_console',
            exception.ConsoleTypeUnavailable(console_type="serial"))

    def test_get_serial_console_invalid_type(self):
        body = {'os-getSerialConsole': {'type': 'invalid'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            self.validation_error,
            body)

    def test_get_serial_console_no_type(self):
        body = {'os-getSerialConsole': {}}
        self._check_console_failure(
            self.controller.get_serial_console,
            self.validation_error,
            body)

    def test_get_serial_console_no_instance(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPNotFound,
            body,
            'get_serial_console',
            exception.InstanceNotFound(instance_id=fakes.FAKE_UUID))

    def test_get_serial_console_instance_not_ready(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPConflict,
            body,
            'get_serial_console',
            exception.InstanceNotReady(instance_id=fakes.FAKE_UUID))

    def test_get_serial_console_socket_exhausted(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPBadRequest,
            body,
            'get_serial_console',
            exception.SocketPortRangeExhaustedException(host='127.0.0.1'))

    def test_get_serial_console_image_nport_invalid(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPBadRequest,
            body,
            'get_serial_console',
            exception.ImageSerialPortNumberInvalid(
                num_ports='x', property="hw_serial_port_count"))

    def test_get_serial_console_image_nport_exceed(self):
        body = {'os-getSerialConsole': {'type': 'serial'}}
        self._check_console_failure(
            self.controller.get_serial_console,
            webob.exc.HTTPBadRequest,
            body,
            'get_serial_console',
            exception.ImageSerialPortNumberExceedFlavorValue())


class ConsolesExtensionTestV26(test.NoDBTestCase):
    def setUp(self):
        super(ConsolesExtensionTestV26, self).setUp()
        self.req = fakes.HTTPRequest.blank('')
        self.context = self.req.environ['nova.context']
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.6')
        self.instance = fake_instance.fake_instance_obj(self.context)
        self.stub_out('nova.compute.api.API.get',
                      lambda *a, **kw: self.instance)
        self.controller = console_v21.RemoteConsolesController()

    def test_create_vnc_console(self):
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "http://fake"}
        self.controller.handlers['vnc'] = mock_handler

        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        output = self.controller.create(self.req, fakes.FAKE_UUID, body=body)
        self.assertEqual({'remote_console': {'protocol': 'vnc',
                                             'type': 'novnc',
                                             'url': 'http://fake'}}, output)
        mock_handler.assert_called_once_with(self.context, self.instance,
                                             'novnc')

    def test_create_spice_console(self):
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "http://fake"}
        self.controller.handlers['spice'] = mock_handler

        body = {'remote_console': {'protocol': 'spice',
                                   'type': 'spice-html5'}}
        output = self.controller.create(self.req, fakes.FAKE_UUID, body=body)
        self.assertEqual({'remote_console': {'protocol': 'spice',
                                             'type': 'spice-html5',
                                             'url': 'http://fake'}}, output)
        mock_handler.assert_called_once_with(self.context, self.instance,
                                             'spice-html5')

    def test_create_rdp_console(self):
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "http://fake"}
        self.controller.handlers['rdp'] = mock_handler

        body = {'remote_console': {'protocol': 'rdp', 'type': 'rdp-html5'}}
        output = self.controller.create(self.req, fakes.FAKE_UUID, body=body)
        self.assertEqual({'remote_console': {'protocol': 'rdp',
                                             'type': 'rdp-html5',
                                             'url': 'http://fake'}}, output)
        mock_handler.assert_called_once_with(self.context, self.instance,
                                             'rdp-html5')

    def test_create_serial_console(self):
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "ws://fake"}
        self.controller.handlers['serial'] = mock_handler

        body = {'remote_console': {'protocol': 'serial', 'type': 'serial'}}
        output = self.controller.create(self.req, fakes.FAKE_UUID, body=body)
        self.assertEqual({'remote_console': {'protocol': 'serial',
                                             'type': 'serial',
                                             'url': 'ws://fake'}}, output)
        mock_handler.assert_called_once_with(self.context, self.instance,
                                             'serial')

    def test_create_console_instance_not_ready(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = exception.InstanceNotReady(
            instance_id='xxx')
        self.controller.handlers['vnc'] = mock_handler

        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_unavailable(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = exception.ConsoleTypeUnavailable(
            console_type='vnc')
        self.controller.handlers['vnc'] = mock_handler

        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)
        self.assertTrue(mock_handler.called)

    def test_create_console_not_found(self,):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = exception.InstanceNotFound(
            instance_id='xxx')
        self.controller.handlers['vnc'] = mock_handler

        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_not_implemented(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = NotImplementedError()
        self.controller.handlers['vnc'] = mock_handler

        body = {'remote_console': {'protocol': 'vnc', 'type': 'novnc'}}
        self.assertRaises(webob.exc.HTTPNotImplemented, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_nport_invalid(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = exception.ImageSerialPortNumberInvalid(
            num_ports='x', property="hw_serial_port_count")
        self.controller.handlers['serial'] = mock_handler

        body = {'remote_console': {'protocol': 'serial', 'type': 'serial'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_nport_exceed(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = (
            exception.ImageSerialPortNumberExceedFlavorValue())
        self.controller.handlers['serial'] = mock_handler

        body = {'remote_console': {'protocol': 'serial', 'type': 'serial'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_socket_exhausted(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = (
            exception.SocketPortRangeExhaustedException(host='127.0.0.1'))
        self.controller.handlers['serial'] = mock_handler

        body = {'remote_console': {'protocol': 'serial', 'type': 'serial'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)

    def test_create_console_invalid_type(self):
        mock_handler = mock.MagicMock()
        mock_handler.side_effect = (
            exception.ConsoleTypeInvalid(console_type='invalid_type'))
        self.controller.handlers['serial'] = mock_handler
        body = {'remote_console': {'protocol': 'serial', 'type': 'xvpvnc'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, fakes.FAKE_UUID, body=body)


class ConsolesExtensionTestV28(ConsolesExtensionTestV26):
    def setUp(self):
        super(ConsolesExtensionTestV28, self).setUp()
        self.req = fakes.HTTPRequest.blank('')
        self.context = self.req.environ['nova.context']
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.8')
        self.controller = console_v21.RemoteConsolesController()

    def test_create_mks_console(self):
        mock_handler = mock.MagicMock()
        mock_handler.return_value = {'url': "http://fake"}
        self.controller.handlers['mks'] = mock_handler

        body = {'remote_console': {'protocol': 'mks', 'type': 'webmks'}}
        output = self.controller.create(self.req, fakes.FAKE_UUID, body=body)
        self.assertEqual({'remote_console': {'protocol': 'mks',
                                             'type': 'webmks',
                                             'url': 'http://fake'}}, output)
        mock_handler.assert_called_once_with(self.context, self.instance,
                                             'webmks')

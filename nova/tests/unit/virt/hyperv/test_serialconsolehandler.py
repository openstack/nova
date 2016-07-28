# Copyright 2016 Cloudbase Solutions Srl
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

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import serialconsolehandler
from nova.virt.hyperv import serialproxy


class SerialConsoleHandlerTestCase(test_base.HyperVBaseTestCase):
    @mock.patch.object(pathutils.PathUtils, 'get_vm_console_log_paths')
    def setUp(self, mock_get_log_paths):
        super(SerialConsoleHandlerTestCase, self).setUp()

        mock_get_log_paths.return_value = [mock.sentinel.log_path]

        self._consolehandler = serialconsolehandler.SerialConsoleHandler(
            mock.sentinel.instance_name)

        self._consolehandler._log_path = mock.sentinel.log_path
        self._consolehandler._pathutils = mock.Mock()
        self._consolehandler._vmutils = mock.Mock()

    @mock.patch.object(serialconsolehandler.SerialConsoleHandler,
                       '_setup_handlers')
    def test_start(self, mock_setup_handlers):
        mock_workers = [mock.Mock(), mock.Mock()]
        self._consolehandler._workers = mock_workers

        self._consolehandler.start()

        mock_setup_handlers.assert_called_once_with()
        for worker in mock_workers:
            worker.start.assert_called_once_with()

    @mock.patch('nova.console.serial.release_port')
    def test_stop(self, mock_release_port):
        mock_serial_proxy = mock.Mock()
        mock_workers = [mock_serial_proxy, mock.Mock()]

        self._consolehandler._serial_proxy = mock_serial_proxy
        self._consolehandler._listen_host = mock.sentinel.host
        self._consolehandler._listen_port = mock.sentinel.port
        self._consolehandler._workers = mock_workers

        self._consolehandler.stop()

        mock_release_port.assert_called_once_with(mock.sentinel.host,
                                                  mock.sentinel.port)
        for worker in mock_workers:
            worker.stop.assert_called_once_with()

    @mock.patch.object(serialconsolehandler.SerialConsoleHandler,
                       '_setup_named_pipe_handlers')
    @mock.patch.object(serialconsolehandler.SerialConsoleHandler,
                       '_setup_serial_proxy_handler')
    def _test_setup_handlers(self, mock_setup_proxy, mock_setup_pipe_handlers,
                             serial_console_enabled=True):
        self.flags(enabled=serial_console_enabled, group='serial_console')

        self._consolehandler._setup_handlers()

        self.assertEqual(serial_console_enabled, mock_setup_proxy.called)
        mock_setup_pipe_handlers.assert_called_once_with()

    def test_setup_handlers(self):
        self._test_setup_handlers()

    def test_setup_handlers_console_disabled(self):
        self._test_setup_handlers(serial_console_enabled=False)

    @mock.patch.object(serialproxy, 'SerialProxy')
    @mock.patch('nova.console.serial.acquire_port')
    @mock.patch.object(serialconsolehandler.threading, 'Event')
    @mock.patch.object(serialconsolehandler.ioutils, 'IOQueue')
    def test_setup_serial_proxy_handler(self, mock_io_queue, mock_event,
                                        mock_acquire_port,
                                        mock_serial_proxy_class):
        mock_input_queue = mock.sentinel.input_queue
        mock_output_queue = mock.sentinel.output_queue
        mock_client_connected = mock_event.return_value
        mock_io_queue.side_effect = [mock_input_queue, mock_output_queue]
        mock_serial_proxy = mock_serial_proxy_class.return_value

        mock_acquire_port.return_value = mock.sentinel.port
        self.flags(proxyclient_address='127.0.0.3',
                   group='serial_console')

        self._consolehandler._setup_serial_proxy_handler()

        mock_serial_proxy_class.assert_called_once_with(
            mock.sentinel.instance_name,
            '127.0.0.3', mock.sentinel.port,
            mock_input_queue,
            mock_output_queue,
            mock_client_connected)

        self.assertIn(mock_serial_proxy, self._consolehandler._workers)

    @mock.patch.object(serialconsolehandler.SerialConsoleHandler,
                       '_get_named_pipe_handler')
    @mock.patch.object(serialconsolehandler.SerialConsoleHandler,
                       '_get_vm_serial_port_mapping')
    def _mock_setup_named_pipe_handlers(self, mock_get_port_mapping,
                                        mock_get_pipe_handler,
                                        serial_port_mapping=None):
        mock_get_port_mapping.return_value = serial_port_mapping

        self._consolehandler._setup_named_pipe_handlers()

        expected_workers = [mock_get_pipe_handler.return_value
                            for port in serial_port_mapping]

        self.assertEqual(expected_workers, self._consolehandler._workers)

        return mock_get_pipe_handler

    def test_setup_ro_pipe_handler(self):
        serial_port_mapping = {
            constants.SERIAL_PORT_TYPE_RW: mock.sentinel.pipe_path
        }

        mock_get_handler = self._mock_setup_named_pipe_handlers(
            serial_port_mapping=serial_port_mapping)

        mock_get_handler.assert_called_once_with(
            mock.sentinel.pipe_path,
            pipe_type=constants.SERIAL_PORT_TYPE_RW,
            enable_logging=True)

    def test_setup_pipe_handlers(self):
        serial_port_mapping = {
            constants.SERIAL_PORT_TYPE_RO: mock.sentinel.ro_pipe_path,
            constants.SERIAL_PORT_TYPE_RW: mock.sentinel.rw_pipe_path
        }

        mock_get_handler = self._mock_setup_named_pipe_handlers(
            serial_port_mapping=serial_port_mapping)

        expected_calls = [mock.call(mock.sentinel.ro_pipe_path,
                                    pipe_type=constants.SERIAL_PORT_TYPE_RO,
                                    enable_logging=True),
                          mock.call(mock.sentinel.rw_pipe_path,
                                    pipe_type=constants.SERIAL_PORT_TYPE_RW,
                                    enable_logging=False)]
        mock_get_handler.assert_has_calls(expected_calls, any_order=True)

    @mock.patch.object(serialconsolehandler.utilsfactory,
                       'get_named_pipe_handler')
    def _test_get_named_pipe_handler(self, mock_get_pipe_handler,
                                     pipe_type=None, enable_logging=False):
        expected_args = {}

        if pipe_type == constants.SERIAL_PORT_TYPE_RW:
            self._consolehandler._input_queue = mock.sentinel.input_queue
            self._consolehandler._output_queue = mock.sentinel.output_queue
            self._consolehandler._client_connected = (
                mock.sentinel.connect_event)
            expected_args.update({
                'input_queue': mock.sentinel.input_queue,
                'output_queue': mock.sentinel.output_queue,
                'connect_event': mock.sentinel.connect_event})

        if enable_logging:
            expected_args['log_file'] = mock.sentinel.log_path

        ret_val = self._consolehandler._get_named_pipe_handler(
            mock.sentinel.pipe_path, pipe_type, enable_logging)

        self.assertEqual(mock_get_pipe_handler.return_value, ret_val)
        mock_get_pipe_handler.assert_called_once_with(
            mock.sentinel.pipe_path,
            **expected_args)

    def test_get_ro_named_pipe_handler(self):
        self._test_get_named_pipe_handler(
            pipe_type=constants.SERIAL_PORT_TYPE_RO,
            enable_logging=True)

    def test_get_rw_named_pipe_handler(self):
        self._test_get_named_pipe_handler(
            pipe_type=constants.SERIAL_PORT_TYPE_RW,
            enable_logging=False)

    def _mock_get_port_connections(self, port_connections):
        get_port_connections = (
            self._consolehandler._vmutils.get_vm_serial_port_connections)
        get_port_connections.return_value = port_connections

    def test_get_vm_serial_port_mapping_having_tagged_pipes(self):
        ro_pipe_path = 'fake_pipe_ro'
        rw_pipe_path = 'fake_pipe_rw'
        self._mock_get_port_connections([ro_pipe_path, rw_pipe_path])

        ret_val = self._consolehandler._get_vm_serial_port_mapping()

        expected_mapping = {
            constants.SERIAL_PORT_TYPE_RO: ro_pipe_path,
            constants.SERIAL_PORT_TYPE_RW: rw_pipe_path
        }

        self.assertEqual(expected_mapping, ret_val)

    def test_get_vm_serial_port_mapping_untagged_pipe(self):
        pipe_path = 'fake_pipe_path'
        self._mock_get_port_connections([pipe_path])

        ret_val = self._consolehandler._get_vm_serial_port_mapping()

        expected_mapping = {constants.SERIAL_PORT_TYPE_RW: pipe_path}
        self.assertEqual(expected_mapping, ret_val)

    def test_get_vm_serial_port_mapping_exception(self):
        self._mock_get_port_connections([])
        self.assertRaises(exception.NovaException,
                          self._consolehandler._get_vm_serial_port_mapping)

    @mock.patch('nova.console.type.ConsoleSerial')
    def test_get_serial_console(self, mock_serial_console):
        self.flags(enabled=True, group='serial_console')
        self._consolehandler._listen_host = mock.sentinel.host
        self._consolehandler._listen_port = mock.sentinel.port

        ret_val = self._consolehandler.get_serial_console()
        self.assertEqual(mock_serial_console.return_value, ret_val)
        mock_serial_console.assert_called_once_with(
            host=mock.sentinel.host,
            port=mock.sentinel.port)

    def test_get_serial_console_disabled(self):
        self.flags(enabled=False, group='serial_console')
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self._consolehandler.get_serial_console)

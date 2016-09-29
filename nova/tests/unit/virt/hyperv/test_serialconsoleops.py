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
from six.moves import builtins

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import serialconsolehandler
from nova.virt.hyperv import serialconsoleops


class SerialConsoleOpsTestCase(test_base.HyperVBaseTestCase):
    def setUp(self):
        super(SerialConsoleOpsTestCase, self).setUp()
        serialconsoleops._console_handlers = {}
        self._serialops = serialconsoleops.SerialConsoleOps()
        self._serialops._pathutils = mock.MagicMock()

    def _setup_console_handler_mock(self):
        mock_console_handler = mock.Mock()
        serialconsoleops._console_handlers = {mock.sentinel.instance_name:
                                              mock_console_handler}
        return mock_console_handler

    @mock.patch.object(serialconsolehandler, 'SerialConsoleHandler')
    @mock.patch.object(serialconsoleops.SerialConsoleOps,
                       'stop_console_handler_unsync')
    def _test_start_console_handler(self, mock_stop_handler,
                                    mock_console_handler,
                                    raise_exception=False):
        mock_handler = mock_console_handler.return_value

        if raise_exception:
            mock_handler.start.side_effect = Exception

        self._serialops.start_console_handler(mock.sentinel.instance_name)

        mock_stop_handler.assert_called_once_with(mock.sentinel.instance_name)
        mock_console_handler.assert_called_once_with(
            mock.sentinel.instance_name)

        if raise_exception:
            mock_handler.stop.assert_called_once_with()
        else:
            console_handler = serialconsoleops._console_handlers.get(
                mock.sentinel.instance_name)
            self.assertEqual(mock_handler, console_handler)

    def test_start_console_handler(self):
        self._test_start_console_handler()

    def test_start_console_handler_exception(self):
        self._test_start_console_handler(raise_exception=True)

    def test_stop_console_handler(self):
        mock_console_handler = self._setup_console_handler_mock()

        self._serialops.stop_console_handler(mock.sentinel.instance_name)

        mock_console_handler.stop.assert_called_once_with()
        handler = serialconsoleops._console_handlers.get(
                mock.sentinel.instance_name)
        self.assertIsNone(handler)

    def test_get_serial_console(self):
        mock_console_handler = self._setup_console_handler_mock()

        ret_val = self._serialops.get_serial_console(
            mock.sentinel.instance_name)

        self.assertEqual(mock_console_handler.get_serial_console(),
                         ret_val)

    def test_get_serial_console_exception(self):
        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self._serialops.get_serial_console,
                          mock.sentinel.instance_name)

    @mock.patch.object(builtins, 'open')
    @mock.patch("os.path.exists")
    def test_get_console_output_exception(self, fake_path_exists, fake_open):
        self._serialops._pathutils.get_vm_console_log_paths.return_value = [
            mock.sentinel.log_path_1, mock.sentinel.log_path_2]
        fake_open.side_effect = IOError
        fake_path_exists.return_value = True

        self.assertRaises(exception.ConsoleLogOutputException,
                          self._serialops.get_console_output,
                          mock.sentinel.instance_name)
        fake_open.assert_called_once_with(mock.sentinel.log_path_2, 'rb')

    @mock.patch('os.path.exists')
    @mock.patch.object(serialconsoleops.SerialConsoleOps,
                       'start_console_handler')
    def test_start_console_handlers(self, mock_get_instance_dir, mock_exists):
        self._serialops._pathutils.get_instance_dir.return_value = [
            mock.sentinel.nova_instance_name,
            mock.sentinel.other_instance_name]
        mock_exists.side_effect = [True, False]

        self._serialops.start_console_handlers()

        self._serialops._vmutils.get_active_instances.assert_called_once_with()

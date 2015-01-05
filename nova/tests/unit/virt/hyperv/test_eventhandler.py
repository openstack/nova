# Copyright 2015 Cloudbase Solutions Srl
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
from os_win import constants
from os_win import exceptions as os_win_exc
from os_win import utilsfactory

from nova.tests.unit.virt.hyperv import test_base
from nova import utils
from nova.virt.hyperv import eventhandler


class EventHandlerTestCase(test_base.HyperVBaseTestCase):
    _FAKE_POLLING_INTERVAL = 3
    _FAKE_EVENT_CHECK_TIMEFRAME = 15

    @mock.patch.object(utilsfactory, 'get_vmutils')
    def setUp(self, mock_get_vmutils):
        super(EventHandlerTestCase, self).setUp()

        self._state_change_callback = mock.Mock()
        self.flags(
            power_state_check_timeframe=self._FAKE_EVENT_CHECK_TIMEFRAME,
            group='hyperv')
        self.flags(
            power_state_event_polling_interval=self._FAKE_POLLING_INTERVAL,
            group='hyperv')

        self._event_handler = eventhandler.InstanceEventHandler(
            self._state_change_callback)
        self._event_handler._serial_console_ops = mock.Mock()

    @mock.patch.object(eventhandler.InstanceEventHandler,
                       '_get_instance_uuid')
    @mock.patch.object(eventhandler.InstanceEventHandler, '_emit_event')
    def _test_event_callback(self, mock_emit_event, mock_get_uuid,
                             missing_uuid=False):
        mock_get_uuid.return_value = (
            mock.sentinel.instance_uuid if not missing_uuid else None)
        self._event_handler._vmutils.get_vm_power_state.return_value = (
            mock.sentinel.power_state)

        self._event_handler._event_callback(mock.sentinel.instance_name,
                                            mock.sentinel.power_state)

        if not missing_uuid:
            mock_emit_event.assert_called_once_with(
                mock.sentinel.instance_name,
                mock.sentinel.instance_uuid,
                mock.sentinel.power_state)
        else:
            self.assertFalse(mock_emit_event.called)

    def test_event_callback_uuid_present(self):
        self._test_event_callback()

    def test_event_callback_missing_uuid(self):
        self._test_event_callback(missing_uuid=True)

    @mock.patch.object(eventhandler.InstanceEventHandler, '_get_virt_event')
    @mock.patch.object(utils, 'spawn_n')
    def test_emit_event(self, mock_spawn, mock_get_event):
        self._event_handler._emit_event(mock.sentinel.instance_name,
                                        mock.sentinel.instance_uuid,
                                        mock.sentinel.instance_state)

        virt_event = mock_get_event.return_value
        mock_spawn.assert_has_calls(
            [mock.call(self._state_change_callback, virt_event),
             mock.call(self._event_handler._handle_serial_console_workers,
                       mock.sentinel.instance_name,
                       mock.sentinel.instance_state)])

    def test_handle_serial_console_instance_running(self):
        self._event_handler._handle_serial_console_workers(
            mock.sentinel.instance_name,
            constants.HYPERV_VM_STATE_ENABLED)
        serialops = self._event_handler._serial_console_ops
        serialops.start_console_handler.assert_called_once_with(
            mock.sentinel.instance_name)

    def test_handle_serial_console_instance_stopped(self):
        self._event_handler._handle_serial_console_workers(
            mock.sentinel.instance_name,
            constants.HYPERV_VM_STATE_DISABLED)
        serialops = self._event_handler._serial_console_ops
        serialops.stop_console_handler.assert_called_once_with(
            mock.sentinel.instance_name)

    def _test_get_instance_uuid(self, instance_found=True,
                                missing_uuid=False):
        if instance_found:
            side_effect = (mock.sentinel.instance_uuid
                           if not missing_uuid else None, )
        else:
            side_effect = os_win_exc.HyperVVMNotFoundException(
                vm_name=mock.sentinel.instance_name)
        mock_get_uuid = self._event_handler._vmutils.get_instance_uuid
        mock_get_uuid.side_effect = side_effect

        instance_uuid = self._event_handler._get_instance_uuid(
            mock.sentinel.instance_name)

        expected_uuid = (mock.sentinel.instance_uuid
                         if instance_found and not missing_uuid else None)
        self.assertEqual(expected_uuid, instance_uuid)

    def test_get_nova_created_instance_uuid(self):
        self._test_get_instance_uuid()

    def test_get_deleted_instance_uuid(self):
        self._test_get_instance_uuid(instance_found=False)

    def test_get_instance_uuid_missing_notes(self):
        self._test_get_instance_uuid(missing_uuid=True)

    @mock.patch('nova.virt.event.LifecycleEvent')
    def test_get_virt_event(self, mock_lifecycle_event):
        instance_state = constants.HYPERV_VM_STATE_ENABLED
        expected_transition = self._event_handler._TRANSITION_MAP[
            instance_state]

        virt_event = self._event_handler._get_virt_event(
            mock.sentinel.instance_uuid, instance_state)

        self.assertEqual(mock_lifecycle_event.return_value,
                         virt_event)
        mock_lifecycle_event.assert_called_once_with(
            uuid=mock.sentinel.instance_uuid,
            transition=expected_transition)

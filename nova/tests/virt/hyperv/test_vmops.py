#  Copyright 2014 IBM Corp.
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

from eventlet import timeout as etimeout
import mock

from nova import exception
from nova import test
from nova.tests import fake_instance
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vmops
from nova.virt.hyperv import vmutils


class VMOpsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VMOps class."""

    _FAKE_TIMEOUT = 2

    def __init__(self, test_case_name):
        super(VMOpsTestCase, self).__init__(test_case_name)

    def setUp(self):
        super(VMOpsTestCase, self).setUp()
        self.context = 'fake-context'

        # utilsfactory will check the host OS version via get_hostutils,
        # in order to return the proper Utils Class, so it must be mocked.
        patched_func = mock.patch.object(vmops.utilsfactory,
                                 "get_hostutils")
        patched_func.start()
        self.addCleanup(patched_func.stop)

        self._vmops = vmops.VMOps()

    def test_attach_config_drive(self):
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.InvalidDiskFormat,
                          self._vmops.attach_config_drive,
                          instance, 'C:/fake_instance_dir/configdrive.xxx')

    def test_reboot_hard(self):
        self._test_reboot(vmops.REBOOT_TYPE_HARD,
                          constants.HYPERV_VM_STATE_REBOOT)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = True
        self._test_reboot(vmops.REBOOT_TYPE_SOFT,
                          constants.HYPERV_VM_STATE_ENABLED)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft_failed(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = False
        self._test_reboot(vmops.REBOOT_TYPE_SOFT,
                          constants.HYPERV_VM_STATE_REBOOT)

    @mock.patch("nova.virt.hyperv.vmops.VMOps.power_on")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft_exception(self, mock_soft_shutdown, mock_power_on):
        mock_soft_shutdown.return_value = True
        mock_power_on.side_effect = vmutils.HyperVException("Expected failure")
        instance = fake_instance.fake_instance_obj(self.context)

        self.assertRaises(vmutils.HyperVException, self._vmops.reboot,
                          instance, {}, vmops.REBOOT_TYPE_SOFT)

        mock_soft_shutdown.assert_called_once_with(instance)
        mock_power_on.assert_called_once_with(instance)

    def _test_reboot(self, reboot_type, vm_state):
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self._vmops, '_set_vm_state') as mock_set_state:
            self._vmops.reboot(instance, {}, reboot_type)
            mock_set_state.assert_called_once_with(instance, vm_state)

    @mock.patch("nova.virt.hyperv.vmutils.VMUtils.soft_shutdown_vm")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown(self, mock_wait_for_power_off, mock_shutdown_vm):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.return_value = True

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT)

        mock_shutdown_vm.assert_called_once_with(instance.name)
        mock_wait_for_power_off.assert_called_once_with(
            instance.name, self._FAKE_TIMEOUT)

        self.assertTrue(result)

    @mock.patch("time.sleep")
    @mock.patch("nova.virt.hyperv.vmutils.VMUtils.soft_shutdown_vm")
    def test_soft_shutdown_failed(self, mock_shutdown_vm, mock_sleep):
        instance = fake_instance.fake_instance_obj(self.context)

        mock_shutdown_vm.side_effect = vmutils.HyperVException(
            "Expected failure.")

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT)

        mock_shutdown_vm.assert_called_once_with(instance.name)
        self.assertFalse(result)

    @mock.patch("nova.virt.hyperv.vmutils.VMUtils.soft_shutdown_vm")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown_wait(self, mock_wait_for_power_off,
                                mock_shutdown_vm):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.side_effect = [False, True]

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT, 1)

        calls = [mock.call(instance.name, 1),
                 mock.call(instance.name, self._FAKE_TIMEOUT - 1)]
        mock_shutdown_vm.assert_called_with(instance.name)
        mock_wait_for_power_off.assert_has_calls(calls)

        self.assertTrue(result)

    @mock.patch("nova.virt.hyperv.vmutils.VMUtils.soft_shutdown_vm")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown_wait_timeout(self, mock_wait_for_power_off,
                                        mock_shutdown_vm):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.return_value = False

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT, 1.5)

        calls = [mock.call(instance.name, 1.5),
                 mock.call(instance.name, self._FAKE_TIMEOUT - 1.5)]
        mock_shutdown_vm.assert_called_with(instance.name)
        mock_wait_for_power_off.assert_has_calls(calls)

        self.assertFalse(result)

    def _test_power_off(self, timeout):
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self._vmops, '_set_vm_state') as mock_set_state:
            self._vmops.power_off(instance, timeout)

            mock_set_state.assert_called_once_with(
                instance, constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_hard(self):
        self._test_power_off(timeout=0)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_power_off_exception(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = False
        self._test_power_off(timeout=1)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._set_vm_state")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_power_off_soft(self, mock_soft_shutdown, mock_set_state):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_soft_shutdown.return_value = True

        self._vmops.power_off(instance, 1, 0)

        mock_soft_shutdown.assert_called_once_with(
            instance, 1, vmops.SHUTDOWN_TIME_INCREMENT)
        self.assertFalse(mock_set_state.called)

    def test_get_vm_state(self):
        summary_info = {'EnabledState': constants.HYPERV_VM_STATE_DISABLED}

        with mock.patch.object(self._vmops._vmutils,
                               'get_vm_summary_info') as mock_get_summary_info:
            mock_get_summary_info.return_value = summary_info

            response = self._vmops._get_vm_state(mock.sentinel.FAKE_VM_NAME)
            self.assertEqual(response, constants.HYPERV_VM_STATE_DISABLED)

    @mock.patch.object(vmops.VMOps, '_get_vm_state')
    def test_wait_for_power_off_true(self, mock_get_state):
        mock_get_state.return_value = constants.HYPERV_VM_STATE_DISABLED
        result = self._vmops._wait_for_power_off(
            mock.sentinel.FAKE_VM_NAME, vmops.SHUTDOWN_TIME_INCREMENT)
        mock_get_state.assert_called_with(mock.sentinel.FAKE_VM_NAME)
        self.assertTrue(result)

    @mock.patch.object(vmops.etimeout, "with_timeout")
    def test_wait_for_power_off_false(self, mock_with_timeout):
        mock_with_timeout.side_effect = etimeout.Timeout()
        result = self._vmops._wait_for_power_off(
            mock.sentinel.FAKE_VM_NAME, vmops.SHUTDOWN_TIME_INCREMENT)
        self.assertFalse(result)

    @mock.patch("__builtin__.open")
    @mock.patch("os.path.exists")
    @mock.patch.object(pathutils.PathUtils, 'get_vm_console_log_paths')
    def test_get_console_output_exception(self,
                                          fake_get_vm_log_path,
                                          fake_path_exists,
                                          fake_open):
        fake_vm = mock.MagicMock()

        fake_open.side_effect = vmutils.HyperVException
        fake_path_exists.return_value = True
        fake_get_vm_log_path.return_value = (
            mock.sentinel.fake_console_log_path,
            mock.sentinel.fake_console_log_archived)

        with mock.patch('nova.virt.hyperv.vmops.open', fake_open, create=True):
            self.assertRaises(vmutils.HyperVException,
                              self._vmops.get_console_output,
                              fake_vm)

    def test_list_instance_uuids(self):
        fake_uuid = '4f54fb69-d3a2-45b7-bb9b-b6e6b3d893b3'
        with mock.patch.object(self._vmops._vmutils,
                               'list_instance_notes') as mock_list_notes:
            mock_list_notes.return_value = [('fake_name', [fake_uuid])]

            response = self._vmops.list_instance_uuids()
            mock_list_notes.assert_called_once_with()

        self.assertEqual(response, [fake_uuid])

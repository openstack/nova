#  Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from nova import test
from nova.virt.hyperv import constants
from nova.virt.hyperv import hostutils


class FakeCPUSpec(object):
    """Fake CPU Spec for unit tests."""

    Architecture = mock.sentinel.cpu_arch
    Name = mock.sentinel.cpu_name
    Manufacturer = mock.sentinel.cpu_man
    NumberOfCores = mock.sentinel.cpu_cores
    NumberOfLogicalProcessors = mock.sentinel.cpu_procs


class HostUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V hostutils class."""

    _FAKE_MEMORY_TOTAL = 1024L
    _FAKE_MEMORY_FREE = 512L
    _FAKE_DISK_SIZE = 1024L
    _FAKE_DISK_FREE = 512L
    _FAKE_VERSION_GOOD = '6.2.0'
    _FAKE_VERSION_BAD = '6.1.9'

    def setUp(self):
        self._hostutils = hostutils.HostUtils()
        self._hostutils._conn_cimv2 = mock.MagicMock()

        super(HostUtilsTestCase, self).setUp()

    @mock.patch('nova.virt.hyperv.hostutils.ctypes')
    def test_get_host_tick_count64(self, mock_ctypes):
        tick_count64 = "100"
        mock_ctypes.windll.kernel32.GetTickCount64.return_value = tick_count64
        response = self._hostutils.get_host_tick_count64()
        self.assertEqual(tick_count64, response)

    def test_get_cpus_info(self):
        cpu = mock.MagicMock(spec=FakeCPUSpec)
        self._hostutils._conn_cimv2.query.return_value = [cpu]
        cpu_list = self._hostutils.get_cpus_info()
        self.assertEqual([cpu._mock_children], cpu_list)

    def test_get_memory_info(self):
        memory = mock.MagicMock()
        type(memory).TotalVisibleMemorySize = mock.PropertyMock(
            return_value=self._FAKE_MEMORY_TOTAL)
        type(memory).FreePhysicalMemory = mock.PropertyMock(
            return_value=self._FAKE_MEMORY_FREE)

        self._hostutils._conn_cimv2.query.return_value = [memory]
        total_memory, free_memory = self._hostutils.get_memory_info()

        self.assertEqual(self._FAKE_MEMORY_TOTAL, total_memory)
        self.assertEqual(self._FAKE_MEMORY_FREE, free_memory)

    def test_get_volume_info(self):
        disk = mock.MagicMock()
        type(disk).Size = mock.PropertyMock(return_value=self._FAKE_DISK_SIZE)
        type(disk).FreeSpace = mock.PropertyMock(
            return_value=self._FAKE_DISK_FREE)

        self._hostutils._conn_cimv2.query.return_value = [disk]
        (total_memory, free_memory) = self._hostutils.get_volume_info(
            mock.sentinel.FAKE_DRIVE)

        self.assertEqual(self._FAKE_DISK_SIZE, total_memory)
        self.assertEqual(self._FAKE_DISK_FREE, free_memory)

    def test_check_min_windows_version_true(self):
        self._test_check_min_windows_version(self._FAKE_VERSION_GOOD, True)

    def test_check_min_windows_version_false(self):
        self._test_check_min_windows_version(self._FAKE_VERSION_BAD, False)

    def _test_check_min_windows_version(self, version, expected):
        os = mock.MagicMock()
        os.Version = version
        self._hostutils._conn_cimv2.Win32_OperatingSystem.return_value = [os]
        self.assertEqual(expected,
                         self._hostutils.check_min_windows_version(6, 2))

    def _test_host_power_action(self, action):
        fake_win32 = mock.MagicMock()
        fake_win32.Win32Shutdown = mock.MagicMock()

        self._hostutils._conn_cimv2.Win32_OperatingSystem.return_value = [
            fake_win32]

        if action == constants.HOST_POWER_ACTION_SHUTDOWN:
            self._hostutils.host_power_action(action)
            fake_win32.Win32Shutdown.assert_called_with(
                self._hostutils._HOST_FORCED_SHUTDOWN)
        elif action == constants.HOST_POWER_ACTION_REBOOT:
            self._hostutils.host_power_action(action)
            fake_win32.Win32Shutdown.assert_called_with(
                self._hostutils._HOST_FORCED_REBOOT)
        else:
            self.assertRaises(NotImplementedError,
                              self._hostutils.host_power_action, action)

    def test_host_shutdown(self):
        self._test_host_power_action(constants.HOST_POWER_ACTION_SHUTDOWN)

    def test_host_reboot(self):
        self._test_host_power_action(constants.HOST_POWER_ACTION_REBOOT)

    def test_host_startup(self):
        self._test_host_power_action(constants.HOST_POWER_ACTION_STARTUP)

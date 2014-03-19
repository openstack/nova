# Copyright 2013 Cloudbase Solutions Srl
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

from nova import test

from nova.virt.hyperv import vmutils


class VMUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VMUtils class."""

    _FAKE_VM_NAME = 'fake_vm'
    _FAKE_MEMORY_MB = 2
    _FAKE_VM_PATH = "fake_vm_path"
    _FAKE_VHD_PATH = "fake_vhd_path"
    _FAKE_DVD_PATH = "fake_dvd_path"
    _FAKE_VOLUME_DRIVE_PATH = "fake_volume_drive_path"

    def setUp(self):
        self._vmutils = vmutils.VMUtils()
        self._vmutils._conn = mock.MagicMock()

        super(VMUtilsTestCase, self).setUp()

    def test_enable_vm_metrics_collection(self):
        self.assertRaises(NotImplementedError,
                          self._vmutils.enable_vm_metrics_collection,
                          self._FAKE_VM_NAME)

    def _lookup_vm(self):
        mock_vm = mock.MagicMock()
        self._vmutils._lookup_vm_check = mock.MagicMock(
            return_value=mock_vm)
        mock_vm.path_.return_value = self._FAKE_VM_PATH
        return mock_vm

    def test_set_vm_memory_static(self):
        self._test_set_vm_memory_dynamic(1.0)

    def test_set_vm_memory_dynamic(self):
        self._test_set_vm_memory_dynamic(2.0)

    def _test_set_vm_memory_dynamic(self, dynamic_memory_ratio):
        mock_vm = self._lookup_vm()

        mock_s = self._vmutils._conn.Msvm_VirtualSystemSettingData()[0]
        mock_s.SystemType = 3

        mock_vmsetting = mock.MagicMock()
        mock_vmsetting.associators.return_value = [mock_s]

        self._vmutils._modify_virt_resource = mock.MagicMock()

        self._vmutils._set_vm_memory(mock_vm, mock_vmsetting,
                                     self._FAKE_MEMORY_MB,
                                     dynamic_memory_ratio)

        self._vmutils._modify_virt_resource.assert_called_with(
            mock_s, self._FAKE_VM_PATH)

        if dynamic_memory_ratio > 1:
            self.assertTrue(mock_s.DynamicMemoryEnabled)
        else:
            self.assertFalse(mock_s.DynamicMemoryEnabled)

    @mock.patch('nova.virt.hyperv.vmutils.VMUtils._get_vm_disks')
    def test_get_vm_storage_paths(self, mock_get_vm_disks):
        self._lookup_vm()
        mock_rasds = self._create_mock_disks()
        mock_get_vm_disks.return_value = ([mock_rasds[0]], [mock_rasds[1]])

        storage = self._vmutils.get_vm_storage_paths(self._FAKE_VM_NAME)
        (disk_files, volume_drives) = storage

        self.assertEqual([self._FAKE_VHD_PATH], disk_files)
        self.assertEqual([self._FAKE_VOLUME_DRIVE_PATH], volume_drives)

    def test_get_vm_disks(self):
        mock_vm = self._lookup_vm()
        mock_vmsettings = [mock.MagicMock()]
        mock_vm.associators.return_value = mock_vmsettings

        mock_rasds = self._create_mock_disks()
        mock_vmsettings[0].associators.return_value = mock_rasds

        (disks, volumes) = self._vmutils._get_vm_disks(mock_vm)

        mock_vm.associators.assert_called_with(
            wmi_result_class=self._vmutils._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        mock_vmsettings[0].associators.assert_called_with(
            wmi_result_class=self._vmutils._STORAGE_ALLOC_SETTING_DATA_CLASS)
        self.assertEqual([mock_rasds[0]], disks)
        self.assertEqual([mock_rasds[1]], volumes)

    def _create_mock_disks(self):
        mock_rasd1 = mock.MagicMock()
        mock_rasd1.ResourceSubType = self._vmutils._IDE_DISK_RES_SUB_TYPE
        mock_rasd1.Connection = [self._FAKE_VHD_PATH]

        mock_rasd2 = mock.MagicMock()
        mock_rasd2.ResourceSubType = self._vmutils._PHYS_DISK_RES_SUB_TYPE
        mock_rasd2.HostResource = [self._FAKE_VOLUME_DRIVE_PATH]

        return [mock_rasd1, mock_rasd2]

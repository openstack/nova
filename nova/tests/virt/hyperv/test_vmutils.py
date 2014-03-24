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

    def test_list_instance_notes(self):
        vs = mock.MagicMock()
        attrs = {'ElementName': 'fake_name',
                 'Notes': '4f54fb69-d3a2-45b7-bb9b-b6e6b3d893b3'}
        vs.configure_mock(**attrs)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.return_value = [vs]
        response = self._vmutils.list_instance_notes()

        self.assertEqual([(attrs['ElementName'], [attrs['Notes']])], response)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.assert_called_with(
            ['ElementName', 'Notes'],
            SettingType=self._vmutils._VIRTUAL_SYSTEM_CURRENT_SETTINGS)

    @mock.patch('nova.virt.hyperv.vmutils.VMUtils.check_ret_val')
    def test_modify_virtual_system(self, mock_check_ret_val):
        mock_vs_man_svc = mock.MagicMock()
        mock_vmsetting = mock.MagicMock()
        fake_path = 'fake path'
        fake_job_path = 'fake job path'
        fake_ret_val = 'fake return value'

        mock_vs_man_svc.ModifyVirtualSystem.return_value = (0, fake_job_path,
                                                            fake_ret_val)

        self._vmutils._modify_virtual_system(vs_man_svc=mock_vs_man_svc,
                                             vm_path=fake_path,
                                             vmsetting=mock_vmsetting)

        mock_vs_man_svc.ModifyVirtualSystem.assert_called_once_with(
            ComputerSystem=fake_path,
            SystemSettingData=mock_vmsetting.GetText_(1))
        mock_check_ret_val.assert_called_once_with(fake_ret_val, fake_job_path)

    @mock.patch('nova.virt.hyperv.vmutils.VMUtils.check_ret_val')
    @mock.patch('nova.virt.hyperv.vmutils.VMUtils._get_wmi_obj')
    @mock.patch('nova.virt.hyperv.vmutils.VMUtils._modify_virtual_system')
    @mock.patch('nova.virt.hyperv.vmutils.VMUtils._get_vm_setting_data')
    def test_create_vm_obj(self, mock_get_vm_setting_data,
                           mock_modify_virtual_system,
                           mock_get_wmi_obj, mock_check_ret_val):
        mock_vs_man_svc = mock.MagicMock()
        mock_vs_gs_data = mock.MagicMock()
        fake_vm_path = 'fake vm path'
        fake_job_path = 'fake job path'
        fake_ret_val = 'fake return value'
        _conn = self._vmutils._conn.Msvm_VirtualSystemGlobalSettingData

        _conn.new.return_value = mock_vs_gs_data
        mock_vs_man_svc.DefineVirtualSystem.return_value = (fake_vm_path,
                                                            fake_job_path,
                                                            fake_ret_val)

        response = self._vmutils._create_vm_obj(vs_man_svc=mock_vs_man_svc,
                                                vm_name='fake vm',
                                                notes='fake notes')

        _conn.new.assert_called_once_with()
        self.assertEqual(mock_vs_gs_data.ElementName, 'fake vm')
        mock_vs_man_svc.DefineVirtualSystem.assert_called_once_with(
            [], None, mock_vs_gs_data.GetText_(1))
        mock_check_ret_val.assert_called_once_with(fake_ret_val, fake_job_path)

        mock_get_wmi_obj.assert_called_with(fake_vm_path)
        mock_get_vm_setting_data.assert_called_once_with(mock_get_wmi_obj())
        mock_modify_virtual_system.assert_called_once_with(
            mock_vs_man_svc, fake_vm_path, mock_get_vm_setting_data())

        self.assertEqual(mock_get_vm_setting_data().Notes,
                         '\n'.join('fake notes'))
        self.assertEqual(response, mock_get_wmi_obj())

    def test_list_instances(self):
        vs = mock.MagicMock()
        attrs = {'ElementName': 'fake_name'}
        vs.configure_mock(**attrs)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.return_value = [vs]
        response = self._vmutils.list_instances()

        self.assertEqual([(attrs['ElementName'])], response)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.assert_called_with(
            ['ElementName'],
            SettingType=self._vmutils._VIRTUAL_SYSTEM_CURRENT_SETTINGS)

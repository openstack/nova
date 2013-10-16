# Copyright 2014 Cloudbase Solutions Srl
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
from nova import test
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmutils


class VMUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VMUtils class."""

    _FAKE_VM_NAME = 'fake_vm'
    _FAKE_MEMORY_MB = 2
    _FAKE_VCPUS_NUM = 4
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_RET_VAL = 0
    _FAKE_RET_VAL_BAD = -1
    _FAKE_CTRL_PATH = 'fake_ctrl_path'
    _FAKE_CTRL_ADDR = 0
    _FAKE_DRIVE_ADDR = 0
    _FAKE_MOUNTED_DISK_PATH = 'fake_mounted_disk_path'
    _FAKE_VM_PATH = "fake_vm_path"
    _FAKE_VHD_PATH = "fake_vhd_path"
    _FAKE_DVD_PATH = "fake_dvd_path"
    _FAKE_VOLUME_DRIVE_PATH = "fake_volume_drive_path"
    _FAKE_SNAPSHOT_PATH = "fake_snapshot_path"
    _FAKE_RES_DATA = "fake_res_data"
    _FAKE_HOST_RESOURCE = "fake_host_resource"
    _FAKE_CLASS = "FakeClass"
    _FAKE_RES_PATH = "fake_res_path"
    _FAKE_RES_NAME = 'fake_res_name'
    _FAKE_ADDRESS = "fake_address"
    _FAKE_JOB_STATUS_DONE = 7
    _FAKE_JOB_STATUS_BAD = -1
    _FAKE_JOB_DESCRIPTION = "fake_job_description"
    _FAKE_ERROR = "fake_error"
    _FAKE_ELAPSED_TIME = 0
    _CONCRETE_JOB = "Msvm_ConcreteJob"
    _FAKE_DYNAMIC_MEMORY_RATIO = 1.0

    _FAKE_SUMMARY_INFO = {'NumberOfProcessors': 4,
                          'EnabledState': 2,
                          'MemoryUsage': 2,
                          'UpTime': 1}

    _DEFINE_SYSTEM = 'DefineVirtualSystem'
    _DESTROY_SYSTEM = 'DestroyVirtualSystem'
    _DESTROY_SNAPSHOT = 'RemoveVirtualSystemSnapshot'
    _ADD_RESOURCE = 'AddVirtualSystemResources'
    _REMOVE_RESOURCE = 'RemoveVirtualSystemResources'
    _SETTING_TYPE = 'SettingType'

    _VIRTUAL_SYSTEM_TYPE_REALIZED = 3

    def setUp(self):
        self._vmutils = vmutils.VMUtils()
        self._vmutils._conn = mock.MagicMock()

        super(VMUtilsTestCase, self).setUp()

    def test_enable_vm_metrics_collection(self):
        self.assertRaises(NotImplementedError,
                          self._vmutils.enable_vm_metrics_collection,
                          self._FAKE_VM_NAME)

    def test_get_vm_summary_info(self):
        self._lookup_vm()
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]

        mock_summary = mock.MagicMock()
        mock_svc.GetSummaryInformation.return_value = (self._FAKE_RET_VAL,
                                                       [mock_summary])

        for (key, val) in self._FAKE_SUMMARY_INFO.items():
            setattr(mock_summary, key, val)

        summary = self._vmutils.get_vm_summary_info(self._FAKE_VM_NAME)
        self.assertEqual(self._FAKE_SUMMARY_INFO, summary)

    def _lookup_vm(self):
        mock_vm = mock.MagicMock()
        self._vmutils._lookup_vm_check = mock.MagicMock(
            return_value=mock_vm)
        mock_vm.path_.return_value = self._FAKE_VM_PATH
        return mock_vm

    def test_lookup_vm_ok(self):
        mock_vm = mock.MagicMock()
        self._vmutils._conn.Msvm_ComputerSystem.return_value = [mock_vm]
        vm = self._vmutils._lookup_vm_check(self._FAKE_VM_NAME)
        self.assertEqual(mock_vm, vm)

    def test_lookup_vm_multiple(self):
        mockvm = mock.MagicMock()
        self._vmutils._conn.Msvm_ComputerSystem.return_value = [mockvm, mockvm]
        self.assertRaises(vmutils.HyperVException,
                          self._vmutils._lookup_vm_check,
                          self._FAKE_VM_NAME)

    def test_lookup_vm_none(self):
        self._vmutils._conn.Msvm_ComputerSystem.return_value = []
        self.assertRaises(exception.NotFound,
                          self._vmutils._lookup_vm_check,
                          self._FAKE_VM_NAME)

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
        mock_rasd1.HostResource = [self._FAKE_VHD_PATH]
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

    @mock.patch.object(vmutils.VMUtils, '_set_vm_vcpus')
    @mock.patch.object(vmutils.VMUtils, '_set_vm_memory')
    @mock.patch.object(vmutils.VMUtils, '_get_wmi_obj')
    def test_create_vm(self, mock_get_wmi_obj, mock_set_mem, mock_set_vcpus):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        getattr(mock_svc, self._DEFINE_SYSTEM).return_value = (
            None, self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        mock_vm = mock_get_wmi_obj.return_value
        self._vmutils._conn.Msvm_ComputerSystem.return_value = [mock_vm]

        mock_s = mock.MagicMock()
        setattr(mock_s,
                self._SETTING_TYPE,
                self._VIRTUAL_SYSTEM_TYPE_REALIZED)
        mock_vm.associators.return_value = [mock_s]

        self._vmutils.create_vm(self._FAKE_VM_NAME, self._FAKE_MEMORY_MB,
                                self._FAKE_VCPUS_NUM, False,
                                self._FAKE_DYNAMIC_MEMORY_RATIO)

        self.assertTrue(getattr(mock_svc, self._DEFINE_SYSTEM).called)
        mock_set_mem.assert_called_with(mock_vm, mock_s, self._FAKE_MEMORY_MB,
                                        self._FAKE_DYNAMIC_MEMORY_RATIO)

        mock_set_vcpus.assert_called_with(mock_vm, mock_s,
                                          self._FAKE_VCPUS_NUM,
                                          False)

    def test_get_vm_scsi_controller(self):
        self._prepare_get_vm_controller(self._vmutils._SCSI_CTRL_RES_SUB_TYPE)
        path = self._vmutils.get_vm_scsi_controller(self._FAKE_VM_NAME)
        self.assertEqual(self._FAKE_RES_PATH, path)

    def test_get_vm_ide_controller(self):
        self._prepare_get_vm_controller(self._vmutils._IDE_CTRL_RES_SUB_TYPE)
        path = self._vmutils.get_vm_ide_controller(self._FAKE_VM_NAME,
                                                   self._FAKE_ADDRESS)
        self.assertEqual(self._FAKE_RES_PATH, path)

    def _prepare_get_vm_controller(self, resource_sub_type):
        mock_vm = self._lookup_vm()
        mock_vm_settings = mock.MagicMock()
        mock_rasds = mock.MagicMock()
        mock_rasds.path_.return_value = self._FAKE_RES_PATH
        mock_rasds.ResourceSubType = resource_sub_type
        mock_rasds.Address = self._FAKE_ADDRESS
        mock_vm_settings.associators.return_value = [mock_rasds]
        mock_vm.associators.return_value = [mock_vm_settings]

    def _prepare_resources(self, mock_path, mock_subtype, mock_vm_settings):
        mock_rasds = mock_vm_settings.associators.return_value[0]
        mock_rasds.path_.return_value = mock_path
        mock_rasds.ResourceSubType = mock_subtype
        return mock_rasds

    @mock.patch.object(vmutils.VMUtils, '_get_new_resource_setting_data')
    @mock.patch.object(vmutils.VMUtils, '_get_vm_ide_controller')
    def test_attach_ide_drive(self, mock_get_ide_ctrl, mock_get_new_rsd):
        mock_vm = self._lookup_vm()
        mock_rsd = mock_get_new_rsd.return_value

        with mock.patch.object(self._vmutils,
                               '_add_virt_resource') as mock_add_virt_res:
            self._vmutils.attach_ide_drive(self._FAKE_VM_NAME,
                                           self._FAKE_CTRL_PATH,
                                           self._FAKE_CTRL_ADDR,
                                           self._FAKE_DRIVE_ADDR)

            mock_add_virt_res.assert_called_with(mock_rsd,
                                                 mock_vm.path_.return_value)

        mock_get_ide_ctrl.assert_called_with(mock_vm, self._FAKE_CTRL_ADDR)
        self.assertTrue(mock_get_new_rsd.called)

    @mock.patch.object(vmutils.VMUtils, '_get_new_resource_setting_data')
    def test_create_scsi_controller(self, mock_get_new_rsd):
        mock_vm = self._lookup_vm()
        with mock.patch.object(self._vmutils,
                               '_add_virt_resource') as mock_add_virt_res:
            self._vmutils.create_scsi_controller(self._FAKE_VM_NAME)

            mock_add_virt_res.assert_called_with(mock_get_new_rsd.return_value,
                                                 mock_vm.path_.return_value)

    @mock.patch.object(vmutils.VMUtils, '_get_new_resource_setting_data')
    def test_attach_volume_to_controller(self, mock_get_new_rsd):
        mock_vm = self._lookup_vm()
        with mock.patch.object(self._vmutils,
                               '_add_virt_resource') as mock_add_virt_res:
            self._vmutils.attach_volume_to_controller(
                self._FAKE_VM_NAME, self._FAKE_CTRL_PATH, self._FAKE_CTRL_ADDR,
                self._FAKE_MOUNTED_DISK_PATH)

            mock_add_virt_res.assert_called_with(mock_get_new_rsd.return_value,
                                                 mock_vm.path_.return_value)

    @mock.patch.object(vmutils.VMUtils, '_modify_virt_resource')
    @mock.patch.object(vmutils.VMUtils, '_get_nic_data_by_name')
    def test_set_nic_connection(self, mock_get_nic_conn, mock_modify_virt_res):
        self._lookup_vm()
        mock_nic = mock_get_nic_conn.return_value
        self._vmutils.set_nic_connection(self._FAKE_VM_NAME, None, None)

        mock_modify_virt_res.assert_called_with(mock_nic, self._FAKE_VM_PATH)

    @mock.patch.object(vmutils.VMUtils, '_get_new_setting_data')
    def test_create_nic(self, mock_get_new_virt_res):
        self._lookup_vm()
        mock_nic = mock_get_new_virt_res.return_value

        with mock.patch.object(self._vmutils,
                               '_add_virt_resource') as mock_add_virt_res:
            self._vmutils.create_nic(
                self._FAKE_VM_NAME, self._FAKE_RES_NAME, self._FAKE_ADDRESS)

            mock_add_virt_res.assert_called_with(mock_nic, self._FAKE_VM_PATH)

    def test_set_vm_state(self):
        mock_vm = self._lookup_vm()
        mock_vm.RequestStateChange.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vmutils.set_vm_state(self._FAKE_VM_NAME,
                                   constants.HYPERV_VM_STATE_ENABLED)
        mock_vm.RequestStateChange.assert_called_with(
            constants.HYPERV_VM_STATE_ENABLED)

    def test_destroy_vm(self):
        self._lookup_vm()

        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        getattr(mock_svc, self._DESTROY_SYSTEM).return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vmutils.destroy_vm(self._FAKE_VM_NAME)

        getattr(mock_svc, self._DESTROY_SYSTEM).assert_called_with(
            self._FAKE_VM_PATH)

    @mock.patch.object(vmutils.VMUtils, '_wait_for_job')
    def test_check_ret_val_ok(self, mock_wait_for_job):
        self._vmutils.check_ret_val(constants.WMI_JOB_STATUS_STARTED,
                                    self._FAKE_JOB_PATH)
        mock_wait_for_job.assert_called_once_with(self._FAKE_JOB_PATH)

    def test_check_ret_val_exception(self):
        self.assertRaises(vmutils.HyperVException,
                          self._vmutils.check_ret_val,
                          self._FAKE_RET_VAL_BAD,
                          self._FAKE_JOB_PATH)

    def test_wait_for_job_done(self):
        mockjob = self._prepare_wait_for_job(constants.WMI_JOB_STATE_COMPLETED)
        job = self._vmutils._wait_for_job(self._FAKE_JOB_PATH)
        self.assertEqual(mockjob, job)

    def test_wait_for_job_exception_concrete_job(self):
        mock_job = self._prepare_wait_for_job()
        mock_job.path.return_value.Class = self._CONCRETE_JOB
        self.assertRaises(vmutils.HyperVException,
                          self._vmutils._wait_for_job,
                          self._FAKE_JOB_PATH)

    def test_wait_for_job_exception_with_error(self):
        mock_job = self._prepare_wait_for_job()
        mock_job.GetError.return_value = (self._FAKE_ERROR, self._FAKE_RET_VAL)
        self.assertRaises(vmutils.HyperVException,
                          self._vmutils._wait_for_job,
                          self._FAKE_JOB_PATH)

    def test_wait_for_job_exception_no_error(self):
        mock_job = self._prepare_wait_for_job()
        mock_job.GetError.return_value = (None, None)
        self.assertRaises(vmutils.HyperVException,
                          self._vmutils._wait_for_job,
                          self._FAKE_JOB_PATH)

    def _prepare_wait_for_job(self, state=_FAKE_JOB_STATUS_BAD):
        mock_job = mock.MagicMock()
        mock_job.JobState = state
        mock_job.Description = self._FAKE_JOB_DESCRIPTION
        mock_job.ElapsedTime = self._FAKE_ELAPSED_TIME

        self._vmutils._get_wmi_obj = mock.MagicMock(return_value=mock_job)
        return mock_job

    def test_add_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        getattr(mock_svc, self._ADD_RESOURCE).return_value = (
            self._FAKE_JOB_PATH, mock.MagicMock(), self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.GetText_.return_value = self._FAKE_RES_DATA

        self._vmutils._add_virt_resource(mock_res_setting_data,
                                         self._FAKE_VM_PATH)
        self._assert_add_resources(mock_svc)

    def test_modify_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.ModifyVirtualSystemResources.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.GetText_.return_value = self._FAKE_RES_DATA

        self._vmutils._modify_virt_resource(mock_res_setting_data,
                                            self._FAKE_VM_PATH)

        mock_svc.ModifyVirtualSystemResources.assert_called_with(
            ResourceSettingData=[self._FAKE_RES_DATA],
            ComputerSystem=self._FAKE_VM_PATH)

    def test_remove_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        getattr(mock_svc, self._REMOVE_RESOURCE).return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.path_.return_value = self._FAKE_RES_PATH

        self._vmutils._remove_virt_resource(mock_res_setting_data,
                                            self._FAKE_VM_PATH)
        self._assert_remove_resources(mock_svc)

    @mock.patch.object(vmutils, 'wmi', create=True)
    @mock.patch.object(vmutils.VMUtils, 'check_ret_val')
    def test_take_vm_snapshot(self, mock_check_ret_val, mock_wmi):
        self._lookup_vm()

        mock_svc = self._get_snapshot_service()
        mock_svc.CreateVirtualSystemSnapshot.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL, mock.MagicMock())

        self._vmutils.take_vm_snapshot(self._FAKE_VM_NAME)

        mock_svc.CreateVirtualSystemSnapshot.assert_called_with(
            self._FAKE_VM_PATH)

        mock_check_ret_val.assert_called_once_with(self._FAKE_RET_VAL,
                                                   self._FAKE_JOB_PATH)

    def test_remove_vm_snapshot(self):
        mock_svc = self._get_snapshot_service()
        getattr(mock_svc, self._DESTROY_SNAPSHOT).return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vmutils.remove_vm_snapshot(self._FAKE_SNAPSHOT_PATH)
        getattr(mock_svc, self._DESTROY_SNAPSHOT).assert_called_with(
            self._FAKE_SNAPSHOT_PATH)

    def test_detach_vm_disk(self):
        self._lookup_vm()
        mock_disk = self._prepare_mock_disk()

        with mock.patch.object(self._vmutils,
                               '_remove_virt_resource') as mock_rm_virt_res:
            self._vmutils.detach_vm_disk(self._FAKE_VM_NAME,
                                         self._FAKE_HOST_RESOURCE)

            mock_rm_virt_res.assert_called_with(mock_disk, self._FAKE_VM_PATH)

    def test_get_mounted_disk_resource_from_path(self):
        mock_disk_1 = mock.MagicMock()
        mock_disk_2 = mock.MagicMock()
        mock_disk_2.HostResource = [self._FAKE_MOUNTED_DISK_PATH]
        self._vmutils._conn.query.return_value = [mock_disk_1, mock_disk_2]

        physical_disk = self._vmutils._get_mounted_disk_resource_from_path(
            self._FAKE_MOUNTED_DISK_PATH)

        self.assertEqual(mock_disk_2, physical_disk)

    def test_get_controller_volume_paths(self):
        self._prepare_mock_disk()
        mock_disks = {self._FAKE_RES_PATH: self._FAKE_HOST_RESOURCE}
        disks = self._vmutils.get_controller_volume_paths(self._FAKE_RES_PATH)
        self.assertEqual(mock_disks, disks)

    def _prepare_mock_disk(self):
        mock_disk = mock.MagicMock()
        mock_disk.HostResource = [self._FAKE_HOST_RESOURCE]
        mock_disk.path.return_value.RelPath = self._FAKE_RES_PATH
        mock_disk.ResourceSubType = self._vmutils._IDE_DISK_RES_SUB_TYPE
        self._vmutils._conn.query.return_value = [mock_disk]

        return mock_disk

    def _get_snapshot_service(self):
        return self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]

    def _assert_add_resources(self, mock_svc):
        getattr(mock_svc, self._ADD_RESOURCE).assert_called_with(
            [self._FAKE_RES_DATA], self._FAKE_VM_PATH)

    def _assert_remove_resources(self, mock_svc):
        getattr(mock_svc, self._REMOVE_RESOURCE).assert_called_with(
            [self._FAKE_RES_PATH], self._FAKE_VM_PATH)

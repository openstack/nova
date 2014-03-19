#  Copyright 2013 Cloudbase Solutions Srl
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

from nova.virt.hyperv import vmutilsv2


class VMUtilsV2TestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VMUtilsV2 class."""

    _FAKE_VM_NAME = 'fake_vm'
    _FAKE_MEMORY_MB = 2
    _FAKE_VCPUS_NUM = 4
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_RET_VAL = 0
    _FAKE_CTRL_PATH = 'fake_ctrl_path'
    _FAKE_CTRL_ADDR = 0
    _FAKE_DRIVE_ADDR = 0
    _FAKE_MOUNTED_DISK_PATH = 'fake_mounted_disk_path'
    _FAKE_VM_PATH = "fake_vm_path"
    _FAKE_ENABLED_STATE = 1
    _FAKE_SNAPSHOT_PATH = "_FAKE_SNAPSHOT_PATH"
    _FAKE_RES_DATA = "fake_res_data"
    _FAKE_RES_PATH = "fake_res_path"
    _FAKE_DYNAMIC_MEMORY_RATIO = 1.0
    _FAKE_VHD_PATH = "fake_vhd_path"
    _FAKE_VOLUME_DRIVE_PATH = "fake_volume_drive_path"

    def setUp(self):
        self._vmutils = vmutilsv2.VMUtilsV2()
        self._vmutils._conn = mock.MagicMock()

        super(VMUtilsV2TestCase, self).setUp()

    def _lookup_vm(self):
        mock_vm = mock.MagicMock()
        self._vmutils._lookup_vm_check = mock.MagicMock(
            return_value=mock_vm)
        mock_vm.path_.return_value = self._FAKE_VM_PATH
        return mock_vm

    def test_create_vm(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.DefineSystem.return_value = (None, self._FAKE_JOB_PATH,
                                              self._FAKE_RET_VAL)

        self._vmutils._get_wmi_obj = mock.MagicMock()
        mock_vm = self._vmutils._get_wmi_obj.return_value

        mock_s = mock.MagicMock()
        mock_s.VirtualSystemType = self._vmutils._VIRTUAL_SYSTEM_TYPE_REALIZED
        mock_vm.associators.return_value = [mock_s]

        self._vmutils._set_vm_memory = mock.MagicMock()
        self._vmutils._set_vm_vcpus = mock.MagicMock()

        self._vmutils.create_vm(self._FAKE_VM_NAME, self._FAKE_MEMORY_MB,
                                self._FAKE_VCPUS_NUM, False,
                                self._FAKE_DYNAMIC_MEMORY_RATIO)

        self.assertTrue(mock_svc.DefineSystem.called)
        self._vmutils._set_vm_memory.assert_called_with(
            mock_vm, mock_s, self._FAKE_MEMORY_MB,
            self._FAKE_DYNAMIC_MEMORY_RATIO)

        self._vmutils._set_vm_vcpus.assert_called_with(mock_vm, mock_s,
                                                       self._FAKE_VCPUS_NUM,
                                                       False)

    def test_attach_ide_drive(self):
        self._lookup_vm()
        self._vmutils._get_vm_ide_controller = mock.MagicMock()
        self._vmutils._get_new_resource_setting_data = mock.MagicMock()
        self._vmutils._add_virt_resource = mock.MagicMock()

        self._vmutils.attach_ide_drive(self._FAKE_VM_NAME,
                                       self._FAKE_CTRL_PATH,
                                       self._FAKE_CTRL_ADDR,
                                       self._FAKE_DRIVE_ADDR)

        self.assertTrue(self._vmutils._get_vm_ide_controller.called)
        self.assertTrue(self._vmutils._get_new_resource_setting_data.called)
        self.assertTrue(self._vmutils._add_virt_resource.called)

    def test_attach_volume_to_controller(self):
        self._lookup_vm()
        self._vmutils._add_virt_resource = mock.MagicMock()

        self._vmutils.attach_volume_to_controller(self._FAKE_VM_NAME,
                                                  self._FAKE_CTRL_PATH,
                                                  self._FAKE_CTRL_ADDR,
                                                  self._FAKE_MOUNTED_DISK_PATH)

        self.assertTrue(self._vmutils._add_virt_resource.called)

    def test_create_scsi_controller(self):
        self._lookup_vm()
        self._vmutils._add_virt_resource = mock.MagicMock()

        self._vmutils.create_scsi_controller(self._FAKE_VM_NAME)

        self.assertTrue(self._vmutils._add_virt_resource.called)

    def test_get_vm_storage_paths(self):
        mock_vm = self._lookup_vm()

        mock_vmsettings = [mock.MagicMock()]
        mock_vm.associators.return_value = mock_vmsettings
        mock_sasds = []
        mock_sasd1 = mock.MagicMock()
        mock_sasd1.ResourceSubType = self._vmutils._IDE_DISK_RES_SUB_TYPE
        mock_sasd1.HostResource = [self._FAKE_VHD_PATH]
        mock_sasd2 = mock.MagicMock()
        mock_sasd2.ResourceSubType = self._vmutils._PHYS_DISK_RES_SUB_TYPE
        mock_sasd2.HostResource = [self._FAKE_VOLUME_DRIVE_PATH]
        mock_sasds.append(mock_sasd1)
        mock_sasds.append(mock_sasd2)
        mock_vmsettings[0].associators.return_value = mock_sasds

        storage = self._vmutils.get_vm_storage_paths(self._FAKE_VM_NAME)
        (disk_files, volume_drives) = storage

        mock_vm.associators.assert_called_with(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        mock_vmsettings[0].associators.assert_called_with(
            wmi_result_class='Msvm_StorageAllocationSettingData')
        self.assertEqual([self._FAKE_VHD_PATH], disk_files)
        self.assertEqual([self._FAKE_VOLUME_DRIVE_PATH], volume_drives)

    def test_destroy(self):
        self._lookup_vm()

        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.DestroySystem.return_value = (self._FAKE_JOB_PATH,
                                               self._FAKE_RET_VAL)

        self._vmutils.destroy_vm(self._FAKE_VM_NAME)

        mock_svc.DestroySystem.assert_called_with(self._FAKE_VM_PATH)

    def test_get_vm_state(self):
        self._vmutils.get_vm_summary_info = mock.MagicMock(
            return_value={'EnabledState': self._FAKE_ENABLED_STATE})

        enabled_state = self._vmutils.get_vm_state(self._FAKE_VM_NAME)

        self.assertEqual(self._FAKE_ENABLED_STATE, enabled_state)

    def test_take_vm_snapshot(self):
        self._lookup_vm()

        mock_svc = self._vmutils._conn.Msvm_VirtualSystemSnapshotService()[0]
        mock_svc.CreateSnapshot.return_value = (self._FAKE_JOB_PATH,
                                                mock.MagicMock(),
                                                self._FAKE_RET_VAL)
        vmutilsv2.wmi = mock.MagicMock()

        self._vmutils.take_vm_snapshot(self._FAKE_VM_NAME)

        mock_svc.CreateSnapshot.assert_called_with(
            AffectedSystem=self._FAKE_VM_PATH,
            SnapshotType=self._vmutils._SNAPSHOT_FULL)

    def test_remove_vm_snapshot(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemSnapshotService()[0]
        mock_svc.DestroySnapshot.return_value = (self._FAKE_JOB_PATH,
                                                 self._FAKE_RET_VAL)

        self._vmutils.remove_vm_snapshot(self._FAKE_SNAPSHOT_PATH)

        mock_svc.DestroySnapshot.assert_called_with(self._FAKE_SNAPSHOT_PATH)

    def test_set_nic_connection(self):
        self._lookup_vm()

        self._vmutils._get_nic_data_by_name = mock.MagicMock()
        self._vmutils._add_virt_resource = mock.MagicMock()

        fake_eth_port = mock.MagicMock()
        self._vmutils._get_new_setting_data = mock.MagicMock(
            return_value=fake_eth_port)

        self._vmutils.set_nic_connection(self._FAKE_VM_NAME, None, None)

        self._vmutils._add_virt_resource.assert_called_with(fake_eth_port,
                                                            self._FAKE_VM_PATH)

    def test_add_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.AddResourceSettings.return_value = (self._FAKE_JOB_PATH,
                                                     mock.MagicMock(),
                                                     self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.GetText_.return_value = self._FAKE_RES_DATA

        self._vmutils._add_virt_resource(mock_res_setting_data,
                                         self._FAKE_VM_PATH)

        mock_svc.AddResourceSettings.assert_called_with(self._FAKE_VM_PATH,
                                                        [self._FAKE_RES_DATA])

    def test_modify_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.ModifyResourceSettings.return_value = (self._FAKE_JOB_PATH,
                                                        mock.MagicMock(),
                                                        self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.GetText_.return_value = self._FAKE_RES_DATA

        self._vmutils._modify_virt_resource(mock_res_setting_data,
                                            self._FAKE_VM_PATH)

        mock_svc.ModifyResourceSettings.assert_called_with(
            ResourceSettings=[self._FAKE_RES_DATA])

    def test_remove_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.RemoveResourceSettings.return_value = (self._FAKE_JOB_PATH,
                                                        self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.path_.return_value = self._FAKE_RES_PATH

        self._vmutils._remove_virt_resource(mock_res_setting_data,
                                            self._FAKE_VM_PATH)

        mock_svc.RemoveResourceSettings.assert_called_with(
            [self._FAKE_RES_PATH])

    @mock.patch('nova.virt.hyperv.vmutils.VMUtils._get_vm_disks')
    def test_enable_vm_metrics_collection(self, mock_get_vm_disks):
        self._lookup_vm()
        mock_svc = self._vmutils._conn.Msvm_MetricService()[0]

        metric_def = mock.MagicMock()
        mock_disk = mock.MagicMock()
        mock_disk.path_.return_value = self._FAKE_RES_PATH
        mock_get_vm_disks.return_value = ([mock_disk], [mock_disk])

        fake_metric_def_paths = ["fake_0", None]
        fake_metric_resource_paths = [self._FAKE_VM_PATH, self._FAKE_RES_PATH]

        metric_def.path_.side_effect = fake_metric_def_paths
        self._vmutils._conn.CIM_BaseMetricDefinition.return_value = [
            metric_def]

        self._vmutils.enable_vm_metrics_collection(self._FAKE_VM_NAME)

        calls = []
        for i in range(len(fake_metric_def_paths)):
            calls.append(mock.call(
                Subject=fake_metric_resource_paths[i],
                Definition=fake_metric_def_paths[i],
                MetricCollectionEnabled=self._vmutils._METRIC_ENABLED))

        mock_svc.ControlMetrics.assert_has_calls(calls, any_order=True)

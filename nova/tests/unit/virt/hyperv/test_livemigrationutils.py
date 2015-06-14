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

from nova import test
from nova.virt.hyperv import livemigrationutils


class LiveMigrationUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V LiveMigrationUtils class."""

    _FAKE_RET_VAL = 0

    _RESOURCE_TYPE_VHD = 31
    _RESOURCE_TYPE_DISK = 17
    _RESOURCE_SUB_TYPE_VHD = 'Microsoft:Hyper-V:Virtual Hard Disk'
    _RESOURCE_SUB_TYPE_DISK = 'Microsoft:Hyper-V:Physical Disk Drive'

    def setUp(self):
        self.liveutils = livemigrationutils.LiveMigrationUtils()
        self.liveutils._vmutils = mock.MagicMock()
        self.liveutils._volutils = mock.MagicMock()

        self._conn = mock.MagicMock()
        self.liveutils._get_conn_v2 = mock.MagicMock(return_value=self._conn)

        super(LiveMigrationUtilsTestCase, self).setUp()

    def test_check_live_migration_config(self):
        mock_migr_svc = self._conn.Msvm_VirtualSystemMigrationService()[0]

        vsmssd = mock.MagicMock()
        vsmssd.EnableVirtualSystemMigration = True
        mock_migr_svc.associators.return_value = [vsmssd]
        mock_migr_svc.MigrationServiceListenerIPAdressList.return_value = [
            mock.sentinel.FAKE_HOST]

        self.liveutils.check_live_migration_config()
        self.assertTrue(mock_migr_svc.associators.called)

    @mock.patch.object(livemigrationutils.LiveMigrationUtils,
                       '_destroy_planned_vm')
    def test_check_existing_planned_vm_found(self, mock_destroy_planned_vm):
        mock_vm = mock.MagicMock()
        mock_v2 = mock.MagicMock()
        mock_v2.Msvm_PlannedComputerSystem.return_value = [mock_vm]
        self.liveutils._check_existing_planned_vm(mock_v2, mock_vm)

        mock_destroy_planned_vm.assert_called_once_with(mock_v2, mock_vm)

    @mock.patch.object(livemigrationutils.LiveMigrationUtils,
                       '_destroy_planned_vm')
    def test_check_existing_planned_vm_none(self, mock_destroy_planned_vm):
        mock_v2 = mock.MagicMock()
        mock_v2.Msvm_PlannedComputerSystem.return_value = []
        self.liveutils._check_existing_planned_vm(mock_v2, mock.MagicMock())

        self.assertFalse(mock_destroy_planned_vm.called)

    def test_create_remote_planned_vm(self):
        mock_vsmsd = self._conn.query()[0]
        mock_vm = mock.MagicMock()
        mock_v2 = mock.MagicMock()
        mock_v2.Msvm_PlannedComputerSystem.return_value = [mock_vm]

        migr_svc = self._conn.Msvm_VirtualSystemMigrationService()[0]
        migr_svc.MigrateVirtualSystemToHost.return_value = (
            self._FAKE_RET_VAL, mock.sentinel.FAKE_JOB_PATH)

        resulted_vm = self.liveutils._create_remote_planned_vm(
            self._conn, mock_v2, mock_vm, [mock.sentinel.FAKE_REMOTE_IP_ADDR],
            mock.sentinel.FAKE_HOST)

        self.assertEqual(mock_vm, resulted_vm)

        migr_svc.MigrateVirtualSystemToHost.assert_called_once_with(
            ComputerSystem=mock_vm.path_.return_value,
            DestinationHost=mock.sentinel.FAKE_HOST,
            MigrationSettingData=mock_vsmsd.GetText_.return_value)

    def test_get_physical_disk_paths(self):
        ide_path = {mock.sentinel.IDE_PATH: mock.sentinel.IDE_HOST_RESOURCE}
        scsi_path = {mock.sentinel.SCSI_PATH: mock.sentinel.SCSI_HOST_RESOURCE}
        ide_ctrl = self.liveutils._vmutils.get_vm_ide_controller.return_value
        scsi_ctrl = self.liveutils._vmutils.get_vm_scsi_controller.return_value
        mock_get_controller_paths = (
            self.liveutils._vmutils.get_controller_volume_paths)

        mock_get_controller_paths.side_effect = [ide_path, scsi_path]

        result = self.liveutils._get_physical_disk_paths(mock.sentinel.VM_NAME)

        expected = dict(ide_path)
        expected.update(scsi_path)
        self.assertDictContainsSubset(expected, result)
        calls = [mock.call(ide_ctrl), mock.call(scsi_ctrl)]
        mock_get_controller_paths.assert_has_calls(calls)

    def test_get_physical_disk_paths_no_ide(self):
        scsi_path = {mock.sentinel.SCSI_PATH: mock.sentinel.SCSI_HOST_RESOURCE}
        scsi_ctrl = self.liveutils._vmutils.get_vm_scsi_controller.return_value
        mock_get_controller_paths = (
            self.liveutils._vmutils.get_controller_volume_paths)

        self.liveutils._vmutils.get_vm_ide_controller.return_value = None
        mock_get_controller_paths.return_value = scsi_path

        result = self.liveutils._get_physical_disk_paths(mock.sentinel.VM_NAME)

        self.assertEqual(scsi_path, result)
        mock_get_controller_paths.assert_called_once_with(scsi_ctrl)

    @mock.patch.object(livemigrationutils.volumeutilsv2, 'VolumeUtilsV2')
    def test_get_remote_disk_data(self, mock_vol_utils_class):
        mock_vol_utils_remote = mock_vol_utils_class.return_value
        mock_vm_utils = mock.MagicMock()
        disk_paths = {
            mock.sentinel.FAKE_RASD_PATH: mock.sentinel.FAKE_DISK_PATH}
        self.liveutils._volutils.get_target_from_disk_path.return_value = (
            mock.sentinel.FAKE_IQN, mock.sentinel.FAKE_LUN)
        mock_vol_utils_remote.get_device_number_for_target.return_value = (
            mock.sentinel.FAKE_DEV_NUM)
        mock_vm_utils.get_mounted_disk_by_drive_number.return_value = (
            mock.sentinel.FAKE_DISK_PATH)

        disk_paths = self.liveutils._get_remote_disk_data(
            mock_vm_utils, disk_paths, mock.sentinel.FAKE_HOST)

        self.liveutils._volutils.get_target_from_disk_path.assert_called_with(
            mock.sentinel.FAKE_DISK_PATH)
        mock_vol_utils_remote.get_device_number_for_target.assert_called_with(
            mock.sentinel.FAKE_IQN, mock.sentinel.FAKE_LUN)
        mock_vm_utils.get_mounted_disk_by_drive_number.assert_called_once_with(
            mock.sentinel.FAKE_DEV_NUM)

        self.assertEqual(
            {mock.sentinel.FAKE_RASD_PATH: mock.sentinel.FAKE_DISK_PATH},
            disk_paths)

    def test_update_planned_vm_disk_resources(self):
        mock_vm_utils = mock.MagicMock()

        self._prepare_vm_mocks(self._RESOURCE_TYPE_DISK,
                               self._RESOURCE_SUB_TYPE_DISK)
        mock_vm = self._conn.Msvm_ComputerSystem.return_value[0]
        sasd = mock_vm.associators()[0].associators()[0]

        mock_vsmsvc = self._conn.Msvm_VirtualSystemManagementService()[0]

        self.liveutils._update_planned_vm_disk_resources(
            mock_vm_utils, self._conn, mock_vm, mock.sentinel.FAKE_VM_NAME,
            {sasd.path.return_value.RelPath: mock.sentinel.FAKE_RASD_PATH})

        mock_vsmsvc.ModifyResourceSettings.assert_called_once_with(
            ResourceSettings=[sasd.GetText_.return_value])

    def test_get_vhd_setting_data(self):
        self._prepare_vm_mocks(self._RESOURCE_TYPE_VHD,
                               self._RESOURCE_SUB_TYPE_VHD)
        mock_vm = self._conn.Msvm_ComputerSystem.return_value[0]
        mock_sasd = mock_vm.associators()[0].associators()[0]

        vhd_sds = self.liveutils._get_vhd_setting_data(mock_vm)
        self.assertEqual([mock_sasd.GetText_.return_value], vhd_sds)

    def test_live_migrate_vm_helper(self):
        mock_conn_local = mock.MagicMock()
        mock_vm = mock.MagicMock()
        mock_vsmsd = mock_conn_local.query()[0]

        mock_vsmsvc = mock_conn_local.Msvm_VirtualSystemMigrationService()[0]
        mock_vsmsvc.MigrateVirtualSystemToHost.return_value = (
            self._FAKE_RET_VAL, mock.sentinel.FAKE_JOB_PATH)

        self.liveutils._live_migrate_vm(
            mock_conn_local, mock_vm, None,
            [mock.sentinel.FAKE_REMOTE_IP_ADDR],
            mock.sentinel.FAKE_RASD_PATH, mock.sentinel.FAKE_HOST)

        mock_vsmsvc.MigrateVirtualSystemToHost.assert_called_once_with(
            ComputerSystem=mock_vm.path_.return_value,
            DestinationHost=mock.sentinel.FAKE_HOST,
            MigrationSettingData=mock_vsmsd.GetText_.return_value,
            NewResourceSettingData=mock.sentinel.FAKE_RASD_PATH)

    @mock.patch.object(livemigrationutils, 'vmutilsv2')
    def test_live_migrate_vm(self, mock_vm_utils):
        mock_vm_utils_remote = mock_vm_utils.VMUtilsV2.return_value
        mock_vm = self._get_vm()

        mock_migr_svc = self._conn.Msvm_VirtualSystemMigrationService()[0]
        mock_migr_svc.MigrationServiceListenerIPAddressList = [
            mock.sentinel.FAKE_REMOTE_IP_ADDR]

        # patches, call and assertions.
        with mock.patch.multiple(
                self.liveutils,
                _destroy_planned_vm=mock.DEFAULT,
                _get_physical_disk_paths=mock.DEFAULT,
                _get_remote_disk_data=mock.DEFAULT,
                _create_remote_planned_vm=mock.DEFAULT,
                _update_planned_vm_disk_resources=mock.DEFAULT,
                _get_vhd_setting_data=mock.DEFAULT,
                _live_migrate_vm=mock.DEFAULT):

            disk_paths = {
                mock.sentinel.FAKE_IDE_PATH: mock.sentinel.FAKE_SASD_RESOURCE}
            self.liveutils._get_physical_disk_paths.return_value = disk_paths

            mock_disk_paths = [mock.sentinel.FAKE_DISK_PATH]
            self.liveutils._get_remote_disk_data.return_value = (
                mock_disk_paths)

            self.liveutils._create_remote_planned_vm.return_value = mock_vm

            self.liveutils.live_migrate_vm(mock.sentinel.FAKE_VM_NAME,
                                            mock.sentinel.FAKE_HOST)

            self.liveutils._get_remote_disk_data.assert_called_once_with(
                mock_vm_utils_remote, disk_paths, mock.sentinel.FAKE_HOST)

            self.liveutils._create_remote_planned_vm.assert_called_once_with(
                self._conn, self._conn, mock_vm,
                [mock.sentinel.FAKE_REMOTE_IP_ADDR], mock.sentinel.FAKE_HOST)

            mocked_method = self.liveutils._update_planned_vm_disk_resources
            mocked_method.assert_called_once_with(
                mock_vm_utils_remote, self._conn, mock_vm,
                mock.sentinel.FAKE_VM_NAME, mock_disk_paths)

            self.liveutils._live_migrate_vm.assert_called_once_with(
                self._conn, mock_vm, mock_vm,
                [mock.sentinel.FAKE_REMOTE_IP_ADDR],
                self.liveutils._get_vhd_setting_data.return_value,
                mock.sentinel.FAKE_HOST)

    def _prepare_vm_mocks(self, resource_type, resource_sub_type):
        mock_vm_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vm = self._get_vm()
        self._conn.Msvm_PlannedComputerSystem.return_value = [vm]
        mock_vm_svc.DestroySystem.return_value = (mock.sentinel.FAKE_JOB_PATH,
                                                  self._FAKE_RET_VAL)
        mock_vm_svc.ModifyResourceSettings.return_value = (
            None, mock.sentinel.FAKE_JOB_PATH, self._FAKE_RET_VAL)

        sasd = mock.MagicMock()
        other_sasd = mock.MagicMock()
        sasd.ResourceType = resource_type
        sasd.ResourceSubType = resource_sub_type
        sasd.HostResource = [mock.sentinel.FAKE_SASD_RESOURCE]
        sasd.path.return_value.RelPath = mock.sentinel.FAKE_DISK_PATH

        vm_settings = mock.MagicMock()
        vm.associators.return_value = [vm_settings]
        vm_settings.associators.return_value = [sasd, other_sasd]

    def _get_vm(self):
        mock_vm = mock.MagicMock()
        self._conn.Msvm_ComputerSystem.return_value = [mock_vm]
        mock_vm.path_.return_value = mock.sentinel.FAKE_VM_PATH
        return mock_vm

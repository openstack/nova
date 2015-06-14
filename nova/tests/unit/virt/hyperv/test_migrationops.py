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

import mock

from nova.tests.unit import fake_instance
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import migrationops
from nova.virt.hyperv import vmutils


class MigrationOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V MigrationOps class."""

    _FAKE_DISK = 'fake_disk'
    _FAKE_TIMEOUT = 10
    _FAKE_RETRY_INTERVAL = 5

    def setUp(self):
        super(MigrationOpsTestCase, self).setUp()
        self.context = 'fake-context'

        self._migrationops = migrationops.MigrationOps()
        self._migrationops._hostutils = mock.MagicMock()
        self._migrationops._vmops = mock.MagicMock()
        self._migrationops._vmutils = mock.MagicMock()
        self._migrationops._pathutils = mock.Mock()

    def _check_migrate_disk_files(self, host):
        instance_path = 'fake/instance/path'
        self._migrationops._pathutils.get_instance_dir.return_value = (
            instance_path)
        get_revert_dir = (
            self._migrationops._pathutils.get_instance_migr_revert_dir)
        self._migrationops._hostutils.get_local_ips.return_value = [host]
        self._migrationops._pathutils.exists.return_value = True

        expected_get_dir = [mock.call(mock.sentinel.instance_name)]
        expected_move_calls = [mock.call(instance_path,
                                         get_revert_dir.return_value)]

        self._migrationops._migrate_disk_files(
            instance_name=mock.sentinel.instance_name,
            disk_files=[self._FAKE_DISK],
            dest=mock.sentinel.dest_path)

        self._migrationops._hostutils.get_local_ips.assert_called_once_with()
        get_revert_dir.assert_called_with(mock.sentinel.instance_name,
                                          remove_dir=True, create_dir=True)
        if host == mock.sentinel.dest_path:
            fake_dest_path = '%s_tmp' % instance_path
            self._migrationops._pathutils.exists.assert_called_once_with(
                fake_dest_path)
            self._migrationops._pathutils.rmtree.assert_called_once_with(
                fake_dest_path)
            self._migrationops._pathutils.makedirs.assert_called_once_with(
                fake_dest_path)
            expected_move_calls.append(mock.call(fake_dest_path,
                                                 instance_path))
        else:
            fake_dest_path = instance_path
            expected_get_dir.append(mock.call(mock.sentinel.instance_name,
                                              mock.sentinel.dest_path,
                                              remove_dir=True))
        self._migrationops._pathutils.get_instance_dir.assert_has_calls(
            expected_get_dir)
        self._migrationops._pathutils.copy.assert_called_once_with(
            self._FAKE_DISK, fake_dest_path)
        self._migrationops._pathutils.move_folder_files.assert_has_calls(
            expected_move_calls)

    def test_migrate_disk_files(self):
        self._check_migrate_disk_files(host=mock.sentinel.other_dest_path)

    def test_migrate_disk_files_same_host(self):
        self._check_migrate_disk_files(host=mock.sentinel.dest_path)

    @mock.patch.object(migrationops.MigrationOps,
                       '_cleanup_failed_disk_migration')
    def test_migrate_disk_files_exception(self, mock_cleanup):
        instance_path = 'fake/instance/path'
        fake_dest_path = '%s_tmp' % instance_path
        self._migrationops._pathutils.get_instance_dir.return_value = (
            instance_path)
        get_revert_dir = (
            self._migrationops._pathutils.get_instance_migr_revert_dir)
        self._migrationops._hostutils.get_local_ips.return_value = [
            mock.sentinel.dest_path]
        self._migrationops._pathutils.copy.side_effect = IOError(
            "Expected exception.")

        self.assertRaises(IOError, self._migrationops._migrate_disk_files,
                          instance_name=mock.sentinel.instance_name,
                          disk_files=[self._FAKE_DISK],
                          dest=mock.sentinel.dest_path)
        mock_cleanup.assert_called_once_with(instance_path,
                                             get_revert_dir.return_value,
                                             fake_dest_path)

    def test_check_and_attach_config_drive_unknown_path(self):
        instance = fake_instance.fake_instance_obj(self.context,
            expected_attrs=['system_metadata'])
        instance.config_drive = 'True'
        self._migrationops._pathutils.lookup_configdrive_path.return_value = (
            None)
        self.assertRaises(vmutils.HyperVException,
                          self._migrationops._check_and_attach_config_drive,
                          instance,
                          mock.sentinel.FAKE_VM_GEN)

    @mock.patch.object(migrationops.MigrationOps, '_migrate_disk_files')
    @mock.patch.object(migrationops.MigrationOps, '_check_target_flavor')
    def test_migrate_disk_and_power_off(self, mock_check_flavor,
                                        mock_migrate_disk_files):
        instance = fake_instance.fake_instance_obj(self.context)
        flavor = mock.MagicMock()
        network_info = mock.MagicMock()

        disk_files = [mock.MagicMock()]
        volume_drives = [mock.MagicMock()]

        mock_get_vm_st_path = self._migrationops._vmutils.get_vm_storage_paths
        mock_get_vm_st_path.return_value = (disk_files, volume_drives)

        self._migrationops.migrate_disk_and_power_off(
            self.context, instance, mock.sentinel.FAKE_DEST, flavor,
            network_info, None, self._FAKE_TIMEOUT, self._FAKE_RETRY_INTERVAL)

        mock_check_flavor.assert_called_once_with(instance, flavor)
        self._migrationops._vmops.power_off.assert_called_once_with(
            instance, self._FAKE_TIMEOUT, self._FAKE_RETRY_INTERVAL)
        mock_get_vm_st_path.assert_called_once_with(instance.name)
        mock_migrate_disk_files.assert_called_once_with(
            instance.name, disk_files, mock.sentinel.FAKE_DEST)
        self._migrationops._vmops.destroy.assert_called_once_with(
            instance, destroy_disks=False)

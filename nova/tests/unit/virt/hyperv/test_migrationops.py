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

import os

import mock
from oslo_utils import units

from nova import exception
from nova import objects
from nova import test
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
        self._migrationops._vhdutils = mock.MagicMock()
        self._migrationops._pathutils = mock.MagicMock()
        self._migrationops._volumeops = mock.MagicMock()
        self._migrationops._imagecache = mock.MagicMock()

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

    def test_cleanup_failed_disk_migration(self):
        self._migrationops._pathutils.exists.return_value = True

        self._migrationops._cleanup_failed_disk_migration(
            instance_path=mock.sentinel.instance_path,
            revert_path=mock.sentinel.revert_path,
            dest_path=mock.sentinel.dest_path)

        expected = [mock.call(mock.sentinel.dest_path),
                    mock.call(mock.sentinel.revert_path)]
        self._migrationops._pathutils.exists.assert_has_calls(expected)
        self._migrationops._pathutils.rmtree.assert_called_once_with(
            mock.sentinel.dest_path)
        self._migrationops._pathutils.rename.assert_called_once_with(
            mock.sentinel.revert_path, mock.sentinel.instance_path)

    def test_check_target_flavor(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_instance.root_gb = 1
        mock_flavor = mock.MagicMock(root_gb=0)
        self.assertRaises(exception.InstanceFaultRollback,
                          self._migrationops._check_target_flavor,
                          mock_instance, mock_flavor)

    def test_check_and_attach_config_drive(self):
        mock_instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        mock_instance.config_drive = 'True'

        self._migrationops._check_and_attach_config_drive(
            mock_instance, mock.sentinel.vm_gen)

        self._migrationops._vmops.attach_config_drive.assert_called_once_with(
            mock_instance,
            self._migrationops._pathutils.lookup_configdrive_path.return_value,
            mock.sentinel.vm_gen)

    def test_check_and_attach_config_drive_unknown_path(self):
        instance = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        instance.config_drive = 'True'
        self._migrationops._pathutils.lookup_configdrive_path.return_value = (
            None)
        self.assertRaises(exception.ConfigDriveNotFound,
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

    def test_confirm_migration(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._migrationops.confirm_migration(
            migration=mock.sentinel.migration, instance=mock_instance,
            network_info=mock.sentinel.network_info)
        get_instance_migr_revert_dir = (
            self._migrationops._pathutils.get_instance_migr_revert_dir)
        get_instance_migr_revert_dir.assert_called_with(mock_instance.name,
                                                        remove_dir=True)

    def test_revert_migration_files(self):
        instance_path = (
            self._migrationops._pathutils.get_instance_dir.return_value)
        get_revert_dir = (
            self._migrationops._pathutils.get_instance_migr_revert_dir)

        self._migrationops._revert_migration_files(
            instance_name=mock.sentinel.instance_name)

        self._migrationops._pathutils.get_instance_dir.assert_called_once_with(
            mock.sentinel.instance_name, create_dir=False, remove_dir=True)
        get_revert_dir.assert_called_with(mock.sentinel.instance_name)
        self._migrationops._pathutils.rename.assert_called_once_with(
            get_revert_dir.return_value, instance_path)

    @mock.patch.object(migrationops.MigrationOps,
                       '_check_and_attach_config_drive')
    @mock.patch.object(migrationops.MigrationOps, '_revert_migration_files')
    @mock.patch.object(objects.ImageMeta, "from_instance")
    def _check_finish_revert_migration(self, mock_image,
                                       mock_revert_migration_files,
                                       mock_check_attach_config_drive,
                                       boot_from_volume=False):
        mock_image.return_value = objects.ImageMeta.from_dict({})
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_ebs_root_in_block_devices = (
            self._migrationops._volumeops.ebs_root_in_block_devices)
        mock_ebs_root_in_block_devices.return_value = boot_from_volume
        lookup_ephemeral = (
            self._migrationops._pathutils.lookup_ephemeral_vhd_path)

        self._migrationops.finish_revert_migration(
            context=self.context, instance=mock_instance,
            network_info=mock.sentinel.network_info,
            block_device_info=mock.sentinel.block_device,
            power_on=True)

        mock_revert_migration_files.assert_called_once_with(
            mock_instance.name)
        mock_ebs_root_in_block_devices.assert_called_once_with(
            mock.sentinel.block_device)
        if not boot_from_volume:
            lookup_root_vhd = (
                self._migrationops._pathutils.lookup_root_vhd_path)
            lookup_root_vhd.assert_called_once_with(mock_instance.name)
            fake_root_path = lookup_root_vhd.return_value
        else:
            fake_root_path = None

        lookup_ephemeral.assert_called_with(mock_instance.name)
        get_image_vm_gen = self._migrationops._vmops.get_image_vm_generation
        get_image_vm_gen.assert_called_once_with(
            mock_instance.uuid, fake_root_path,
            test.MatchType(objects.ImageMeta))
        self._migrationops._vmops.create_instance.assert_called_once_with(
            mock_instance, mock.sentinel.network_info,
            mock.sentinel.block_device, fake_root_path,
            lookup_ephemeral.return_value, get_image_vm_gen.return_value)
        mock_check_attach_config_drive.assert_called_once_with(
            mock_instance, get_image_vm_gen.return_value)
        self._migrationops._vmops.power_on.assert_called_once_with(
            mock_instance)

    def test_finish_revert_migration_boot_from_volume(self):
        self._check_finish_revert_migration(boot_from_volume=True)

    def test_finish_revert_migration_not_in_block_device(self):
        self._check_finish_revert_migration()

    def test_merge_base_vhd(self):
        fake_diff_vhd_path = 'fake/diff/path'
        fake_base_vhd_path = 'fake/base/path'
        base_vhd_copy_path = os.path.join(
            os.path.dirname(fake_diff_vhd_path),
            os.path.basename(fake_base_vhd_path))

        self._migrationops._merge_base_vhd(diff_vhd_path=fake_diff_vhd_path,
                                           base_vhd_path=fake_base_vhd_path)

        self._migrationops._pathutils.copyfile.assert_called_once_with(
            fake_base_vhd_path, base_vhd_copy_path)
        recon_parent_vhd = self._migrationops._vhdutils.reconnect_parent_vhd
        recon_parent_vhd.assert_called_once_with(fake_diff_vhd_path,
                                                 base_vhd_copy_path)
        self._migrationops._vhdutils.merge_vhd.assert_called_once_with(
            fake_diff_vhd_path, base_vhd_copy_path)
        self._migrationops._pathutils.rename.assert_called_once_with(
            base_vhd_copy_path, fake_diff_vhd_path)

    def test_merge_base_vhd_exception(self):
        fake_diff_vhd_path = 'fake/diff/path'
        fake_base_vhd_path = 'fake/base/path'
        base_vhd_copy_path = os.path.join(
            os.path.dirname(fake_diff_vhd_path),
            os.path.basename(fake_base_vhd_path))

        self._migrationops._vhdutils.reconnect_parent_vhd.side_effect = (
            vmutils.HyperVException)
        self._migrationops._pathutils.exists.return_value = True

        self.assertRaises(vmutils.HyperVException,
                          self._migrationops._merge_base_vhd,
                          fake_diff_vhd_path, fake_base_vhd_path)
        self._migrationops._pathutils.exists.assert_called_once_with(
            base_vhd_copy_path)
        self._migrationops._pathutils.remove.assert_called_once_with(
            base_vhd_copy_path)

    @mock.patch.object(migrationops.MigrationOps, '_resize_vhd')
    def test_check_resize_vhd(self, mock_resize_vhd):
        self._migrationops._check_resize_vhd(
            vhd_path=mock.sentinel.vhd_path, vhd_info={'MaxInternalSize': 1},
            new_size=2)
        mock_resize_vhd.assert_called_once_with(mock.sentinel.vhd_path, 2)

    def test_check_resize_vhd_exception(self):
        self.assertRaises(exception.CannotResizeDisk,
                          self._migrationops._check_resize_vhd,
                          mock.sentinel.vhd_path,
                          {'MaxInternalSize': 1}, 0)

    @mock.patch.object(migrationops.MigrationOps, '_merge_base_vhd')
    def test_resize_vhd(self, mock_merge_base_vhd):
        fake_vhd_path = 'fake/path.vhd'
        new_vhd_size = 2
        self._migrationops._resize_vhd(vhd_path=fake_vhd_path,
                                       new_size=new_vhd_size)

        get_vhd_parent_path = self._migrationops._vhdutils.get_vhd_parent_path
        get_vhd_parent_path.assert_called_once_with(fake_vhd_path)
        mock_merge_base_vhd.assert_called_once_with(
            fake_vhd_path,
            self._migrationops._vhdutils.get_vhd_parent_path.return_value)
        self._migrationops._vhdutils.resize_vhd.assert_called_once_with(
            fake_vhd_path, new_vhd_size)

    def test_check_base_disk(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        fake_src_vhd_path = 'fake/src/path'
        fake_base_vhd = 'fake/vhd'
        get_cached_image = self._migrationops._imagecache.get_cached_image
        get_cached_image.return_value = fake_base_vhd

        self._migrationops._check_base_disk(
            context=self.context, instance=mock_instance,
            diff_vhd_path=mock.sentinel.diff_vhd_path,
            src_base_disk_path=fake_src_vhd_path)

        get_cached_image.assert_called_once_with(self.context, mock_instance)
        recon_parent_vhd = self._migrationops._vhdutils.reconnect_parent_vhd
        recon_parent_vhd.assert_called_once_with(
            mock.sentinel.diff_vhd_path, fake_base_vhd)

    @mock.patch.object(migrationops.MigrationOps,
                       '_check_and_attach_config_drive')
    @mock.patch.object(migrationops.MigrationOps, '_check_base_disk')
    @mock.patch.object(migrationops.MigrationOps, '_check_resize_vhd')
    def _check_finish_migration(self, mock_check_resize_vhd,
                                mock_check_base_disk,
                                mock_check_attach_config_drive,
                                ephemeral_path=None,
                                boot_from_volume=False):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_instance.ephemeral_gb = 1
        mock_vhd_info = mock.MagicMock()
        mock_eph_info = mock.MagicMock()
        lookup_root_vhd = self._migrationops._pathutils.lookup_root_vhd_path
        side_effect = [mock_eph_info] if boot_from_volume else [mock_vhd_info,
                                                                mock_eph_info]
        mock_ebs_root_in_block_devices = (
            self._migrationops._volumeops.ebs_root_in_block_devices)
        mock_ebs_root_in_block_devices.return_value = boot_from_volume
        self._migrationops._vhdutils.get_vhd_info.side_effect = side_effect
        look_up_ephem = self._migrationops._pathutils.lookup_ephemeral_vhd_path
        look_up_ephem.return_value = ephemeral_path
        expected_check_resize = []
        expected_get_info = []

        self._migrationops.finish_migration(
            context=self.context, migration=mock.sentinel.migration,
            instance=mock_instance, disk_info=mock.sentinel.disk_info,
            network_info=mock.sentinel.network_info,
            image_meta=mock.sentinel.image_meta, resize_instance=True)

        mock_ebs_root_in_block_devices.assert_called_once_with(None)
        if not boot_from_volume:
            root_vhd_path = lookup_root_vhd.return_value
            lookup_root_vhd.assert_called_with(mock_instance.name)
            expected_get_info = [mock.call(root_vhd_path)]
            mock_vhd_info.get.assert_called_once_with("ParentPath")
            mock_check_base_disk.assert_called_once_with(
                self.context, mock_instance, root_vhd_path,
                mock_vhd_info.get.return_value)
            expected_check_resize.append(
                mock.call(root_vhd_path, mock_vhd_info,
                          mock_instance.root_gb * units.Gi))
        else:
            root_vhd_path = None

        look_up_ephem.assert_called_once_with(mock_instance.name)
        if ephemeral_path is None:
            create_eph_vhd = self._migrationops._vmops.create_ephemeral_vhd
            create_eph_vhd.assert_called_once_with(mock_instance)
            ephemeral_path = create_eph_vhd.return_value
        else:
            expected_get_info.append(mock.call(ephemeral_path))
            expected_check_resize.append(
                mock.call(ephemeral_path, mock_eph_info,
                          mock_instance.ephemeral_gb * units.Gi))

        mock_check_resize_vhd.assert_has_calls(expected_check_resize)
        self._migrationops._vhdutils.get_vhd_info.assert_has_calls(
            expected_get_info)
        get_image_vm_gen = self._migrationops._vmops.get_image_vm_generation
        get_image_vm_gen.assert_called_once_with(mock_instance.uuid,
                                                 root_vhd_path,
                                                 mock.sentinel.image_meta)
        self._migrationops._vmops.create_instance.assert_called_once_with(
            mock_instance, mock.sentinel.network_info, None, root_vhd_path,
            ephemeral_path, get_image_vm_gen.return_value)
        mock_check_attach_config_drive.assert_called_once_with(
            mock_instance, get_image_vm_gen.return_value)
        self._migrationops._vmops.power_on.assert_called_once_with(
            mock_instance)

    def test_finish_migration(self):
        self._check_finish_migration(
            ephemeral_path=mock.sentinel.ephemeral_path)

    def test_finish_migration_boot_from_volume(self):
        self._check_finish_migration(
            ephemeral_path=mock.sentinel.ephemeral_path,
            boot_from_volume=True)

    def test_finish_migration_no_ephemeral(self):
        self._check_finish_migration()

    def test_finish_migration_no_root(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_ebs_root_in_block_devices = (
            self._migrationops._volumeops.ebs_root_in_block_devices)
        mock_ebs_root_in_block_devices.return_value = False
        self._migrationops._pathutils.lookup_root_vhd_path.return_value = None

        self.assertRaises(exception.DiskNotFound,
                          self._migrationops.finish_migration,
                          self.context, mock.sentinel.migration,
                          mock_instance, mock.sentinel.disk_info,
                          mock.sentinel.network_info,
                          mock.sentinel.image_meta, True, None, True)

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
from os_win import exceptions as os_win_exc
from oslo_config import cfg

from nova.tests.unit import fake_instance
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import livemigrationops
from nova.virt.hyperv import serialconsoleops

CONF = cfg.CONF


class LiveMigrationOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V LiveMigrationOps class."""

    def setUp(self):
        super(LiveMigrationOpsTestCase, self).setUp()
        self.context = 'fake_context'
        self._livemigrops = livemigrationops.LiveMigrationOps()
        self._livemigrops._livemigrutils = mock.MagicMock()
        self._livemigrops._pathutils = mock.MagicMock()

    @mock.patch.object(serialconsoleops.SerialConsoleOps,
                       'stop_console_handler')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.copy_vm_dvd_disks')
    def _test_live_migration(self, mock_get_vm_dvd_paths,
                             mock_stop_console_handler, side_effect):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_post = mock.MagicMock()
        mock_recover = mock.MagicMock()
        mock_copy_logs = self._livemigrops._pathutils.copy_vm_console_logs
        fake_dest = mock.sentinel.DESTINATION
        self._livemigrops._livemigrutils.live_migrate_vm.side_effect = [
            side_effect]
        if side_effect is os_win_exc.HyperVException:
            self.assertRaises(os_win_exc.HyperVException,
                              self._livemigrops.live_migration,
                              self.context, mock_instance, fake_dest,
                              mock_post, mock_recover, False, None)
            mock_recover.assert_called_once_with(self.context, mock_instance,
                                                 fake_dest, False)
        else:
            self._livemigrops.live_migration(context=self.context,
                                             instance_ref=mock_instance,
                                             dest=fake_dest,
                                             post_method=mock_post,
                                             recover_method=mock_recover)

            mock_stop_console_handler.assert_called_once_with(
                mock_instance.name)
            mock_copy_logs.assert_called_once_with(mock_instance.name,
                                                   fake_dest)
            mock_live_migr = self._livemigrops._livemigrutils.live_migrate_vm
            mock_live_migr.assert_called_once_with(mock_instance.name,
                                                   fake_dest)
            mock_post.assert_called_once_with(self.context, mock_instance,
                                              fake_dest, False)

    def test_live_migration(self):
        self._test_live_migration(side_effect=None)

    def test_live_migration_exception(self):
        self._test_live_migration(side_effect=os_win_exc.HyperVException)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps.get_disk_path_mapping')
    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps'
                '.ebs_root_in_block_devices')
    @mock.patch('nova.virt.hyperv.imagecache.ImageCache.get_cached_image')
    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps'
                '.initialize_volumes_connection')
    def _test_pre_live_migration(self, mock_initialize_connection,
                                 mock_get_cached_image,
                                 mock_ebs_root_in_block_devices,
                                 mock_get_disk_path_mapping,
                                 phys_disks_attached=True):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_instance.image_ref = "fake_image_ref"
        mock_ebs_root_in_block_devices.return_value = None
        mock_get_disk_path_mapping.return_value = (
            mock.sentinel.disk_path_mapping if phys_disks_attached
            else None)
        CONF.set_override('use_cow_images', True)
        self._livemigrops.pre_live_migration(
            self.context, mock_instance,
            block_device_info=mock.sentinel.BLOCK_INFO,
            network_info=mock.sentinel.NET_INFO)

        check_config = (
            self._livemigrops._livemigrutils.check_live_migration_config)
        check_config.assert_called_once_with()
        mock_ebs_root_in_block_devices.assert_called_once_with(
            mock.sentinel.BLOCK_INFO)
        mock_get_cached_image.assert_called_once_with(self.context,
                                                      mock_instance)
        mock_initialize_connection.assert_called_once_with(
            mock.sentinel.BLOCK_INFO)
        mock_get_disk_path_mapping.assert_called_once_with(
            mock.sentinel.BLOCK_INFO)
        if phys_disks_attached:
            livemigrutils = self._livemigrops._livemigrutils
            livemigrutils.create_planned_vm.assert_called_once_with(
                mock_instance.name,
                mock_instance.host,
                mock.sentinel.disk_path_mapping)

    def test_pre_live_migration(self):
        self._test_pre_live_migration()

    def test_pre_live_migration_invalid_disk_mapping(self):
        self._test_pre_live_migration(phys_disks_attached=False)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps.disconnect_volumes')
    def test_post_live_migration(self, mock_disconnect_volumes):
        self._livemigrops.post_live_migration(
            self.context, mock.sentinel.instance,
            mock.sentinel.block_device_info)
        mock_disconnect_volumes.assert_called_once_with(
            mock.sentinel.block_device_info)
        self._livemigrops._pathutils.get_instance_dir.assert_called_once_with(
            mock.sentinel.instance.name, create_dir=False, remove_dir=True)

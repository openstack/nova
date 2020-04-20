# Copyright 2015 Cloudbase Solutions SRL
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

"""
Unit tests for the Hyper-V Driver.
"""

import platform
import sys

import mock
from os_win import exceptions as os_win_exc

from nova import exception
from nova import safe_utils
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.hyperv import test_base
from nova.virt import driver as base_driver
from nova.virt.hyperv import driver


class HyperVDriverTestCase(test_base.HyperVBaseTestCase):

    FAKE_WIN_2008R2_VERSION = '6.0.0'

    @mock.patch.object(driver.HyperVDriver, '_check_minimum_windows_version')
    def setUp(self, mock_check_minimum_windows_version):
        super(HyperVDriverTestCase, self).setUp()

        self.context = 'context'
        self.driver = driver.HyperVDriver(mock.sentinel.virtapi)
        self.driver._hostops = mock.MagicMock()
        self.driver._volumeops = mock.MagicMock()
        self.driver._vmops = mock.MagicMock()
        self.driver._snapshotops = mock.MagicMock()
        self.driver._livemigrationops = mock.MagicMock()
        self.driver._migrationops = mock.MagicMock()
        self.driver._rdpconsoleops = mock.MagicMock()
        self.driver._serialconsoleops = mock.MagicMock()
        self.driver._imagecache = mock.MagicMock()

    @mock.patch.object(driver.LOG, 'warning')
    @mock.patch.object(driver.utilsfactory, 'get_hostutils')
    def test_check_minimum_windows_version(self, mock_get_hostutils,
                                           mock_warning):
        mock_hostutils = mock_get_hostutils.return_value
        mock_hostutils.check_min_windows_version.return_value = False

        self.assertRaises(exception.HypervisorTooOld,
                          self.driver._check_minimum_windows_version)

        mock_hostutils.check_min_windows_version.side_effect = [True, False]

        self.driver._check_minimum_windows_version()
        self.assertTrue(mock_warning.called)

    def test_public_api_signatures(self):
        # NOTE(claudiub): wrapped functions do not keep the same signature in
        # Python 2.7, which causes this test to fail. Instead, we should
        # compare the public API signatures of the unwrapped methods.

        for attr in driver.HyperVDriver.__dict__:
            class_member = getattr(driver.HyperVDriver, attr)
            if callable(class_member):
                mocked_method = mock.patch.object(
                    driver.HyperVDriver, attr,
                    safe_utils.get_wrapped_function(class_member))
                mocked_method.start()
                self.addCleanup(mocked_method.stop)

        self.assertPublicAPISignatures(base_driver.ComputeDriver,
                                       driver.HyperVDriver)

    def test_converted_exception(self):
        self.driver._vmops.get_info.side_effect = (
            os_win_exc.OSWinException)
        self.assertRaises(exception.NovaException,
                          self.driver.get_info, mock.sentinel.instance)

        self.driver._vmops.get_info.side_effect = os_win_exc.HyperVException
        self.assertRaises(exception.NovaException,
                          self.driver.get_info, mock.sentinel.instance)

        self.driver._vmops.get_info.side_effect = (
            os_win_exc.HyperVVMNotFoundException(vm_name='foofoo'))
        self.assertRaises(exception.InstanceNotFound,
                          self.driver.get_info, mock.sentinel.instance)

    def test_assert_original_traceback_maintained(self):
        def bar(self):
            foo = "foofoo"
            raise os_win_exc.HyperVVMNotFoundException(vm_name=foo)

        self.driver._vmops.get_info.side_effect = bar
        try:
            self.driver.get_info(mock.sentinel.instance)
            self.fail("Test expected exception, but it was not raised.")
        except exception.InstanceNotFound:
            # exception has been raised as expected.
            _, _, trace = sys.exc_info()
            while trace.tb_next:
                # iterate until the original exception source, bar.
                trace = trace.tb_next

            # original frame will contain the 'foo' variable.
            self.assertEqual('foofoo', trace.tb_frame.f_locals['foo'])

    @mock.patch.object(driver.eventhandler, 'InstanceEventHandler')
    def test_init_host(self, mock_InstanceEventHandler):
        self.driver.init_host(mock.sentinel.host)

        mock_start_console_handlers = (
            self.driver._serialconsoleops.start_console_handlers)
        mock_start_console_handlers.assert_called_once_with()
        mock_InstanceEventHandler.assert_called_once_with(
            state_change_callback=self.driver.emit_event)
        fake_event_handler = mock_InstanceEventHandler.return_value
        fake_event_handler.start_listener.assert_called_once_with()

    def test_list_instance_uuids(self):
        self.driver.list_instance_uuids()
        self.driver._vmops.list_instance_uuids.assert_called_once_with()

    def test_list_instances(self):
        self.driver.list_instances()
        self.driver._vmops.list_instances.assert_called_once_with()

    def test_spawn(self):
        self.driver.spawn(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.image_meta, mock.sentinel.injected_files,
            mock.sentinel.admin_password, mock.sentinel.allocations,
            mock.sentinel.network_info, mock.sentinel.block_device_info)

        self.driver._vmops.spawn.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.image_meta, mock.sentinel.injected_files,
            mock.sentinel.admin_password, mock.sentinel.network_info,
            mock.sentinel.block_device_info)

    def test_reboot(self):
        self.driver.reboot(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.reboot_type,
            mock.sentinel.block_device_info, mock.sentinel.bad_vol_callback)

        self.driver._vmops.reboot.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info,
            mock.sentinel.reboot_type)

    def test_destroy(self):
        self.driver.destroy(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info,
            mock.sentinel.destroy_disks)

        self.driver._vmops.destroy.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info,
            mock.sentinel.block_device_info, mock.sentinel.destroy_disks)

    def test_cleanup(self):
        self.driver.cleanup(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info,
            mock.sentinel.destroy_disks, mock.sentinel.migrate_data,
            mock.sentinel.destroy_vifs)

        self.driver._vmops.unplug_vifs.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info)

    def test_get_info(self):
        self.driver.get_info(mock.sentinel.instance)
        self.driver._vmops.get_info.assert_called_once_with(
            mock.sentinel.instance)

    def test_attach_volume(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.driver.attach_volume(
            mock.sentinel.context, mock.sentinel.connection_info,
            mock_instance, mock.sentinel.mountpoint, mock.sentinel.disk_bus,
            mock.sentinel.device_type, mock.sentinel.encryption)

        self.driver._volumeops.attach_volume.assert_called_once_with(
            mock.sentinel.connection_info,
            mock_instance.name)

    def test_detach_volume(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.driver.detach_volume(
            mock.sentinel.context, mock.sentinel.connection_info,
            mock_instance, mock.sentinel.mountpoint, mock.sentinel.encryption)

        self.driver._volumeops.detach_volume.assert_called_once_with(
            mock.sentinel.connection_info,
            mock_instance.name)

    def test_get_volume_connector(self):
        self.driver.get_volume_connector(mock.sentinel.instance)
        self.driver._volumeops.get_volume_connector.assert_called_once_with()

    def test_get_available_resource(self):
        self.driver.get_available_resource(mock.sentinel.nodename)
        self.driver._hostops.get_available_resource.assert_called_once_with()

    def test_get_available_nodes(self):
        response = self.driver.get_available_nodes(mock.sentinel.refresh)
        self.assertEqual([platform.node()], response)

    def test_host_power_action(self):
        self.driver.host_power_action(mock.sentinel.action)
        self.driver._hostops.host_power_action.assert_called_once_with(
            mock.sentinel.action)

    def test_snapshot(self):
        self.driver.snapshot(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.image_id, mock.sentinel.update_task_state)

        self.driver._snapshotops.snapshot.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.image_id, mock.sentinel.update_task_state)

    def test_pause(self):
        self.driver.pause(mock.sentinel.instance)
        self.driver._vmops.pause.assert_called_once_with(
            mock.sentinel.instance)

    def test_unpause(self):
        self.driver.unpause(mock.sentinel.instance)
        self.driver._vmops.unpause.assert_called_once_with(
            mock.sentinel.instance)

    def test_suspend(self):
        self.driver.suspend(mock.sentinel.context, mock.sentinel.instance)
        self.driver._vmops.suspend.assert_called_once_with(
            mock.sentinel.instance)

    def test_resume(self):
        self.driver.resume(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info)

        self.driver._vmops.resume.assert_called_once_with(
            mock.sentinel.instance)

    def test_power_off(self):
        self.driver.power_off(
            mock.sentinel.instance, mock.sentinel.timeout,
            mock.sentinel.retry_interval)

        self.driver._vmops.power_off.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.timeout,
            mock.sentinel.retry_interval)

    def test_power_on(self):
        self.driver.power_on(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info)

        self.driver._vmops.power_on.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.block_device_info,
            mock.sentinel.network_info)

    def test_resume_state_on_host_boot(self):
        self.driver.resume_state_on_host_boot(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info)

        self.driver._vmops.resume_state_on_host_boot.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info)

    def test_live_migration(self):
        self.driver.live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest, mock.sentinel.post_method,
            mock.sentinel.recover_method, mock.sentinel.block_migration,
            mock.sentinel.migrate_data)

        self.driver._livemigrationops.live_migration.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest, mock.sentinel.post_method,
            mock.sentinel.recover_method, mock.sentinel.block_migration,
            mock.sentinel.migrate_data)

    @mock.patch.object(driver.HyperVDriver, 'destroy')
    def test_rollback_live_migration_at_destination(self, mock_destroy):
        self.driver.rollback_live_migration_at_destination(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info,
            mock.sentinel.destroy_disks, mock.sentinel.migrate_data)

        mock_destroy.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info,
            destroy_disks=mock.sentinel.destroy_disks)

    def test_pre_live_migration(self):
        migrate_data = self.driver.pre_live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info, mock.sentinel.network_info,
            mock.sentinel.disk_info, mock.sentinel.migrate_data)

        self.assertEqual(mock.sentinel.migrate_data, migrate_data)
        pre_live_migration = self.driver._livemigrationops.pre_live_migration
        pre_live_migration.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info, mock.sentinel.network_info)

    def test_post_live_migration(self):
        self.driver.post_live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info, mock.sentinel.migrate_data)

        post_live_migration = self.driver._livemigrationops.post_live_migration
        post_live_migration.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info,
            mock.sentinel.migrate_data)

    def test_post_live_migration_at_destination(self):
        self.driver.post_live_migration_at_destination(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_migration,
            mock.sentinel.block_device_info)

        mtd = self.driver._livemigrationops.post_live_migration_at_destination
        mtd.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_migration)

    def test_check_can_live_migrate_destination(self):
        self.driver.check_can_live_migrate_destination(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.src_compute_info, mock.sentinel.dst_compute_info,
            mock.sentinel.block_migration, mock.sentinel.disk_over_commit)

        mtd = self.driver._livemigrationops.check_can_live_migrate_destination
        mtd.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.src_compute_info, mock.sentinel.dst_compute_info,
            mock.sentinel.block_migration, mock.sentinel.disk_over_commit)

    def test_cleanup_live_migration_destination_check(self):
        self.driver.cleanup_live_migration_destination_check(
            mock.sentinel.context, mock.sentinel.dest_check_data)

        _livemigrops = self.driver._livemigrationops
        method = _livemigrops.cleanup_live_migration_destination_check
        method.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.dest_check_data)

    def test_check_can_live_migrate_source(self):
        self.driver.check_can_live_migrate_source(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest_check_data, mock.sentinel.block_device_info)

        method = self.driver._livemigrationops.check_can_live_migrate_source
        method.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest_check_data)

    def test_plug_vifs(self):
        self.driver.plug_vifs(
            mock.sentinel.instance, mock.sentinel.network_info)

        self.driver._vmops.plug_vifs.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info)

    def test_unplug_vifs(self):
        self.driver.unplug_vifs(
            mock.sentinel.instance, mock.sentinel.network_info)

        self.driver._vmops.unplug_vifs.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info)

    def test_migrate_disk_and_power_off(self):
        self.driver.migrate_disk_and_power_off(
            mock.sentinel.context, mock.sentinel.instance, mock.sentinel.dest,
            mock.sentinel.flavor, mock.sentinel.network_info,
            mock.sentinel.block_device_info, mock.sentinel.timeout,
            mock.sentinel.retry_interval)

        migr_power_off = self.driver._migrationops.migrate_disk_and_power_off
        migr_power_off.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance, mock.sentinel.dest,
            mock.sentinel.flavor, mock.sentinel.network_info,
            mock.sentinel.block_device_info, mock.sentinel.timeout,
            mock.sentinel.retry_interval)

    def test_confirm_migration(self):
        self.driver.confirm_migration(
            mock.sentinel.context,
            mock.sentinel.migration, mock.sentinel.instance,
            mock.sentinel.network_info)

        self.driver._migrationops.confirm_migration.assert_called_once_with(
            mock.sentinel.context,
            mock.sentinel.migration, mock.sentinel.instance,
            mock.sentinel.network_info)

    def test_finish_revert_migration(self):
        self.driver.finish_revert_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.migration,
            mock.sentinel.block_device_info, mock.sentinel.power_on)

        finish_revert_migr = self.driver._migrationops.finish_revert_migration
        finish_revert_migr.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info, mock.sentinel.block_device_info,
            mock.sentinel.power_on)

    def test_finish_migration(self):
        self.driver.finish_migration(
            mock.sentinel.context, mock.sentinel.migration,
            mock.sentinel.instance, mock.sentinel.disk_info,
            mock.sentinel.network_info, mock.sentinel.image_meta,
            mock.sentinel.resize_instance, mock.sentinel.allocations,
            mock.sentinel.block_device_info,
            mock.sentinel.power_on)

        self.driver._migrationops.finish_migration.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.migration,
            mock.sentinel.instance, mock.sentinel.disk_info,
            mock.sentinel.network_info, mock.sentinel.image_meta,
            mock.sentinel.resize_instance, mock.sentinel.block_device_info,
            mock.sentinel.power_on)

    def test_get_host_ip_addr(self):
        self.driver.get_host_ip_addr()

        self.driver._hostops.get_host_ip_addr.assert_called_once_with()

    def test_get_host_uptime(self):
        self.driver.get_host_uptime()
        self.driver._hostops.get_host_uptime.assert_called_once_with()

    def test_get_rdp_console(self):
        self.driver.get_rdp_console(
            mock.sentinel.context, mock.sentinel.instance)
        self.driver._rdpconsoleops.get_rdp_console.assert_called_once_with(
            mock.sentinel.instance)

    def test_get_console_output(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.driver.get_console_output(self.context, mock_instance)

        mock_get_console_output = (
            self.driver._serialconsoleops.get_console_output)
        mock_get_console_output.assert_called_once_with(
            mock_instance.name)

    def test_get_serial_console(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.driver.get_console_output(self.context, mock_instance)

        mock_get_serial_console = (
            self.driver._serialconsoleops.get_console_output)
        mock_get_serial_console.assert_called_once_with(
            mock_instance.name)

    def test_manage_image_cache(self):
        self.driver.manage_image_cache(mock.sentinel.context,
                                       mock.sentinel.all_instances)
        self.driver._imagecache.update.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.all_instances)

    @mock.patch.object(driver.HyperVDriver, '_get_allocation_ratios')
    def test_update_provider_tree(self, mock_get_alloc_ratios):
        mock_ptree = mock.Mock()
        mock_inventory = mock_ptree.data.return_value.inventory

        self.driver.update_provider_tree(
            mock_ptree, mock.sentinel.nodename, mock.sentinel.allocations)

        mock_get_alloc_ratios.assert_called_once_with(mock_inventory)
        self.driver._hostops.update_provider_tree.assert_called_once_with(
            mock_ptree, mock.sentinel.nodename,
            mock_get_alloc_ratios.return_value,
            mock.sentinel.allocations)

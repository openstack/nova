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

from eventlet import timeout as etimeout
import mock
from os_win import exceptions as os_win_exc
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import units
import unittest2

from nova import exception
from nova import objects
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_virtual_interface
from nova.tests.unit.virt.hyperv import test_base
from nova.virt import hardware
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmops

CONF = cfg.CONF


class VMOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V VMOps class."""

    _FAKE_TIMEOUT = 2
    FAKE_SIZE = 10
    FAKE_DIR = 'fake_dir'
    FAKE_ROOT_PATH = 'C:\\path\\to\\fake.%s'
    FAKE_CONFIG_DRIVE_ISO = 'configdrive.iso'
    FAKE_CONFIG_DRIVE_VHD = 'configdrive.vhd'
    FAKE_UUID = '4f54fb69-d3a2-45b7-bb9b-b6e6b3d893b3'
    FAKE_LOG = 'fake_log'

    _WIN_VERSION_6_3 = '6.3.0'
    _WIN_VERSION_10 = '10.0'

    ISO9660 = 'iso9660'
    _FAKE_CONFIGDRIVE_PATH = 'C:/fake_instance_dir/configdrive.vhd'

    def setUp(self):
        super(VMOpsTestCase, self).setUp()
        self.context = 'fake-context'

        self._vmops = vmops.VMOps()
        self._vmops._vmutils = mock.MagicMock()
        self._vmops._vhdutils = mock.MagicMock()
        self._vmops._pathutils = mock.MagicMock()
        self._vmops._hostutils = mock.MagicMock()

    @mock.patch('nova.virt.hyperv.vmops.importutils.import_object')
    def test_load_vif_driver_class(self, mock_import_object):
        self._vmops._load_vif_driver_class()
        mock_import_object.assert_called_once_with(
            self._vmops._vif_driver_class_map[CONF.network_api_class])
        self.assertEqual(self._vmops._vif_driver,
                         mock_import_object.return_value)

    @mock.patch('nova.virt.hyperv.vmops.importutils.import_object')
    def test_load_vif_driver_class_error(self, mock_import_object):
        mock_import_object.side_effect = KeyError
        self.assertRaises(TypeError, self._vmops._load_vif_driver_class)

    def test_list_instances(self):
        mock_instance = mock.MagicMock()
        self._vmops._vmutils.list_instances.return_value = [mock_instance]
        response = self._vmops.list_instances()
        self._vmops._vmutils.list_instances.assert_called_once_with()
        self.assertEqual(response, [mock_instance])

    def _test_get_info(self, vm_exists):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_info = mock.MagicMock(spec_set=dict)
        fake_info = {'EnabledState': 2,
                     'MemoryUsage': mock.sentinel.FAKE_MEM_KB,
                     'NumberOfProcessors': mock.sentinel.FAKE_NUM_CPU,
                     'UpTime': mock.sentinel.FAKE_CPU_NS}

        def getitem(key):
            return fake_info[key]
        mock_info.__getitem__.side_effect = getitem

        expected = hardware.InstanceInfo(state=constants.HYPERV_POWER_STATE[2],
                                         max_mem_kb=mock.sentinel.FAKE_MEM_KB,
                                         mem_kb=mock.sentinel.FAKE_MEM_KB,
                                         num_cpu=mock.sentinel.FAKE_NUM_CPU,
                                         cpu_time_ns=mock.sentinel.FAKE_CPU_NS)

        self._vmops._vmutils.vm_exists.return_value = vm_exists
        self._vmops._vmutils.get_vm_summary_info.return_value = mock_info

        if not vm_exists:
            self.assertRaises(exception.InstanceNotFound,
                              self._vmops.get_info, mock_instance)
        else:
            response = self._vmops.get_info(mock_instance)
            self._vmops._vmutils.vm_exists.assert_called_once_with(
                mock_instance.name)
            self._vmops._vmutils.get_vm_summary_info.assert_called_once_with(
                mock_instance.name)
            self.assertEqual(response, expected)

    def test_get_info(self):
        self._test_get_info(vm_exists=True)

    def test_get_info_exception(self):
        self._test_get_info(vm_exists=False)

    def _prepare_create_root_vhd_mocks(self, use_cow_images, vhd_format,
                                       vhd_size):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_instance.root_gb = self.FAKE_SIZE
        self.flags(use_cow_images=use_cow_images)
        self._vmops._vhdutils.get_vhd_info.return_value = {'VirtualSize':
                                                           vhd_size * units.Gi}
        self._vmops._vhdutils.get_vhd_format.return_value = vhd_format
        root_vhd_internal_size = mock_instance.root_gb * units.Gi
        get_size = self._vmops._vhdutils.get_internal_vhd_size_by_file_size
        get_size.return_value = root_vhd_internal_size
        self._vmops._pathutils.exists.return_value = True

        return mock_instance

    @mock.patch('nova.virt.hyperv.imagecache.ImageCache.get_cached_image')
    def _test_create_root_vhd_exception(self, mock_get_cached_image,
                                        vhd_format):
        mock_instance = self._prepare_create_root_vhd_mocks(
            use_cow_images=False, vhd_format=vhd_format,
            vhd_size=(self.FAKE_SIZE + 1))
        fake_vhd_path = self.FAKE_ROOT_PATH % vhd_format
        mock_get_cached_image.return_value = fake_vhd_path
        fake_root_path = self._vmops._pathutils.get_root_vhd_path.return_value

        self.assertRaises(exception.FlavorDiskSmallerThanImage,
                          self._vmops._create_root_vhd, self.context,
                          mock_instance)

        self.assertFalse(self._vmops._vhdutils.resize_vhd.called)
        self._vmops._pathutils.exists.assert_called_once_with(
            fake_root_path)
        self._vmops._pathutils.remove.assert_called_once_with(
            fake_root_path)

    @mock.patch('nova.virt.hyperv.imagecache.ImageCache.get_cached_image')
    def _test_create_root_vhd_qcow(self, mock_get_cached_image, vhd_format):
        mock_instance = self._prepare_create_root_vhd_mocks(
            use_cow_images=True, vhd_format=vhd_format,
            vhd_size=(self.FAKE_SIZE - 1))
        fake_vhd_path = self.FAKE_ROOT_PATH % vhd_format
        mock_get_cached_image.return_value = fake_vhd_path

        fake_root_path = self._vmops._pathutils.get_root_vhd_path.return_value
        root_vhd_internal_size = mock_instance.root_gb * units.Gi
        get_size = self._vmops._vhdutils.get_internal_vhd_size_by_file_size

        response = self._vmops._create_root_vhd(context=self.context,
                                                instance=mock_instance)

        self.assertEqual(fake_root_path, response)
        self._vmops._pathutils.get_root_vhd_path.assert_called_with(
            mock_instance.name, vhd_format)
        differencing_vhd = self._vmops._vhdutils.create_differencing_vhd
        differencing_vhd.assert_called_with(fake_root_path, fake_vhd_path)
        self._vmops._vhdutils.get_vhd_info.assert_called_once_with(
            fake_vhd_path)

        if vhd_format is constants.DISK_FORMAT_VHD:
            self.assertFalse(get_size.called)
            self.assertFalse(self._vmops._vhdutils.resize_vhd.called)
        else:
            get_size.assert_called_once_with(fake_vhd_path,
                                             root_vhd_internal_size)
            self._vmops._vhdutils.resize_vhd.assert_called_once_with(
                fake_root_path, root_vhd_internal_size, is_file_max_size=False)

    @mock.patch('nova.virt.hyperv.imagecache.ImageCache.get_cached_image')
    def _test_create_root_vhd(self, mock_get_cached_image, vhd_format):
        mock_instance = self._prepare_create_root_vhd_mocks(
            use_cow_images=False, vhd_format=vhd_format,
            vhd_size=(self.FAKE_SIZE - 1))
        fake_vhd_path = self.FAKE_ROOT_PATH % vhd_format
        mock_get_cached_image.return_value = fake_vhd_path

        fake_root_path = self._vmops._pathutils.get_root_vhd_path.return_value
        root_vhd_internal_size = mock_instance.root_gb * units.Gi
        get_size = self._vmops._vhdutils.get_internal_vhd_size_by_file_size

        response = self._vmops._create_root_vhd(context=self.context,
                                                instance=mock_instance)

        self.assertEqual(fake_root_path, response)
        self._vmops._pathutils.get_root_vhd_path.assert_called_with(
            mock_instance.name, vhd_format)

        self._vmops._pathutils.copyfile.assert_called_once_with(
            fake_vhd_path, fake_root_path)
        get_size.assert_called_once_with(fake_vhd_path, root_vhd_internal_size)
        self._vmops._vhdutils.resize_vhd.assert_called_once_with(
            fake_root_path, root_vhd_internal_size, is_file_max_size=False)

    def test_create_root_vhd(self):
        self._test_create_root_vhd(vhd_format=constants.DISK_FORMAT_VHD)

    def test_create_root_vhdx(self):
        self._test_create_root_vhd(vhd_format=constants.DISK_FORMAT_VHDX)

    def test_create_root_vhd_use_cow_images_true(self):
        self._test_create_root_vhd_qcow(vhd_format=constants.DISK_FORMAT_VHD)

    def test_create_root_vhdx_use_cow_images_true(self):
        self._test_create_root_vhd_qcow(vhd_format=constants.DISK_FORMAT_VHDX)

    def test_create_root_vhdx_size_less_than_internal(self):
        self._test_create_root_vhd_exception(
            vhd_format=constants.DISK_FORMAT_VHD)

    def test_is_resize_needed_exception(self):
        inst = mock.MagicMock()
        self.assertRaises(
            exception.FlavorDiskSmallerThanImage,
            self._vmops._is_resize_needed,
            mock.sentinel.FAKE_PATH, self.FAKE_SIZE, self.FAKE_SIZE - 1, inst)

    def test_is_resize_needed_true(self):
        inst = mock.MagicMock()
        self.assertTrue(self._vmops._is_resize_needed(
            mock.sentinel.FAKE_PATH, self.FAKE_SIZE, self.FAKE_SIZE + 1, inst))

    def test_is_resize_needed_false(self):
        inst = mock.MagicMock()
        self.assertFalse(self._vmops._is_resize_needed(
            mock.sentinel.FAKE_PATH, self.FAKE_SIZE, self.FAKE_SIZE, inst))

    def test_create_ephemeral_vhd(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_instance.ephemeral_gb = self.FAKE_SIZE
        best_supported = self._vmops._vhdutils.get_best_supported_vhd_format
        best_supported.return_value = mock.sentinel.FAKE_FORMAT
        self._vmops._pathutils.get_ephemeral_vhd_path.return_value = (
            mock.sentinel.FAKE_PATH)

        response = self._vmops.create_ephemeral_vhd(instance=mock_instance)

        self._vmops._pathutils.get_ephemeral_vhd_path.assert_called_with(
            mock_instance.name, mock.sentinel.FAKE_FORMAT)
        self._vmops._vhdutils.create_dynamic_vhd.assert_called_with(
            mock.sentinel.FAKE_PATH, mock_instance.ephemeral_gb * units.Gi)
        self.assertEqual(mock.sentinel.FAKE_PATH, response)

    @mock.patch('nova.virt.hyperv.vmops.VMOps.destroy')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.power_on')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.attach_config_drive')
    @mock.patch('nova.virt.hyperv.vmops.VMOps._create_config_drive')
    @mock.patch('nova.virt.configdrive.required_by')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.create_instance')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.get_image_vm_generation')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.create_ephemeral_vhd')
    @mock.patch('nova.virt.hyperv.vmops.VMOps._create_root_vhd')
    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps.'
                'ebs_root_in_block_devices')
    @mock.patch('nova.virt.hyperv.vmops.VMOps._delete_disk_files')
    def _test_spawn(self, mock_delete_disk_files,
                    mock_ebs_root_in_block_devices, mock_create_root_vhd,
                    mock_create_ephemeral_vhd, mock_get_image_vm_gen,
                    mock_create_instance, mock_configdrive_required,
                    mock_create_config_drive, mock_attach_config_drive,
                    mock_power_on, mock_destroy, exists, boot_from_volume,
                    configdrive_required, fail):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_image_meta = mock.MagicMock()

        fake_root_path = mock_create_root_vhd.return_value
        fake_root_path = None if boot_from_volume else fake_root_path
        fake_ephemeral_path = mock_create_ephemeral_vhd.return_value
        fake_vm_gen = mock_get_image_vm_gen.return_value
        fake_config_drive_path = mock_create_config_drive.return_value

        self._vmops._vmutils.vm_exists.return_value = exists
        mock_ebs_root_in_block_devices.return_value = boot_from_volume
        mock_create_root_vhd.return_value = fake_root_path
        mock_configdrive_required.return_value = configdrive_required
        mock_create_instance.side_effect = fail
        if exists:
            self.assertRaises(exception.InstanceExists, self._vmops.spawn,
                              self.context, mock_instance, mock_image_meta,
                              [mock.sentinel.FILE], mock.sentinel.PASSWORD,
                              mock.sentinel.INFO, mock.sentinel.DEV_INFO)
        elif fail is os_win_exc.HyperVException:
            self.assertRaises(os_win_exc.HyperVException, self._vmops.spawn,
                              self.context, mock_instance, mock_image_meta,
                              [mock.sentinel.FILE], mock.sentinel.PASSWORD,
                              mock.sentinel.INFO, mock.sentinel.DEV_INFO)
            mock_destroy.assert_called_once_with(mock_instance)
        else:
            self._vmops.spawn(self.context, mock_instance, mock_image_meta,
                              [mock.sentinel.FILE], mock.sentinel.PASSWORD,
                              mock.sentinel.INFO, mock.sentinel.DEV_INFO)
            self._vmops._vmutils.vm_exists.assert_called_once_with(
                mock_instance.name)
            mock_delete_disk_files.assert_called_once_with(
                mock_instance.name)
            mock_ebs_root_in_block_devices.assert_called_once_with(
                mock.sentinel.DEV_INFO)
            if not boot_from_volume:
                mock_create_root_vhd.assert_called_once_with(self.context,
                                                             mock_instance)
            mock_create_ephemeral_vhd.assert_called_once_with(mock_instance)
            mock_get_image_vm_gen.assert_called_once_with(
                mock_instance.uuid, fake_root_path, mock_image_meta)
            mock_create_instance.assert_called_once_with(
                mock_instance, mock.sentinel.INFO, mock.sentinel.DEV_INFO,
                fake_root_path, fake_ephemeral_path, fake_vm_gen)
            mock_configdrive_required.assert_called_once_with(mock_instance)
            if configdrive_required:
                mock_create_config_drive.assert_called_once_with(
                    mock_instance, [mock.sentinel.FILE],
                    mock.sentinel.PASSWORD,
                    mock.sentinel.INFO)
                mock_attach_config_drive.assert_called_once_with(
                    mock_instance, fake_config_drive_path, fake_vm_gen)
            mock_power_on.assert_called_once_with(mock_instance)

    def test_spawn(self):
        self._test_spawn(exists=False, boot_from_volume=False,
                         configdrive_required=True, fail=None)

    def test_spawn_instance_exists(self):
        self._test_spawn(exists=True, boot_from_volume=False,
                         configdrive_required=True, fail=None)

    def test_spawn_create_instance_exception(self):
        self._test_spawn(exists=False, boot_from_volume=False,
                         configdrive_required=True,
                         fail=os_win_exc.HyperVException)

    def test_spawn_not_required(self):
        self._test_spawn(exists=False, boot_from_volume=False,
                         configdrive_required=False, fail=None)

    def test_spawn_root_in_block(self):
        self._test_spawn(exists=False, boot_from_volume=True,
                         configdrive_required=False, fail=None)

    def test_spawn_no_admin_permissions(self):
        self._vmops._vmutils.check_admin_permissions.side_effect = (
            os_win_exc.HyperVException)
        self.assertRaises(os_win_exc.HyperVException,
                          self._vmops.spawn,
                          self.context, mock.DEFAULT, mock.DEFAULT,
                          [mock.sentinel.FILE], mock.sentinel.PASSWORD,
                          mock.sentinel.INFO, mock.sentinel.DEV_INFO)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps'
                '.attach_volumes')
    @mock.patch.object(vmops.VMOps, '_attach_drive')
    def _test_create_instance(self, mock_attach_drive, mock_attach_volumes,
                              fake_root_path, fake_ephemeral_path,
                              enable_instance_metrics,
                              vm_gen=constants.VM_GEN_1):
        mock_vif_driver = mock.MagicMock()
        self._vmops._vif_driver = mock_vif_driver
        self.flags(enable_instance_metrics_collection=enable_instance_metrics,
                   group='hyperv')
        fake_network_info = {'id': mock.sentinel.ID,
                             'address': mock.sentinel.ADDRESS}
        mock_instance = fake_instance.fake_instance_obj(self.context)
        instance_path = os.path.join(CONF.instances_path, mock_instance.name)

        self._vmops.create_instance(instance=mock_instance,
                                    network_info=[fake_network_info],
                                    block_device_info=mock.sentinel.DEV_INFO,
                                    root_vhd_path=fake_root_path,
                                    eph_vhd_path=fake_ephemeral_path,
                                    vm_gen=vm_gen)
        self._vmops._vmutils.create_vm.assert_called_once_with(
            mock_instance.name, mock_instance.memory_mb,
            mock_instance.vcpus, CONF.hyperv.limit_cpu_features,
            CONF.hyperv.dynamic_memory_ratio, vm_gen, instance_path,
            [mock_instance.uuid])
        expected = []
        ctrl_type = vmops.VM_GENERATIONS_CONTROLLER_TYPES[vm_gen]
        ctrl_disk_addr = 0
        if fake_root_path:
            expected.append(mock.call(mock_instance.name, fake_root_path,
                                      0, ctrl_disk_addr, ctrl_type,
                                      constants.DISK))
        ctrl_disk_addr = 1
        if fake_ephemeral_path:
            expected.append(mock.call(mock_instance.name,
                                      fake_ephemeral_path, 0, ctrl_disk_addr,
                                      ctrl_type, constants.DISK))
        mock_attach_drive.has_calls(expected)
        self._vmops._vmutils.create_scsi_controller.assert_called_once_with(
            mock_instance.name)

        ebs_root = vm_gen is not constants.VM_GEN_2 and fake_root_path is None
        mock_attach_volumes.assert_called_once_with(mock.sentinel.DEV_INFO,
                                                    mock_instance.name,
                                                    ebs_root)
        self._vmops._vmutils.create_nic.assert_called_once_with(
            mock_instance.name, mock.sentinel.ID, mock.sentinel.ADDRESS)
        mock_vif_driver.plug.assert_called_once_with(mock_instance,
                                                     fake_network_info)
        mock_enable = self._vmops._vmutils.enable_vm_metrics_collection
        if enable_instance_metrics:
            mock_enable.assert_called_once_with(mock_instance.name)

    def test_create_instance(self):
        fake_ephemeral_path = mock.sentinel.FAKE_EPHEMERAL_PATH
        self._test_create_instance(fake_root_path=mock.sentinel.FAKE_ROOT_PATH,
                                   fake_ephemeral_path=fake_ephemeral_path,
                                   enable_instance_metrics=True)

    def test_create_instance_no_root_path(self):
        fake_ephemeral_path = mock.sentinel.FAKE_EPHEMERAL_PATH
        self._test_create_instance(fake_root_path=None,
                                   fake_ephemeral_path=fake_ephemeral_path,
                                   enable_instance_metrics=True)

    def test_create_instance_no_ephemeral_path(self):
        self._test_create_instance(fake_root_path=mock.sentinel.FAKE_ROOT_PATH,
                                   fake_ephemeral_path=None,
                                   enable_instance_metrics=True)

    def test_create_instance_no_path(self):
        self._test_create_instance(fake_root_path=None,
                                   fake_ephemeral_path=None,
                                   enable_instance_metrics=False)

    def test_create_instance_enable_instance_metrics_false(self):
        fake_ephemeral_path = mock.sentinel.FAKE_EPHEMERAL_PATH
        self._test_create_instance(fake_root_path=mock.sentinel.FAKE_ROOT_PATH,
                                   fake_ephemeral_path=fake_ephemeral_path,
                                   enable_instance_metrics=False)

    def test_create_instance_gen2(self):
        self._test_create_instance(fake_root_path=None,
                                   fake_ephemeral_path=None,
                                   enable_instance_metrics=False,
                                   vm_gen=constants.VM_GEN_2)

    def test_attach_drive_vm_to_scsi(self):
        self._vmops._attach_drive(
            mock.sentinel.FAKE_VM_NAME, mock.sentinel.FAKE_PATH,
            mock.sentinel.FAKE_DRIVE_ADDR, mock.sentinel.FAKE_CTRL_DISK_ADDR,
            constants.CTRL_TYPE_SCSI)

        self._vmops._vmutils.attach_scsi_drive.assert_called_once_with(
            mock.sentinel.FAKE_VM_NAME, mock.sentinel.FAKE_PATH,
            constants.DISK)

    def test_attach_drive_vm_to_ide(self):
        self._vmops._attach_drive(
            mock.sentinel.FAKE_VM_NAME, mock.sentinel.FAKE_PATH,
            mock.sentinel.FAKE_DRIVE_ADDR, mock.sentinel.FAKE_CTRL_DISK_ADDR,
            constants.CTRL_TYPE_IDE)

        self._vmops._vmutils.attach_ide_drive.assert_called_once_with(
            mock.sentinel.FAKE_VM_NAME, mock.sentinel.FAKE_PATH,
            mock.sentinel.FAKE_DRIVE_ADDR, mock.sentinel.FAKE_CTRL_DISK_ADDR,
            constants.DISK)

    def test_get_image_vm_generation_default(self):
        image_meta = objects.ImageMeta.from_dict({"properties": {}})
        self._vmops._hostutils.get_default_vm_generation.return_value = (
            constants.IMAGE_PROP_VM_GEN_1)
        self._vmops._hostutils.get_supported_vm_types.return_value = [
            constants.IMAGE_PROP_VM_GEN_1, constants.IMAGE_PROP_VM_GEN_2]

        response = self._vmops.get_image_vm_generation(
            mock.sentinel.instance_id, mock.sentinel.FAKE_PATH, image_meta)

        self.assertEqual(constants.VM_GEN_1, response)

    def test_get_image_vm_generation_gen2(self):
        image_meta = objects.ImageMeta.from_dict(
            {"properties":
             {"hw_machine_type": constants.IMAGE_PROP_VM_GEN_2}})
        self._vmops._hostutils.get_supported_vm_types.return_value = [
            constants.IMAGE_PROP_VM_GEN_1, constants.IMAGE_PROP_VM_GEN_2]
        self._vmops._vhdutils.get_vhd_format.return_value = (
            constants.DISK_FORMAT_VHDX)

        response = self._vmops.get_image_vm_generation(
            mock.sentinel.instance_id, mock.sentinel.FAKE_PATH, image_meta)

        self.assertEqual(constants.VM_GEN_2, response)

    def test_get_image_vm_generation_not_vhdx(self):
        image_meta = objects.ImageMeta.from_dict(
            {"properties":
             {'hw_machine_type': constants.IMAGE_PROP_VM_GEN_2}})
        self._vmops._hostutils.get_supported_vm_types.return_value = [
            constants.IMAGE_PROP_VM_GEN_1, constants.IMAGE_PROP_VM_GEN_2]
        self._vmops._vhdutils.get_vhd_format.return_value = (
            constants.DISK_FORMAT_VHD)

        self.assertRaises(exception.InstanceUnacceptable,
                          self._vmops.get_image_vm_generation,
                          mock.sentinel.instance_id,
                          mock.sentinel.FAKE_PATH,
                          image_meta)

    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder')
    @mock.patch('nova.utils.execute')
    def _test_create_config_drive(self, mock_execute, mock_ConfigDriveBuilder,
                                  mock_InstanceMetadata, config_drive_format,
                                  config_drive_cdrom, side_effect):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.flags(config_drive_format=config_drive_format)
        self.flags(config_drive_cdrom=config_drive_cdrom, group='hyperv')
        self.flags(config_drive_inject_password=True, group='hyperv')
        self._vmops._pathutils.get_instance_dir.return_value = (
            self.FAKE_DIR)
        mock_ConfigDriveBuilder().__enter__().make_drive.side_effect = [
            side_effect]

        if config_drive_format != self.ISO9660:
            self.assertRaises(exception.ConfigDriveUnsupportedFormat,
                              self._vmops._create_config_drive,
                              mock_instance, [mock.sentinel.FILE],
                              mock.sentinel.PASSWORD,
                              mock.sentinel.NET_INFO)
        elif side_effect is processutils.ProcessExecutionError:
            self.assertRaises(processutils.ProcessExecutionError,
                              self._vmops._create_config_drive,
                              mock_instance, [mock.sentinel.FILE],
                              mock.sentinel.PASSWORD,
                              mock.sentinel.NET_INFO)
        else:
            path = self._vmops._create_config_drive(mock_instance,
                                                    [mock.sentinel.FILE],
                                                    mock.sentinel.PASSWORD,
                                                    mock.sentinel.NET_INFO)
            mock_InstanceMetadata.assert_called_once_with(
                mock_instance, content=[mock.sentinel.FILE],
                extra_md={'admin_pass': mock.sentinel.PASSWORD},
                network_info=mock.sentinel.NET_INFO)
            self._vmops._pathutils.get_instance_dir.assert_called_once_with(
                mock_instance.name)
            mock_ConfigDriveBuilder.assert_called_with(
                instance_md=mock_InstanceMetadata())
            mock_make_drive = mock_ConfigDriveBuilder().__enter__().make_drive
            path_iso = os.path.join(self.FAKE_DIR, self.FAKE_CONFIG_DRIVE_ISO)
            path_vhd = os.path.join(self.FAKE_DIR, self.FAKE_CONFIG_DRIVE_VHD)
            mock_make_drive.assert_called_once_with(path_iso)
            if not CONF.hyperv.config_drive_cdrom:
                expected = path_vhd
                mock_execute.assert_called_once_with(
                    CONF.hyperv.qemu_img_cmd,
                    'convert', '-f', 'raw', '-O', 'vpc',
                    path_iso, path_vhd, attempts=1)
                self._vmops._pathutils.remove.assert_called_once_with(
                    os.path.join(self.FAKE_DIR, self.FAKE_CONFIG_DRIVE_ISO))
            else:
                expected = path_iso

            self.assertEqual(expected, path)

    def test_create_config_drive_cdrom(self):
        self._test_create_config_drive(config_drive_format=self.ISO9660,
                                       config_drive_cdrom=True,
                                       side_effect=None)

    def test_create_config_drive_vhd(self):
        self._test_create_config_drive(config_drive_format=self.ISO9660,
                                       config_drive_cdrom=False,
                                       side_effect=None)

    def test_create_config_drive_other_drive_format(self):
        self._test_create_config_drive(config_drive_format=mock.sentinel.OTHER,
                                       config_drive_cdrom=False,
                                       side_effect=None)

    def test_create_config_drive_execution_error(self):
        self._test_create_config_drive(
            config_drive_format=self.ISO9660,
            config_drive_cdrom=False,
            side_effect=processutils.ProcessExecutionError)

    def test_attach_config_drive_exception(self):
        instance = fake_instance.fake_instance_obj(self.context)
        self.assertRaises(exception.InvalidDiskFormat,
                          self._vmops.attach_config_drive,
                          instance, 'C:/fake_instance_dir/configdrive.xxx',
                          constants.VM_GEN_1)

    @mock.patch.object(vmops.VMOps, '_attach_drive')
    def test_attach_config_drive(self, mock_attach_drive):
        instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.attach_config_drive(instance,
                                        self._FAKE_CONFIGDRIVE_PATH,
                                        constants.VM_GEN_1)
        mock_attach_drive.assert_called_once_with(
            instance.name, self._FAKE_CONFIGDRIVE_PATH,
            1, 0, constants.CTRL_TYPE_IDE, constants.DISK)

    @mock.patch.object(vmops.VMOps, '_attach_drive')
    def test_attach_config_drive_gen2(self, mock_attach_drive):
        instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.attach_config_drive(instance,
                                        self._FAKE_CONFIGDRIVE_PATH,
                                        constants.VM_GEN_2)
        mock_attach_drive.assert_called_once_with(
            instance.name, self._FAKE_CONFIGDRIVE_PATH,
            1, 0, constants.CTRL_TYPE_SCSI, constants.DISK)

    def test_delete_disk_files(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._delete_disk_files(mock_instance.name)
        self._vmops._pathutils.get_instance_dir.assert_called_once_with(
            mock_instance.name, create_dir=False, remove_dir=True)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps.disconnect_volumes')
    @mock.patch('nova.virt.hyperv.vmops.VMOps._delete_disk_files')
    @mock.patch('nova.virt.hyperv.vmops.VMOps.power_off')
    def test_destroy(self, mock_power_off, mock_delete_disk_files,
                     mock_disconnect_volumes):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._vmutils.vm_exists.return_value = True
        self._vmops._vif_driver = mock.MagicMock()

        self._vmops.destroy(instance=mock_instance,
                            network_info=[mock.sentinel.fake_vif],
                            block_device_info=mock.sentinel.FAKE_BD_INFO)

        self._vmops._vmutils.vm_exists.assert_called_with(
            mock_instance.name)
        mock_power_off.assert_called_once_with(mock_instance)
        self._vmops._vif_driver.unplug.assert_called_once_with(
            mock_instance, mock.sentinel.fake_vif)
        self._vmops._vmutils.destroy_vm.assert_called_once_with(
            mock_instance.name)
        mock_disconnect_volumes.assert_called_once_with(
            mock.sentinel.FAKE_BD_INFO)
        mock_delete_disk_files.assert_called_once_with(
            mock_instance.name)

    def test_destroy_inexistent_instance(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._vmutils.vm_exists.return_value = False

        self._vmops.destroy(instance=mock_instance)
        self.assertFalse(self._vmops._vmutils.destroy_vm.called)

    @mock.patch('nova.virt.hyperv.vmops.VMOps.power_off')
    def test_destroy_exception(self, mock_power_off):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._vmutils.destroy_vm.side_effect = (
            os_win_exc.HyperVException)
        self._vmops._vmutils.vm_exists.return_value = True

        self.assertRaises(os_win_exc.HyperVException,
                          self._vmops.destroy, mock_instance)

    def test_reboot_hard(self):
        self._test_reboot(vmops.REBOOT_TYPE_HARD,
                          constants.HYPERV_VM_STATE_REBOOT)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = True
        self._test_reboot(vmops.REBOOT_TYPE_SOFT,
                          constants.HYPERV_VM_STATE_ENABLED)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft_failed(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = False
        self._test_reboot(vmops.REBOOT_TYPE_SOFT,
                          constants.HYPERV_VM_STATE_REBOOT)

    @mock.patch("nova.virt.hyperv.vmops.VMOps.power_on")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_reboot_soft_exception(self, mock_soft_shutdown, mock_power_on):
        mock_soft_shutdown.return_value = True
        mock_power_on.side_effect = os_win_exc.HyperVException(
            "Expected failure")
        instance = fake_instance.fake_instance_obj(self.context)

        self.assertRaises(os_win_exc.HyperVException, self._vmops.reboot,
                          instance, {}, vmops.REBOOT_TYPE_SOFT)

        mock_soft_shutdown.assert_called_once_with(instance)
        mock_power_on.assert_called_once_with(instance)

    def _test_reboot(self, reboot_type, vm_state):
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self._vmops, '_set_vm_state') as mock_set_state:
            self._vmops.reboot(instance, {}, reboot_type)
            mock_set_state.assert_called_once_with(instance, vm_state)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown(self, mock_wait_for_power_off):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.return_value = True

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT)

        mock_shutdown_vm = self._vmops._vmutils.soft_shutdown_vm
        mock_shutdown_vm.assert_called_once_with(instance.name)
        mock_wait_for_power_off.assert_called_once_with(
            instance.name, self._FAKE_TIMEOUT)

        self.assertTrue(result)

    @mock.patch("time.sleep")
    def test_soft_shutdown_failed(self, mock_sleep):
        instance = fake_instance.fake_instance_obj(self.context)

        mock_shutdown_vm = self._vmops._vmutils.soft_shutdown_vm
        mock_shutdown_vm.side_effect = os_win_exc.HyperVException(
            "Expected failure.")

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT)

        mock_shutdown_vm.assert_called_once_with(instance.name)
        self.assertFalse(result)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown_wait(self, mock_wait_for_power_off):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.side_effect = [False, True]

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT, 1)

        calls = [mock.call(instance.name, 1),
                 mock.call(instance.name, self._FAKE_TIMEOUT - 1)]
        mock_shutdown_vm = self._vmops._vmutils.soft_shutdown_vm
        mock_shutdown_vm.assert_called_with(instance.name)
        mock_wait_for_power_off.assert_has_calls(calls)

        self.assertTrue(result)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._wait_for_power_off")
    def test_soft_shutdown_wait_timeout(self, mock_wait_for_power_off):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_wait_for_power_off.return_value = False

        result = self._vmops._soft_shutdown(instance, self._FAKE_TIMEOUT, 1.5)

        calls = [mock.call(instance.name, 1.5),
                 mock.call(instance.name, self._FAKE_TIMEOUT - 1.5)]
        mock_shutdown_vm = self._vmops._vmutils.soft_shutdown_vm
        mock_shutdown_vm.assert_called_with(instance.name)
        mock_wait_for_power_off.assert_has_calls(calls)

        self.assertFalse(result)

    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_pause(self, mock_set_vm_state):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.pause(instance=mock_instance)
        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_PAUSED)

    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_unpause(self, mock_set_vm_state):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.unpause(instance=mock_instance)
        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_ENABLED)

    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_suspend(self, mock_set_vm_state):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.suspend(instance=mock_instance)
        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_SUSPENDED)

    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_resume(self, mock_set_vm_state):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops.resume(instance=mock_instance)
        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_ENABLED)

    def _test_power_off(self, timeout, set_state_expected=True):
        instance = fake_instance.fake_instance_obj(self.context)
        with mock.patch.object(self._vmops, '_set_vm_state') as mock_set_state:
            self._vmops.power_off(instance, timeout)

            if set_state_expected:
                mock_set_state.assert_called_once_with(
                    instance, constants.HYPERV_VM_STATE_DISABLED)

    def test_power_off_hard(self):
        self._test_power_off(timeout=0)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_power_off_exception(self, mock_soft_shutdown):
        mock_soft_shutdown.return_value = False
        self._test_power_off(timeout=1)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._set_vm_state")
    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_power_off_soft(self, mock_soft_shutdown, mock_set_state):
        instance = fake_instance.fake_instance_obj(self.context)
        mock_soft_shutdown.return_value = True

        self._vmops.power_off(instance, 1, 0)

        mock_soft_shutdown.assert_called_once_with(
            instance, 1, vmops.SHUTDOWN_TIME_INCREMENT)
        self.assertFalse(mock_set_state.called)

    @mock.patch("nova.virt.hyperv.vmops.VMOps._soft_shutdown")
    def test_power_off_unexisting_instance(self, mock_soft_shutdown):
        mock_soft_shutdown.side_effect = os_win_exc.HyperVVMNotFoundException(
            vm_name=mock.sentinel.vm_name)
        self._test_power_off(timeout=1, set_state_expected=False)

    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_power_on(self, mock_set_vm_state):
        mock_instance = fake_instance.fake_instance_obj(self.context)

        self._vmops.power_on(mock_instance)

        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_ENABLED)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps'
                '.fix_instance_volume_disk_paths')
    @mock.patch('nova.virt.hyperv.vmops.VMOps._set_vm_state')
    def test_power_on_having_block_devices(self, mock_set_vm_state,
                                           mock_fix_instance_vol_paths):
        mock_instance = fake_instance.fake_instance_obj(self.context)

        self._vmops.power_on(mock_instance, mock.sentinel.block_device_info)

        mock_fix_instance_vol_paths.assert_called_once_with(
            mock_instance.name, mock.sentinel.block_device_info)
        mock_set_vm_state.assert_called_once_with(
            mock_instance, constants.HYPERV_VM_STATE_ENABLED)

    @mock.patch.object(vmops.VMOps, 'log_vm_serial_output')
    @mock.patch.object(vmops.VMOps, '_delete_vm_console_log')
    def _test_set_vm_state(self, mock_delete_vm_console_log,
                           mock_log_vm_output, state):
        mock_instance = fake_instance.fake_instance_obj(self.context)

        self._vmops._set_vm_state(mock_instance, state)
        self._vmops._vmutils.set_vm_state.assert_called_once_with(
            mock_instance.name, state)
        if state in (constants.HYPERV_VM_STATE_DISABLED,
                     constants.HYPERV_VM_STATE_REBOOT):
            mock_delete_vm_console_log.assert_called_once_with(mock_instance)
        if state in (constants.HYPERV_VM_STATE_ENABLED,
                     constants.HYPERV_VM_STATE_REBOOT):
            mock_log_vm_output.assert_called_once_with(mock_instance.name,
                                                       mock_instance.uuid)

    def test_set_vm_state_disabled(self):
        self._test_set_vm_state(state=constants.HYPERV_VM_STATE_DISABLED)

    def test_set_vm_state_enabled(self):
        self._test_set_vm_state(state=constants.HYPERV_VM_STATE_ENABLED)

    def test_set_vm_state_reboot(self):
        self._test_set_vm_state(state=constants.HYPERV_VM_STATE_REBOOT)

    def test_set_vm_state_exception(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._vmutils.set_vm_state.side_effect = (
            os_win_exc.HyperVException)
        self.assertRaises(os_win_exc.HyperVException,
                          self._vmops._set_vm_state,
                          mock_instance, mock.sentinel.STATE)

    def test_get_vm_state(self):
        summary_info = {'EnabledState': constants.HYPERV_VM_STATE_DISABLED}

        with mock.patch.object(self._vmops._vmutils,
                               'get_vm_summary_info') as mock_get_summary_info:
            mock_get_summary_info.return_value = summary_info

            response = self._vmops._get_vm_state(mock.sentinel.FAKE_VM_NAME)
            self.assertEqual(response, constants.HYPERV_VM_STATE_DISABLED)

    @mock.patch.object(vmops.VMOps, '_get_vm_state')
    def test_wait_for_power_off_true(self, mock_get_state):
        mock_get_state.return_value = constants.HYPERV_VM_STATE_DISABLED
        result = self._vmops._wait_for_power_off(
            mock.sentinel.FAKE_VM_NAME, vmops.SHUTDOWN_TIME_INCREMENT)
        mock_get_state.assert_called_with(mock.sentinel.FAKE_VM_NAME)
        self.assertTrue(result)

    @mock.patch.object(vmops.etimeout, "with_timeout")
    def test_wait_for_power_off_false(self, mock_with_timeout):
        mock_with_timeout.side_effect = etimeout.Timeout()
        result = self._vmops._wait_for_power_off(
            mock.sentinel.FAKE_VM_NAME, vmops.SHUTDOWN_TIME_INCREMENT)
        self.assertFalse(result)

    @mock.patch.object(vmops.ioutils, 'IOThread')
    def _test_log_vm_serial_output(self, mock_io_thread,
                                   worker_running=False,
                                   worker_exists=False):
        self._vmops._pathutils.get_vm_console_log_paths.return_value = (
            mock.sentinel.log_path, )
        fake_instance_uuid = 'fake-uuid'
        fake_existing_worker = mock.Mock()
        fake_existing_worker.is_active.return_value = worker_running
        fake_log_writers = {fake_instance_uuid: fake_existing_worker}
        self._vmops._vm_log_writers = (
            fake_log_writers if worker_exists else {})

        self._vmops.log_vm_serial_output(mock.sentinel.instance_name,
                                         fake_instance_uuid)

        if not (worker_exists and worker_running):
            expected_pipe_path = r'\\.\pipe\%s' % fake_instance_uuid
            expected_current_worker = mock_io_thread.return_value
            expected_current_worker.start.assert_called_once_with()
            mock_io_thread.assert_called_once_with(
                expected_pipe_path, mock.sentinel.log_path,
                self._vmops._MAX_CONSOLE_LOG_FILE_SIZE)
        else:
            expected_current_worker = fake_existing_worker
        self.assertEqual(expected_current_worker,
                        self._vmops._vm_log_writers[fake_instance_uuid])

    def test_log_vm_serial_output_unexisting_worker(self):
        self._test_log_vm_serial_output()

    def test_log_vm_serial_output_worker_stopped(self):
        self._test_log_vm_serial_output(worker_exists=True)

    def test_log_vm_serial_output_worker_running(self):
        self._test_log_vm_serial_output(worker_exists=True,
                                        worker_running=True)

    def test_copy_vm_console_logs(self):
        fake_local_paths = (mock.sentinel.FAKE_PATH,
                            mock.sentinel.FAKE_PATH_ARCHIVED)
        fake_remote_paths = (mock.sentinel.FAKE_REMOTE_PATH,
                             mock.sentinel.FAKE_REMOTE_PATH_ARCHIVED)

        self._vmops._pathutils.get_vm_console_log_paths.side_effect = [
            fake_local_paths, fake_remote_paths]
        self._vmops._pathutils.exists.side_effect = [True, False]

        self._vmops.copy_vm_console_logs(mock.sentinel.FAKE_VM_NAME,
                                         mock.sentinel.FAKE_DEST)

        calls = [mock.call(mock.sentinel.FAKE_VM_NAME),
                 mock.call(mock.sentinel.FAKE_VM_NAME,
                           remote_server=mock.sentinel.FAKE_DEST)]
        self._vmops._pathutils.get_vm_console_log_paths.assert_has_calls(calls)

        calls = [mock.call(mock.sentinel.FAKE_PATH),
                 mock.call(mock.sentinel.FAKE_PATH_ARCHIVED)]
        self._vmops._pathutils.exists.assert_has_calls(calls)

        self._vmops._pathutils.copy.assert_called_once_with(
            mock.sentinel.FAKE_PATH, mock.sentinel.FAKE_REMOTE_PATH)

    @mock.patch.object(vmops.ioutils, 'IOThread')
    def test_log_vm_serial_output(self, fake_iothread):
        self._vmops._pathutils.get_vm_console_log_paths.return_value = [
            mock.sentinel.FAKE_PATH]

        self._vmops.log_vm_serial_output(mock.sentinel.FAKE_VM_NAME,
                                         self.FAKE_UUID)

        pipe_path = r'\\.\pipe\%s' % self.FAKE_UUID
        fake_iothread.assert_called_once_with(
            pipe_path, mock.sentinel.FAKE_PATH,
            self._vmops._MAX_CONSOLE_LOG_FILE_SIZE)
        fake_iothread.return_value.start.assert_called_once_with()

    @unittest2.skip('mock_open in 1.2 read only works once 1475661')
    @mock.patch("os.path.exists")
    def test_get_console_output(self, fake_path_exists):
        mock_instance = fake_instance.fake_instance_obj(self.context)

        fake_path_exists.return_value = True
        self._vmops._pathutils.get_vm_console_log_paths.return_value = (
            mock.sentinel.FAKE_PATH, mock.sentinel.FAKE_PATH_ARCHIVED)

        with mock.patch('nova.virt.hyperv.vmops.open',
                        mock.mock_open(read_data=self.FAKE_LOG),
                        create=True):
            instance_log = self._vmops.get_console_output(mock_instance)
            # get_vm_console_log_paths returns 2 paths.
            self.assertEqual(self.FAKE_LOG * 2, instance_log)

            expected_calls = [mock.call(mock.sentinel.FAKE_PATH_ARCHIVED),
                              mock.call(mock.sentinel.FAKE_PATH)]
            fake_path_exists.assert_has_calls(expected_calls, any_order=False)

    @mock.patch("__builtin__.open")
    @mock.patch("os.path.exists")
    def test_get_console_output_exception(self, fake_path_exists, fake_open):
        fake_vm = mock.MagicMock()
        fake_open.side_effect = IOError
        fake_path_exists.return_value = True
        self._vmops._pathutils.get_vm_console_log_paths.return_value = (
            mock.sentinel.fake_console_log_path,
            mock.sentinel.fake_console_log_archived)

        with mock.patch('nova.virt.hyperv.vmops.open', fake_open, create=True):
            self.assertRaises(exception.ConsoleLogOutputException,
                              self._vmops.get_console_output,
                              fake_vm)

    @mock.patch.object(vmops.fileutils, 'delete_if_exists')
    def test_delete_vm_console_log(self, mock_delete_if_exists):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self._vmops._pathutils.get_vm_console_log_paths.return_value = (
            mock.sentinel.FAKE_PATH, )
        mock_log_writer = mock.MagicMock()
        self._vmops._vm_log_writers[mock_instance['uuid']] = mock_log_writer

        self._vmops._delete_vm_console_log(mock_instance)

        mock_log_writer.join.assert_called_once_with()
        mock_delete_if_exists.assert_called_once_with(mock.sentinel.FAKE_PATH)

    def test_create_vm_com_port_pipe(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        pipe_path = r'\\.\pipe\%s' % mock_instance['uuid']

        self._vmops._create_vm_com_port_pipe(mock_instance)

        get_vm_serial_port = self._vmops._vmutils.get_vm_serial_port_connection
        get_vm_serial_port.assert_called_once_with(mock_instance['name'],
                                                   update_connection=pipe_path)

    @mock.patch.object(vmops.VMOps, "log_vm_serial_output")
    @mock.patch("os.path.basename")
    @mock.patch("os.path.exists")
    def test_restart_vm_log_writers(self, mock_exists, mock_basename,
                                    mock_log_vm_output):
        self._vmops._vmutils.get_active_instances.return_value = [
            mock.sentinel.FAKE_VM_NAME, mock.sentinel.FAKE_VM_NAME_OTHER]
        mock_exists.side_effect = [True, False]

        self._vmops.restart_vm_log_writers()

        calls = [mock.call(mock.sentinel.FAKE_VM_NAME),
                 mock.call(mock.sentinel.FAKE_VM_NAME_OTHER)]
        self._vmops._pathutils.get_instance_dir.assert_has_calls(calls)
        get_vm_serial_port = self._vmops._vmutils.get_vm_serial_port_connection
        get_vm_serial_port.assert_called_once_with(mock.sentinel.FAKE_VM_NAME)
        mock_log_vm_output.assert_called_once_with(mock.sentinel.FAKE_VM_NAME,
                                                   mock_basename.return_value)

    def test_list_instance_uuids(self):
        fake_uuid = '4f54fb69-d3a2-45b7-bb9b-b6e6b3d893b3'
        with mock.patch.object(self._vmops._vmutils,
                               'list_instance_notes') as mock_list_notes:
            mock_list_notes.return_value = [('fake_name', [fake_uuid])]

            response = self._vmops.list_instance_uuids()
            mock_list_notes.assert_called_once_with()

        self.assertEqual(response, [fake_uuid])

    def test_copy_vm_dvd_disks(self):
        fake_paths = [mock.sentinel.FAKE_DVD_PATH1,
                      mock.sentinel.FAKE_DVD_PATH2]
        mock_copy = self._vmops._pathutils.copyfile
        mock_get_dvd_disk_paths = self._vmops._vmutils.get_vm_dvd_disk_paths
        mock_get_dvd_disk_paths.return_value = fake_paths
        self._vmops._pathutils.get_instance_dir.return_value = (
            mock.sentinel.FAKE_DEST_PATH)

        self._vmops.copy_vm_dvd_disks(mock.sentinel.FAKE_VM_NAME,
                                      mock.sentinel.FAKE_DEST_HOST)

        mock_get_dvd_disk_paths.assert_called_with(mock.sentinel.FAKE_VM_NAME)
        self._vmops._pathutils.get_instance_dir.assert_called_once_with(
            mock.sentinel.FAKE_VM_NAME,
            remote_server=mock.sentinel.FAKE_DEST_HOST)
        mock_copy.has_calls(mock.call(mock.sentinel.FAKE_DVD_PATH1,
                                      mock.sentinel.FAKE_DEST_PATH),
                            mock.call(mock.sentinel.FAKE_DVD_PATH2,
                                      mock.sentinel.FAKE_DEST_PATH))

    @mock.patch.object(vmops.VMOps, '_get_vm_state')
    def test_check_hotplug_available_vm_disabled(self, mock_get_vm_state):
        fake_vm = fake_instance.fake_instance_obj(self.context)
        mock_get_vm_state.return_value = constants.HYPERV_VM_STATE_DISABLED

        result = self._vmops._check_hotplug_available(fake_vm)

        self.assertTrue(result)
        mock_get_vm_state.assert_called_once_with(fake_vm.name)
        self.assertFalse(
            self._vmops._hostutils.check_min_windows_version.called)
        self.assertFalse(self._vmops._vmutils.get_vm_generation.called)

    @mock.patch.object(vmops.VMOps, '_get_vm_state')
    def _test_check_hotplug_available(
            self, mock_get_vm_state, expected_result=False,
            vm_gen=constants.VM_GEN_2, windows_version=_WIN_VERSION_10):

        fake_vm = fake_instance.fake_instance_obj(self.context)
        mock_get_vm_state.return_value = constants.HYPERV_VM_STATE_ENABLED
        self._vmops._vmutils.get_vm_generation.return_value = vm_gen
        fake_check_win_vers = self._vmops._hostutils.check_min_windows_version
        fake_check_win_vers.return_value = (
            windows_version == self._WIN_VERSION_10)

        result = self._vmops._check_hotplug_available(fake_vm)

        self.assertEqual(expected_result, result)
        mock_get_vm_state.assert_called_once_with(fake_vm.name)
        fake_check_win_vers.assert_called_once_with(10, 0)

    def test_check_if_hotplug_available(self):
        self._test_check_hotplug_available(expected_result=True)

    def test_check_if_hotplug_available_gen1(self):
        self._test_check_hotplug_available(
            expected_result=False, vm_gen=constants.VM_GEN_1)

    def test_check_if_hotplug_available_win_6_3(self):
        self._test_check_hotplug_available(
            expected_result=False, windows_version=self._WIN_VERSION_6_3)

    @mock.patch.object(vmops.VMOps, '_check_hotplug_available')
    def test_attach_interface(self, mock_check_hotplug_available):
        mock_check_hotplug_available.return_value = True
        fake_vm = fake_instance.fake_instance_obj(self.context)
        fake_vif = test_virtual_interface.fake_vif
        self._vmops._vif_driver = mock.MagicMock()

        self._vmops.attach_interface(fake_vm, fake_vif)

        mock_check_hotplug_available.assert_called_once_with(fake_vm)
        self._vmops._vif_driver.plug.assert_called_once_with(
            fake_vm, fake_vif)
        self._vmops._vmutils.create_nic.assert_called_once_with(
            fake_vm.name, fake_vif['id'], fake_vif['address'])

    @mock.patch.object(vmops.VMOps, '_check_hotplug_available')
    def test_attach_interface_failed(self, mock_check_hotplug_available):
        mock_check_hotplug_available.return_value = False
        self.assertRaises(exception.InterfaceAttachFailed,
                          self._vmops.attach_interface,
                          mock.MagicMock(), mock.sentinel.fake_vif)

    @mock.patch.object(vmops.VMOps, '_check_hotplug_available')
    def test_detach_interface(self, mock_check_hotplug_available):
        mock_check_hotplug_available.return_value = True
        fake_vm = fake_instance.fake_instance_obj(self.context)
        fake_vif = test_virtual_interface.fake_vif
        self._vmops._vif_driver = mock.MagicMock()

        self._vmops.detach_interface(fake_vm, fake_vif)

        mock_check_hotplug_available.assert_called_once_with(fake_vm)
        self._vmops._vif_driver.unplug.assert_called_once_with(
            fake_vm, fake_vif)
        self._vmops._vmutils.destroy_nic.assert_called_once_with(
            fake_vm.name, fake_vif['id'])

    @mock.patch.object(vmops.VMOps, '_check_hotplug_available')
    def test_detach_interface_failed(self, mock_check_hotplug_available):
        mock_check_hotplug_available.return_value = False
        self.assertRaises(exception.InterfaceDetachFailed,
                          self._vmops.detach_interface,
                          mock.MagicMock(), mock.sentinel.fake_vif)

    @mock.patch.object(vmops.VMOps, '_check_hotplug_available')
    def test_detach_interface_missing_instance(self, mock_check_hotplug):
        mock_check_hotplug.side_effect = os_win_exc.HyperVVMNotFoundException(
            vm_name='fake_vm')
        self.assertRaises(exception.InterfaceDetachFailed,
                          self._vmops.detach_interface,
                          mock.MagicMock(), mock.sentinel.fake_vif)

# Copyright (c) 2016 Cloudbase Solutions Srl
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
from os_win import constants as os_win_const

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import block_device_manager
from nova.virt.hyperv import constants


class BlockDeviceManagerTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V BlockDeviceInfoManager class."""

    def setUp(self):
        super(BlockDeviceManagerTestCase, self).setUp()
        self._bdman = block_device_manager.BlockDeviceInfoManager()

    def test_get_device_bus_scsi(self):
        bdm = {'disk_bus': constants.CTRL_TYPE_SCSI,
               'drive_addr': 0, 'ctrl_disk_addr': 2}

        bus = self._bdman._get_device_bus(bdm)
        self.assertEqual('0:0:0:2', bus.address)

    def test_get_device_bus_ide(self):
        bdm = {'disk_bus': constants.CTRL_TYPE_IDE,
               'drive_addr': 0, 'ctrl_disk_addr': 1}

        bus = self._bdman._get_device_bus(bdm)
        self.assertEqual('0:1', bus.address)

    @staticmethod
    def _bdm_mock(**kwargs):
        bdm = mock.MagicMock(**kwargs)
        bdm.__contains__.side_effect = (
            lambda attr: getattr(bdm, attr, None) is not None)
        return bdm

    @mock.patch.object(block_device_manager.objects, 'DiskMetadata')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_device_bus')
    @mock.patch.object(block_device_manager.objects.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_get_bdm_metadata(self, mock_get_by_inst_uuid, mock_get_device_bus,
                              mock_DiskMetadata):
        mock_instance = mock.MagicMock()
        root_disk = {'mount_device': mock.sentinel.dev0}
        ephemeral = {'device_name': mock.sentinel.dev1}
        block_device_info = {
            'root_disk': root_disk,
            'block_device_mapping': [
                {'mount_device': mock.sentinel.dev2},
                {'mount_device': mock.sentinel.dev3},
            ],
            'ephemerals': [ephemeral],
        }

        bdm = self._bdm_mock(device_name=mock.sentinel.dev0, tag='taggy',
                             volume_id=mock.sentinel.uuid1)
        eph = self._bdm_mock(device_name=mock.sentinel.dev1, tag='ephy',
                             volume_id=mock.sentinel.uuid2)
        mock_get_by_inst_uuid.return_value = [
            bdm, eph, self._bdm_mock(device_name=mock.sentinel.dev2, tag=None),
        ]

        bdm_metadata = self._bdman.get_bdm_metadata(mock.sentinel.context,
                                                    mock_instance,
                                                    block_device_info)

        mock_get_by_inst_uuid.assert_called_once_with(mock.sentinel.context,
                                                      mock_instance.uuid)
        mock_get_device_bus.assert_has_calls(
          [mock.call(root_disk), mock.call(ephemeral)], any_order=True)
        mock_DiskMetadata.assert_has_calls(
            [mock.call(bus=mock_get_device_bus.return_value,
                       serial=bdm.volume_id, tags=[bdm.tag]),
             mock.call(bus=mock_get_device_bus.return_value,
                       serial=eph.volume_id, tags=[eph.tag])],
            any_order=True)
        self.assertEqual([mock_DiskMetadata.return_value] * 2, bdm_metadata)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_init_controller_slot_counter_gen1_no_configdrive(
            self, mock_cfg_drive_req):
        mock_cfg_drive_req.return_value = False
        slot_map = self._bdman._initialize_controller_slot_counter(
            mock.sentinel.FAKE_INSTANCE, constants.VM_GEN_1)

        self.assertEqual(slot_map[constants.CTRL_TYPE_IDE][0],
                             os_win_const.IDE_CONTROLLER_SLOTS_NUMBER)
        self.assertEqual(slot_map[constants.CTRL_TYPE_IDE][1],
                         os_win_const.IDE_CONTROLLER_SLOTS_NUMBER)
        self.assertEqual(slot_map[constants.CTRL_TYPE_SCSI][0],
                         os_win_const.SCSI_CONTROLLER_SLOTS_NUMBER)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_init_controller_slot_counter_gen1(self, mock_cfg_drive_req):
        slot_map = self._bdman._initialize_controller_slot_counter(
            mock.sentinel.FAKE_INSTANCE, constants.VM_GEN_1)

        self.assertEqual(slot_map[constants.CTRL_TYPE_IDE][1],
                         os_win_const.IDE_CONTROLLER_SLOTS_NUMBER - 1)

    @mock.patch.object(block_device_manager.configdrive, 'required_by')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_initialize_controller_slot_counter')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_and_update_root_device')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_and_update_ephemerals')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_and_update_volumes')
    def _check_validate_and_update_bdi(self, mock_check_and_update_vol,
                                       mock_check_and_update_eph,
                                       mock_check_and_update_root,
                                       mock_init_ctrl_cntr,
                                       mock_required_by, available_slots=1):
        mock_required_by.return_value = True
        slot_map = {constants.CTRL_TYPE_SCSI: [available_slots]}
        mock_init_ctrl_cntr.return_value = slot_map

        if available_slots:
            self._bdman.validate_and_update_bdi(mock.sentinel.FAKE_INSTANCE,
                                                mock.sentinel.IMAGE_META,
                                                constants.VM_GEN_2,
                                                mock.sentinel.BLOCK_DEV_INFO)
        else:
            self.assertRaises(exception.InvalidBDMFormat,
                              self._bdman.validate_and_update_bdi,
                              mock.sentinel.FAKE_INSTANCE,
                              mock.sentinel.IMAGE_META,
                              constants.VM_GEN_2,
                              mock.sentinel.BLOCK_DEV_INFO)

        mock_init_ctrl_cntr.assert_called_once_with(
            mock.sentinel.FAKE_INSTANCE, constants.VM_GEN_2)
        mock_check_and_update_root.assert_called_once_with(
            constants.VM_GEN_2, mock.sentinel.IMAGE_META,
            mock.sentinel.BLOCK_DEV_INFO, slot_map)
        mock_check_and_update_eph.assert_called_once_with(
            constants.VM_GEN_2, mock.sentinel.BLOCK_DEV_INFO, slot_map)
        mock_check_and_update_vol.assert_called_once_with(
            constants.VM_GEN_2, mock.sentinel.BLOCK_DEV_INFO, slot_map)
        mock_required_by.assert_called_once_with(mock.sentinel.FAKE_INSTANCE)

    def test_validate_and_update_bdi(self):
        self._check_validate_and_update_bdi()

    def test_validate_and_update_bdi_insufficient_slots(self):
        self._check_validate_and_update_bdi(available_slots=0)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_available_controller_slot')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       'is_boot_from_volume')
    def _test_check_and_update_root_device(self, mock_is_boot_from_vol,
                                           mock_get_avail_ctrl_slot,
                                           disk_format,
                                           vm_gen=constants.VM_GEN_1,
                                           boot_from_volume=False):
        image_meta = mock.MagicMock(disk_format=disk_format)
        bdi = {'root_device': '/dev/sda',
               'block_device_mapping': [
                    {'mount_device': '/dev/sda',
                     'connection_info': mock.sentinel.FAKE_CONN_INFO}]}

        mock_is_boot_from_vol.return_value = boot_from_volume
        mock_get_avail_ctrl_slot.return_value = (0, 0)

        self._bdman._check_and_update_root_device(vm_gen, image_meta, bdi,
                                                  mock.sentinel.SLOT_MAP)

        root_disk = bdi['root_disk']
        if boot_from_volume:
            self.assertEqual(root_disk['type'], constants.VOLUME)
            self.assertIsNone(root_disk['path'])
            self.assertEqual(root_disk['connection_info'],
                             mock.sentinel.FAKE_CONN_INFO)
        else:
            image_type = self._bdman._TYPE_FOR_DISK_FORMAT.get(
                image_meta.disk_format)
            self.assertEqual(root_disk['type'], image_type)
            self.assertIsNone(root_disk['path'])
            self.assertIsNone(root_disk['connection_info'])

        disk_bus = (constants.CTRL_TYPE_IDE if
            vm_gen == constants.VM_GEN_1 else constants.CTRL_TYPE_SCSI)
        self.assertEqual(root_disk['disk_bus'], disk_bus)
        self.assertEqual(root_disk['drive_addr'], 0)
        self.assertEqual(root_disk['ctrl_disk_addr'], 0)
        self.assertEqual(root_disk['boot_index'], 0)
        self.assertEqual(root_disk['mount_device'], bdi['root_device'])
        mock_get_avail_ctrl_slot.assert_called_once_with(
            root_disk['disk_bus'], mock.sentinel.SLOT_MAP)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       'is_boot_from_volume', return_value=False)
    def test_check_and_update_root_device_exception(self, mock_is_boot_vol):
        bdi = {}
        image_meta = mock.MagicMock(disk_format=mock.sentinel.fake_format)

        self.assertRaises(exception.InvalidImageFormat,
                          self._bdman._check_and_update_root_device,
                          constants.VM_GEN_1, image_meta, bdi,
                          mock.sentinel.SLOT_MAP)

    def test_check_and_update_root_device_gen1(self):
        self._test_check_and_update_root_device(disk_format='vhd')

    def test_check_and_update_root_device_gen1_vhdx(self):
        self._test_check_and_update_root_device(disk_format='vhdx')

    def test_check_and_update_root_device_gen1_iso(self):
        self._test_check_and_update_root_device(disk_format='iso')

    def test_check_and_update_root_device_gen2(self):
        self._test_check_and_update_root_device(disk_format='vhd',
                                                vm_gen=constants.VM_GEN_2)

    def test_check_and_update_root_device_boot_from_vol_gen1(self):
        self._test_check_and_update_root_device(disk_format='vhd',
                                                boot_from_volume=True)

    def test_check_and_update_root_device_boot_from_vol_gen2(self):
        self._test_check_and_update_root_device(disk_format='vhd',
                                                vm_gen=constants.VM_GEN_2,
                                                boot_from_volume=True)

    @mock.patch('nova.virt.configdrive.required_by', return_value=True)
    def _test_get_available_controller_slot(self, mock_config_drive_req,
                                            bus=constants.CTRL_TYPE_IDE,
                                            fail=False):

        slot_map = self._bdman._initialize_controller_slot_counter(
            mock.sentinel.FAKE_VM, constants.VM_GEN_1)

        if fail:
            slot_map[constants.CTRL_TYPE_IDE][0] = 0
            slot_map[constants.CTRL_TYPE_IDE][1] = 0
            self.assertRaises(exception.InvalidBDMFormat,
                              self._bdman._get_available_controller_slot,
                              constants.CTRL_TYPE_IDE,
                              slot_map)
        else:
            (disk_addr,
             ctrl_disk_addr) = self._bdman._get_available_controller_slot(
                bus, slot_map)

            self.assertEqual(0, disk_addr)
            self.assertEqual(0, ctrl_disk_addr)

    def test_get_available_controller_slot(self):
        self._test_get_available_controller_slot()

    def test_get_available_controller_slot_scsi_ctrl(self):
        self._test_get_available_controller_slot(bus=constants.CTRL_TYPE_SCSI)

    def test_get_available_controller_slot_exception(self):
        self._test_get_available_controller_slot(fail=True)

    def test_is_boot_from_volume_true(self):
        vol = {'mount_device': self._bdman._DEFAULT_ROOT_DEVICE}
        block_device_info = {'block_device_mapping': [vol]}
        ret = self._bdman.is_boot_from_volume(block_device_info)

        self.assertTrue(ret)

    def test_is_boot_from_volume_false(self):
        block_device_info = {'block_device_mapping': []}
        ret = self._bdman.is_boot_from_volume(block_device_info)

        self.assertFalse(ret)

    def test_get_root_device_bdm(self):
        mount_device = '/dev/sda'
        bdm1 = {'mount_device': None}
        bdm2 = {'mount_device': mount_device}
        bdi = {'block_device_mapping': [bdm1, bdm2]}

        ret = self._bdman._get_root_device_bdm(bdi, mount_device)

        self.assertEqual(bdm2, ret)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_and_update_bdm')
    def test_check_and_update_ephemerals(self, mock_check_and_update_bdm):
        fake_ephemerals = [mock.sentinel.eph1, mock.sentinel.eph2,
                           mock.sentinel.eph3]
        fake_bdi = {'ephemerals': fake_ephemerals}
        expected_calls = []
        for eph in fake_ephemerals:
            expected_calls.append(mock.call(mock.sentinel.fake_slot_map,
                                            mock.sentinel.fake_vm_gen,
                                            eph))
        self._bdman._check_and_update_ephemerals(mock.sentinel.fake_vm_gen,
                                                 fake_bdi,
                                                 mock.sentinel.fake_slot_map)
        mock_check_and_update_bdm.assert_has_calls(expected_calls)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_and_update_bdm')
    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_root_device_bdm')
    def test_check_and_update_volumes(self, mock_get_root_dev_bdm,
                                      mock_check_and_update_bdm):
        fake_vol1 = {'mount_device': '/dev/sda'}
        fake_vol2 = {'mount_device': '/dev/sdb'}
        fake_volumes = [fake_vol1, fake_vol2]
        fake_bdi = {'block_device_mapping': fake_volumes,
                    'root_disk': {'mount_device': '/dev/sda'}}
        mock_get_root_dev_bdm.return_value = fake_vol1

        self._bdman._check_and_update_volumes(mock.sentinel.fake_vm_gen,
                                              fake_bdi,
                                              mock.sentinel.fake_slot_map)

        mock_get_root_dev_bdm.assert_called_once_with(fake_bdi, '/dev/sda')
        mock_check_and_update_bdm.assert_called_once_with(
            mock.sentinel.fake_slot_map, mock.sentinel.fake_vm_gen, fake_vol2)
        self.assertNotIn(fake_vol1, fake_bdi)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_available_controller_slot')
    def test_check_and_update_bdm_with_defaults(self, mock_get_ctrl_slot):
        mock_get_ctrl_slot.return_value = ((mock.sentinel.DRIVE_ADDR,
                                            mock.sentinel.CTRL_DISK_ADDR))
        bdm = {'device_type': None,
               'disk_bus': None,
               'boot_index': None}

        self._bdman._check_and_update_bdm(mock.sentinel.FAKE_SLOT_MAP,
                                          constants.VM_GEN_1, bdm)

        mock_get_ctrl_slot.assert_called_once_with(
          bdm['disk_bus'], mock.sentinel.FAKE_SLOT_MAP)
        self.assertEqual(mock.sentinel.DRIVE_ADDR, bdm['drive_addr'])
        self.assertEqual(mock.sentinel.CTRL_DISK_ADDR, bdm['ctrl_disk_addr'])
        self.assertEqual('disk', bdm['device_type'])
        self.assertEqual(self._bdman._DEFAULT_BUS, bdm['disk_bus'])
        self.assertIsNone(bdm['boot_index'])

    def test_check_and_update_bdm_exception_device_type(self):
        bdm = {'device_type': 'cdrom',
               'disk_bus': 'IDE'}

        self.assertRaises(exception.InvalidDiskInfo,
                          self._bdman._check_and_update_bdm,
                          mock.sentinel.FAKE_SLOT_MAP, constants.VM_GEN_1, bdm)

    def test_check_and_update_bdm_exception_disk_bus(self):
        bdm = {'device_type': 'disk',
               'disk_bus': 'fake_bus'}

        self.assertRaises(exception.InvalidDiskInfo,
                          self._bdman._check_and_update_bdm,
                          mock.sentinel.FAKE_SLOT_MAP, constants.VM_GEN_1, bdm)

    def test_sort_by_boot_order(self):
        original = [{'boot_index': 2}, {'boot_index': None}, {'boot_index': 1}]
        expected = [original[2], original[0], original[1]]

        self._bdman._sort_by_boot_order(original)
        self.assertEqual(expected, original)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_boot_order_gen1')
    def test_get_boot_order_gen1_vm(self, mock_get_boot_order):
        self._bdman.get_boot_order(constants.VM_GEN_1,
                                   mock.sentinel.BLOCK_DEV_INFO)
        mock_get_boot_order.assert_called_once_with(
            mock.sentinel.BLOCK_DEV_INFO)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_get_boot_order_gen2')
    def test_get_boot_order_gen2_vm(self, mock_get_boot_order):
        self._bdman.get_boot_order(constants.VM_GEN_2,
                                   mock.sentinel.BLOCK_DEV_INFO)
        mock_get_boot_order.assert_called_once_with(
            mock.sentinel.BLOCK_DEV_INFO)

    def test_get_boot_order_gen1_iso(self):
        fake_bdi = {'root_disk': {'type': 'iso'}}
        expected = [os_win_const.BOOT_DEVICE_CDROM,
                    os_win_const.BOOT_DEVICE_HARDDISK,
                    os_win_const.BOOT_DEVICE_NETWORK,
                    os_win_const.BOOT_DEVICE_FLOPPY]

        res = self._bdman._get_boot_order_gen1(fake_bdi)
        self.assertEqual(expected, res)

    def test_get_boot_order_gen1_vhd(self):
        fake_bdi = {'root_disk': {'type': 'vhd'}}
        expected = [os_win_const.BOOT_DEVICE_HARDDISK,
                    os_win_const.BOOT_DEVICE_CDROM,
                    os_win_const.BOOT_DEVICE_NETWORK,
                    os_win_const.BOOT_DEVICE_FLOPPY]

        res = self._bdman._get_boot_order_gen1(fake_bdi)
        self.assertEqual(expected, res)

    @mock.patch('nova.virt.hyperv.volumeops.VolumeOps.get_disk_resource_path')
    def test_get_boot_order_gen2(self, mock_get_disk_path):
        fake_root_disk = {'boot_index': 0,
                          'path': mock.sentinel.FAKE_ROOT_PATH}
        fake_eph1 = {'boot_index': 2,
                     'path': mock.sentinel.FAKE_EPH_PATH1}
        fake_eph2 = {'boot_index': 3,
                     'path': mock.sentinel.FAKE_EPH_PATH2}
        fake_bdm = {'boot_index': 1,
                    'connection_info': mock.sentinel.FAKE_CONN_INFO}
        fake_bdi = {'root_disk': fake_root_disk,
                    'ephemerals': [fake_eph1,
                                   fake_eph2],
                    'block_device_mapping': [fake_bdm]}

        mock_get_disk_path.return_value = fake_bdm['connection_info']

        expected_res = [mock.sentinel.FAKE_ROOT_PATH,
                        mock.sentinel.FAKE_CONN_INFO,
                        mock.sentinel.FAKE_EPH_PATH1,
                        mock.sentinel.FAKE_EPH_PATH2]

        res = self._bdman._get_boot_order_gen2(fake_bdi)

        self.assertEqual(expected_res, res)

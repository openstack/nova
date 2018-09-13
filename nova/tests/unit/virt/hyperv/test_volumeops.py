# Copyright 2014 Cloudbase Solutions Srl
#
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
from os_brick.initiator import connector
from oslo_config import cfg
from oslo_utils import units

from nova import exception
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import volumeops

CONF = cfg.CONF

connection_data = {'volume_id': 'fake_vol_id',
                   'target_lun': mock.sentinel.fake_lun,
                   'target_iqn': mock.sentinel.fake_iqn,
                   'target_portal': mock.sentinel.fake_portal,
                   'auth_method': 'chap',
                   'auth_username': mock.sentinel.fake_user,
                   'auth_password': mock.sentinel.fake_pass}


def get_fake_block_dev_info():
    return {'block_device_mapping': [
        fake_block_device.AnonFakeDbBlockDeviceDict({'source_type': 'volume'})]
    }


def get_fake_connection_info(**kwargs):
    return {'data': dict(connection_data, **kwargs),
            'serial': mock.sentinel.serial}


class VolumeOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for VolumeOps class."""

    def setUp(self):
        super(VolumeOpsTestCase, self).setUp()
        self._volumeops = volumeops.VolumeOps()
        self._volumeops._volutils = mock.MagicMock()
        self._volumeops._vmutils = mock.Mock()

    def test_get_volume_driver(self):
        fake_conn_info = {'driver_volume_type': mock.sentinel.fake_driver_type}
        self._volumeops.volume_drivers[mock.sentinel.fake_driver_type] = (
            mock.sentinel.fake_driver)

        result = self._volumeops._get_volume_driver(
            connection_info=fake_conn_info)
        self.assertEqual(mock.sentinel.fake_driver, result)

    def test_get_volume_driver_exception(self):
        fake_conn_info = {'driver_volume_type': 'fake_driver'}
        self.assertRaises(exception.VolumeDriverNotFound,
                          self._volumeops._get_volume_driver,
                          connection_info=fake_conn_info)

    @mock.patch.object(volumeops.VolumeOps, 'attach_volume')
    def test_attach_volumes(self, mock_attach_volume):
        block_device_info = get_fake_block_dev_info()

        self._volumeops.attach_volumes(
            block_device_info['block_device_mapping'],
            mock.sentinel.instance_name)

        mock_attach_volume.assert_called_once_with(
            block_device_info['block_device_mapping'][0]['connection_info'],
            mock.sentinel.instance_name)

    def test_fix_instance_volume_disk_paths_empty_bdm(self):
        self._volumeops.fix_instance_volume_disk_paths(
            mock.sentinel.instance_name,
            block_device_info={})
        self.assertFalse(
            self._volumeops._vmutils.get_vm_physical_disk_mapping.called)

    @mock.patch.object(volumeops.VolumeOps, 'get_disk_path_mapping')
    def test_fix_instance_volume_disk_paths(self, mock_get_disk_path_mapping):
        block_device_info = get_fake_block_dev_info()

        mock_disk1 = {
            'mounted_disk_path': mock.sentinel.mounted_disk1_path,
            'resource_path': mock.sentinel.resource1_path
        }
        mock_disk2 = {
            'mounted_disk_path': mock.sentinel.mounted_disk2_path,
            'resource_path': mock.sentinel.resource2_path
        }

        mock_vm_disk_mapping = {
            mock.sentinel.disk1_serial: mock_disk1,
            mock.sentinel.disk2_serial: mock_disk2
        }
        # In this case, only the first disk needs to be updated.
        mock_phys_disk_path_mapping = {
            mock.sentinel.disk1_serial: mock.sentinel.actual_disk1_path,
            mock.sentinel.disk2_serial: mock.sentinel.mounted_disk2_path
        }

        vmutils = self._volumeops._vmutils
        vmutils.get_vm_physical_disk_mapping.return_value = (
            mock_vm_disk_mapping)

        mock_get_disk_path_mapping.return_value = mock_phys_disk_path_mapping

        self._volumeops.fix_instance_volume_disk_paths(
            mock.sentinel.instance_name,
            block_device_info)

        vmutils.get_vm_physical_disk_mapping.assert_called_once_with(
            mock.sentinel.instance_name)
        mock_get_disk_path_mapping.assert_called_once_with(
            block_device_info)
        vmutils.set_disk_host_res.assert_called_once_with(
            mock.sentinel.resource1_path,
            mock.sentinel.actual_disk1_path)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_disconnect_volumes(self, mock_get_volume_driver):
        block_device_info = get_fake_block_dev_info()
        block_device_mapping = block_device_info['block_device_mapping']
        fake_volume_driver = mock_get_volume_driver.return_value

        self._volumeops.disconnect_volumes(block_device_info)
        fake_volume_driver.disconnect_volume.assert_called_once_with(
            block_device_mapping[0]['connection_info'])

    @mock.patch('time.sleep')
    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def _test_attach_volume(self, mock_get_volume_driver, mock_sleep,
                            attach_failed):
        fake_conn_info = get_fake_connection_info(
            qos_specs=mock.sentinel.qos_specs)
        fake_volume_driver = mock_get_volume_driver.return_value

        expected_try_count = 1
        if attach_failed:
            expected_try_count += CONF.hyperv.volume_attach_retry_count

            fake_volume_driver.set_disk_qos_specs.side_effect = (
                test.TestingException)

            self.assertRaises(exception.VolumeAttachFailed,
                              self._volumeops.attach_volume,
                              fake_conn_info,
                              mock.sentinel.inst_name,
                              mock.sentinel.disk_bus)
        else:
            self._volumeops.attach_volume(
                fake_conn_info,
                mock.sentinel.inst_name,
                mock.sentinel.disk_bus)

        mock_get_volume_driver.assert_any_call(
            fake_conn_info)
        fake_volume_driver.attach_volume.assert_has_calls(
            [mock.call(fake_conn_info,
                       mock.sentinel.inst_name,
                       mock.sentinel.disk_bus)] * expected_try_count)
        fake_volume_driver.set_disk_qos_specs.assert_has_calls(
            [mock.call(fake_conn_info,
                       mock.sentinel.qos_specs)] * expected_try_count)

        if attach_failed:
            fake_volume_driver.disconnect_volume.assert_called_once_with(
                fake_conn_info)
            mock_sleep.assert_has_calls(
                [mock.call(CONF.hyperv.volume_attach_retry_interval)] *
                    CONF.hyperv.volume_attach_retry_count)
        else:
            mock_sleep.assert_not_called()

    def test_attach_volume(self):
        self._test_attach_volume(attach_failed=False)

    def test_attach_volume_exc(self):
        self._test_attach_volume(attach_failed=True)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_disconnect_volume(self, mock_get_volume_driver):
        fake_volume_driver = mock_get_volume_driver.return_value

        self._volumeops.disconnect_volume(mock.sentinel.conn_info)

        mock_get_volume_driver.assert_called_once_with(
            mock.sentinel.conn_info)
        fake_volume_driver.disconnect_volume.assert_called_once_with(
            mock.sentinel.conn_info)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_detach_volume(self, mock_get_volume_driver):
        fake_volume_driver = mock_get_volume_driver.return_value
        fake_conn_info = {'data': 'fake_conn_info_data'}

        self._volumeops.detach_volume(fake_conn_info,
                                      mock.sentinel.inst_name)

        mock_get_volume_driver.assert_called_once_with(
            fake_conn_info)
        fake_volume_driver.detach_volume.assert_called_once_with(
            fake_conn_info, mock.sentinel.inst_name)
        fake_volume_driver.disconnect_volume.assert_called_once_with(
            fake_conn_info)

    @mock.patch.object(connector, 'get_connector_properties')
    def test_get_volume_connector(self, mock_get_connector):
        conn = self._volumeops.get_volume_connector()

        mock_get_connector.assert_called_once_with(
            root_helper=None,
            my_ip=CONF.my_block_storage_ip,
            multipath=CONF.hyperv.use_multipath_io,
            enforce_multipath=True,
            host=CONF.host)
        self.assertEqual(mock_get_connector.return_value, conn)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_connect_volumes(self, mock_get_volume_driver):
        block_device_info = get_fake_block_dev_info()

        self._volumeops.connect_volumes(block_device_info)

        init_vol_conn = (
            mock_get_volume_driver.return_value.connect_volume)
        init_vol_conn.assert_called_once_with(
            block_device_info['block_device_mapping'][0]['connection_info'])

    @mock.patch.object(volumeops.VolumeOps,
                       'get_disk_resource_path')
    def test_get_disk_path_mapping(self, mock_get_disk_path):
        block_device_info = get_fake_block_dev_info()
        block_device_mapping = block_device_info['block_device_mapping']
        fake_conn_info = get_fake_connection_info()
        block_device_mapping[0]['connection_info'] = fake_conn_info

        mock_get_disk_path.return_value = mock.sentinel.disk_path

        resulted_disk_path_mapping = self._volumeops.get_disk_path_mapping(
            block_device_info)

        mock_get_disk_path.assert_called_once_with(fake_conn_info)
        expected_disk_path_mapping = {
            mock.sentinel.serial: mock.sentinel.disk_path
        }
        self.assertEqual(expected_disk_path_mapping,
                         resulted_disk_path_mapping)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_get_disk_resource_path(self, mock_get_volume_driver):
        fake_conn_info = get_fake_connection_info()
        fake_volume_driver = mock_get_volume_driver.return_value

        resulted_disk_path = self._volumeops.get_disk_resource_path(
            fake_conn_info)

        mock_get_volume_driver.assert_called_once_with(fake_conn_info)
        get_mounted_disk = fake_volume_driver.get_disk_resource_path
        get_mounted_disk.assert_called_once_with(fake_conn_info)
        self.assertEqual(get_mounted_disk.return_value,
                         resulted_disk_path)

    def test_bytes_per_sec_to_iops(self):
        no_bytes = 15 * units.Ki
        expected_iops = 2

        resulted_iops = self._volumeops.bytes_per_sec_to_iops(no_bytes)
        self.assertEqual(expected_iops, resulted_iops)

    @mock.patch.object(volumeops.LOG, 'warning')
    def test_validate_qos_specs(self, mock_warning):
        supported_qos_specs = [mock.sentinel.spec1, mock.sentinel.spec2]
        requested_qos_specs = {mock.sentinel.spec1: mock.sentinel.val,
                               mock.sentinel.spec3: mock.sentinel.val2}

        self._volumeops.validate_qos_specs(requested_qos_specs,
                                           supported_qos_specs)
        self.assertTrue(mock_warning.called)


class BaseVolumeDriverTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for Hyper-V BaseVolumeDriver class."""

    def setUp(self):
        super(BaseVolumeDriverTestCase, self).setUp()

        self._base_vol_driver = volumeops.BaseVolumeDriver()

        self._base_vol_driver._diskutils = mock.Mock()
        self._base_vol_driver._vmutils = mock.Mock()
        self._base_vol_driver._migrutils = mock.Mock()
        self._base_vol_driver._conn = mock.Mock()
        self._vmutils = self._base_vol_driver._vmutils
        self._migrutils = self._base_vol_driver._migrutils
        self._diskutils = self._base_vol_driver._diskutils
        self._conn = self._base_vol_driver._conn

    @mock.patch.object(connector.InitiatorConnector, 'factory')
    def test_connector(self, mock_conn_factory):
        self._base_vol_driver._conn = None
        self._base_vol_driver._protocol = mock.sentinel.protocol
        self._base_vol_driver._extra_connector_args = dict(
            fake_conn_arg=mock.sentinel.conn_val)

        conn = self._base_vol_driver._connector

        self.assertEqual(mock_conn_factory.return_value, conn)
        mock_conn_factory.assert_called_once_with(
            protocol=mock.sentinel.protocol,
            root_helper=None,
            use_multipath=CONF.hyperv.use_multipath_io,
            device_scan_attempts=CONF.hyperv.mounted_disk_query_retry_count,
            device_scan_interval=(
                CONF.hyperv.mounted_disk_query_retry_interval),
            **self._base_vol_driver._extra_connector_args)

    def test_connect_volume(self):
        conn_info = get_fake_connection_info()

        dev_info = self._base_vol_driver.connect_volume(conn_info)
        expected_dev_info = self._conn.connect_volume.return_value

        self.assertEqual(expected_dev_info, dev_info)
        self._conn.connect_volume.assert_called_once_with(
            conn_info['data'])

    def test_disconnect_volume(self):
        conn_info = get_fake_connection_info()

        self._base_vol_driver.disconnect_volume(conn_info)

        self._conn.disconnect_volume.assert_called_once_with(
            conn_info['data'])

    @mock.patch.object(volumeops.BaseVolumeDriver, '_get_disk_res_path')
    def _test_get_disk_resource_path_by_conn_info(self,
                                                  mock_get_disk_res_path,
                                                  disk_found=True):
        conn_info = get_fake_connection_info()
        mock_vol_paths = [mock.sentinel.disk_path] if disk_found else []
        self._conn.get_volume_paths.return_value = mock_vol_paths

        if disk_found:
            disk_res_path = self._base_vol_driver.get_disk_resource_path(
                conn_info)

            self._conn.get_volume_paths.assert_called_once_with(
                conn_info['data'])
            self.assertEqual(mock_get_disk_res_path.return_value,
                             disk_res_path)
            mock_get_disk_res_path.assert_called_once_with(
                mock.sentinel.disk_path)
        else:
            self.assertRaises(exception.DiskNotFound,
                              self._base_vol_driver.get_disk_resource_path,
                              conn_info)

    def test_get_existing_disk_res_path(self):
        self._test_get_disk_resource_path_by_conn_info()

    def test_get_unfound_disk_res_path(self):
        self._test_get_disk_resource_path_by_conn_info(disk_found=False)

    def test_get_block_dev_res_path(self):
        self._base_vol_driver._is_block_dev = True

        mock_get_dev_number = (
            self._diskutils.get_device_number_from_device_name)
        mock_get_dev_number.return_value = mock.sentinel.dev_number
        self._vmutils.get_mounted_disk_by_drive_number.return_value = (
            mock.sentinel.disk_path)

        disk_path = self._base_vol_driver._get_disk_res_path(
            mock.sentinel.dev_name)

        mock_get_dev_number.assert_called_once_with(mock.sentinel.dev_name)
        self._vmutils.get_mounted_disk_by_drive_number.assert_called_once_with(
            mock.sentinel.dev_number)

        self.assertEqual(mock.sentinel.disk_path, disk_path)

    def test_get_virt_disk_res_path(self):
        # For virtual disk images, we expect the resource path to be the
        # actual image path, as opposed to passthrough disks, in which case we
        # need the Msvm_DiskDrive resource path when attaching it to a VM.
        self._base_vol_driver._is_block_dev = False

        path = self._base_vol_driver._get_disk_res_path(
            mock.sentinel.disk_path)
        self.assertEqual(mock.sentinel.disk_path, path)

    @mock.patch.object(volumeops.BaseVolumeDriver,
                       '_get_disk_res_path')
    @mock.patch.object(volumeops.BaseVolumeDriver, '_get_disk_ctrl_and_slot')
    @mock.patch.object(volumeops.BaseVolumeDriver,
                       'connect_volume')
    def _test_attach_volume(self, mock_connect_volume,
                            mock_get_disk_ctrl_and_slot,
                            mock_get_disk_res_path,
                            is_block_dev=True):
        connection_info = get_fake_connection_info()
        self._base_vol_driver._is_block_dev = is_block_dev
        mock_connect_volume.return_value = dict(path=mock.sentinel.raw_path)

        mock_get_disk_res_path.return_value = (
            mock.sentinel.disk_path)
        mock_get_disk_ctrl_and_slot.return_value = (
            mock.sentinel.ctrller_path,
            mock.sentinel.slot)

        self._base_vol_driver.attach_volume(
            connection_info=connection_info,
            instance_name=mock.sentinel.instance_name,
            disk_bus=mock.sentinel.disk_bus)

        if is_block_dev:
            self._vmutils.attach_volume_to_controller.assert_called_once_with(
                mock.sentinel.instance_name,
                mock.sentinel.ctrller_path,
                mock.sentinel.slot,
                mock.sentinel.disk_path,
                serial=connection_info['serial'])
        else:
            self._vmutils.attach_drive.assert_called_once_with(
                mock.sentinel.instance_name,
                mock.sentinel.disk_path,
                mock.sentinel.ctrller_path,
                mock.sentinel.slot)

        mock_get_disk_res_path.assert_called_once_with(
            mock.sentinel.raw_path)
        mock_get_disk_ctrl_and_slot.assert_called_once_with(
            mock.sentinel.instance_name, mock.sentinel.disk_bus)

    def test_attach_volume_image_file(self):
        self._test_attach_volume(is_block_dev=False)

    def test_attach_volume_block_dev(self):
        self._test_attach_volume(is_block_dev=True)

    def test_detach_volume_planned_vm(self):
        self._base_vol_driver.detach_volume(mock.sentinel.connection_info,
                                            mock.sentinel.inst_name)
        self._vmutils.detach_vm_disk.assert_not_called()

    @mock.patch.object(volumeops.BaseVolumeDriver,
                       'get_disk_resource_path')
    def test_detach_volume(self, mock_get_disk_resource_path):
        self._migrutils.planned_vm_exists.return_value = False
        connection_info = get_fake_connection_info()

        self._base_vol_driver.detach_volume(connection_info,
                                            mock.sentinel.instance_name)

        mock_get_disk_resource_path.assert_called_once_with(
            connection_info)
        self._vmutils.detach_vm_disk.assert_called_once_with(
            mock.sentinel.instance_name,
            mock_get_disk_resource_path.return_value,
            is_physical=self._base_vol_driver._is_block_dev)

    def test_get_disk_ctrl_and_slot_ide(self):
        ctrl, slot = self._base_vol_driver._get_disk_ctrl_and_slot(
            mock.sentinel.instance_name,
            disk_bus=constants.CTRL_TYPE_IDE)

        expected_ctrl = self._vmutils.get_vm_ide_controller.return_value
        expected_slot = 0

        self._vmutils.get_vm_ide_controller.assert_called_once_with(
            mock.sentinel.instance_name, 0)

        self.assertEqual(expected_ctrl, ctrl)
        self.assertEqual(expected_slot, slot)

    def test_get_disk_ctrl_and_slot_scsi(self):
        ctrl, slot = self._base_vol_driver._get_disk_ctrl_and_slot(
            mock.sentinel.instance_name,
            disk_bus=constants.CTRL_TYPE_SCSI)

        expected_ctrl = self._vmutils.get_vm_scsi_controller.return_value
        expected_slot = (
            self._vmutils.get_free_controller_slot.return_value)

        self._vmutils.get_vm_scsi_controller.assert_called_once_with(
            mock.sentinel.instance_name)
        self._vmutils.get_free_controller_slot(
           self._vmutils.get_vm_scsi_controller.return_value)

        self.assertEqual(expected_ctrl, ctrl)
        self.assertEqual(expected_slot, slot)

    def test_set_disk_qos_specs(self):
        # This base method is a noop, we'll just make sure
        # it doesn't error out.
        self._base_vol_driver.set_disk_qos_specs(
            mock.sentinel.conn_info, mock.sentinel.disk_qos_spes)


class ISCSIVolumeDriverTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for Hyper-V BaseVolumeDriver class."""

    def test_extra_conn_args(self):
        fake_iscsi_initiator = (
            'PCI\\VEN_1077&DEV_2031&SUBSYS_17E8103C&REV_02\\'
            '4&257301f0&0&0010_0')
        self.flags(iscsi_initiator_list=[fake_iscsi_initiator],
                   group='hyperv')
        expected_extra_conn_args = dict(
            initiator_list=[fake_iscsi_initiator])

        vol_driver = volumeops.ISCSIVolumeDriver()

        self.assertEqual(expected_extra_conn_args,
                         vol_driver._extra_connector_args)


class SMBFSVolumeDriverTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V SMBFSVolumeDriver class."""

    _FAKE_EXPORT_PATH = '//ip/share/'
    _FAKE_CONN_INFO = get_fake_connection_info(export=_FAKE_EXPORT_PATH)

    def setUp(self):
        super(SMBFSVolumeDriverTestCase, self).setUp()
        self._volume_driver = volumeops.SMBFSVolumeDriver()
        self._volume_driver._conn = mock.Mock()
        self._conn = self._volume_driver._conn

    def test_get_export_path(self):
        export_path = self._volume_driver._get_export_path(
            self._FAKE_CONN_INFO)
        expected_path = self._FAKE_EXPORT_PATH.replace('/', '\\')
        self.assertEqual(expected_path, export_path)

    @mock.patch.object(volumeops.BaseVolumeDriver, 'attach_volume')
    def test_attach_volume(self, mock_attach):
        # The tested method will just apply a lock before calling
        # the superclass method.
        self._volume_driver.attach_volume(
            self._FAKE_CONN_INFO,
            mock.sentinel.instance_name,
            disk_bus=mock.sentinel.disk_bus)

        mock_attach.assert_called_once_with(
            self._FAKE_CONN_INFO,
            mock.sentinel.instance_name,
            disk_bus=mock.sentinel.disk_bus)

    @mock.patch.object(volumeops.BaseVolumeDriver, 'detach_volume')
    def test_detach_volume(self, mock_detach):
        self._volume_driver.detach_volume(
            self._FAKE_CONN_INFO,
            instance_name=mock.sentinel.instance_name)

        mock_detach.assert_called_once_with(
            self._FAKE_CONN_INFO,
            instance_name=mock.sentinel.instance_name)

    @mock.patch.object(volumeops.VolumeOps, 'bytes_per_sec_to_iops')
    @mock.patch.object(volumeops.VolumeOps, 'validate_qos_specs')
    @mock.patch.object(volumeops.BaseVolumeDriver, 'get_disk_resource_path')
    def test_set_disk_qos_specs(self, mock_get_disk_path,
                                mock_validate_qos_specs,
                                mock_bytes_per_sec_to_iops):
        fake_total_bytes_sec = 8
        fake_total_iops_sec = 1

        storage_qos_specs = {'total_bytes_sec': fake_total_bytes_sec}
        expected_supported_specs = ['total_iops_sec', 'total_bytes_sec']
        mock_set_qos_specs = self._volume_driver._vmutils.set_disk_qos_specs
        mock_bytes_per_sec_to_iops.return_value = fake_total_iops_sec
        mock_get_disk_path.return_value = mock.sentinel.disk_path

        self._volume_driver.set_disk_qos_specs(self._FAKE_CONN_INFO,
                                               storage_qos_specs)

        mock_validate_qos_specs.assert_called_once_with(
            storage_qos_specs, expected_supported_specs)
        mock_bytes_per_sec_to_iops.assert_called_once_with(
            fake_total_bytes_sec)
        mock_get_disk_path.assert_called_once_with(self._FAKE_CONN_INFO)
        mock_set_qos_specs.assert_called_once_with(
            mock.sentinel.disk_path,
            fake_total_iops_sec)

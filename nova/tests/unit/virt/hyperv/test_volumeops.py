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

import os

import mock
from os_win import exceptions as os_win_exc
from oslo_config import cfg

from nova import exception
from nova import test
from nova.tests.unit import fake_block_device
from nova.tests.unit.virt.hyperv import test_base
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

        self._volumeops.attach_volumes(block_device_info,
                                       mock.sentinel.instance_name,
                                       ebs_root=True)

        mock_attach_volume.assert_called_once_with(
            block_device_info['block_device_mapping'][0]['connection_info'],
            mock.sentinel.instance_name, True)

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
        block_device_mapping[0]['connection_info'] = {
            'driver_volume_type': mock.sentinel.fake_vol_type}
        fake_volume_driver = mock_get_volume_driver.return_value

        self._volumeops.disconnect_volumes(block_device_info)
        fake_volume_driver.disconnect_volumes.assert_called_once_with(
            block_device_mapping)

    @mock.patch('nova.block_device.volume_in_mapping')
    def test_ebs_root_in_block_devices(self, mock_vol_in_mapping):
        block_device_info = get_fake_block_dev_info()

        response = self._volumeops.ebs_root_in_block_devices(block_device_info)

        mock_vol_in_mapping.assert_called_once_with(
            self._volumeops._default_root_device, block_device_info)
        self.assertEqual(mock_vol_in_mapping.return_value, response)

    def test_get_volume_connector(self):
        mock_instance = mock.DEFAULT
        initiator = self._volumeops._volutils.get_iscsi_initiator.return_value
        expected = {'ip': CONF.my_ip,
                    'host': CONF.host,
                    'initiator': initiator}

        response = self._volumeops.get_volume_connector(instance=mock_instance)

        self._volumeops._volutils.get_iscsi_initiator.assert_called_once_with()
        self.assertEqual(expected, response)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_initialize_volumes_connection(self, mock_get_volume_driver):
        block_device_info = get_fake_block_dev_info()

        self._volumeops.initialize_volumes_connection(block_device_info)

        init_vol_conn = (
            mock_get_volume_driver.return_value.initialize_volume_connection)
        init_vol_conn.assert_called_once_with(
            block_device_info['block_device_mapping'][0]['connection_info'])

    @mock.patch.object(volumeops.VolumeOps,
                       'get_mounted_disk_path_from_volume')
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

    def test_group_block_devices_by_type(self):
        block_device_map = get_fake_block_dev_info()['block_device_mapping']
        block_device_map[0]['connection_info'] = {
            'driver_volume_type': 'iscsi'}
        result = self._volumeops._group_block_devices_by_type(
            block_device_map)

        expected = {'iscsi': [block_device_map[0]]}
        self.assertEqual(expected, result)

    @mock.patch.object(volumeops.VolumeOps, '_get_volume_driver')
    def test_get_mounted_disk_path_from_volume(self, mock_get_volume_driver):
        fake_conn_info = get_fake_connection_info()
        fake_volume_driver = mock_get_volume_driver.return_value

        resulted_disk_path = self._volumeops.get_mounted_disk_path_from_volume(
            fake_conn_info)

        mock_get_volume_driver.assert_called_once_with(
            connection_info=fake_conn_info)
        get_mounted_disk = fake_volume_driver.get_mounted_disk_path_from_volume
        get_mounted_disk.assert_called_once_with(fake_conn_info)
        self.assertEqual(get_mounted_disk.return_value,
                         resulted_disk_path)


class ISCSIVolumeDriverTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for Hyper-V ISCSIVolumeDriver class."""

    def setUp(self):
        super(ISCSIVolumeDriverTestCase, self).setUp()
        self._volume_driver = volumeops.ISCSIVolumeDriver()
        self._volume_driver._vmutils = mock.MagicMock()
        self._volume_driver._volutils = mock.MagicMock()

    def test_login_storage_target_auth_exception(self):
        connection_info = get_fake_connection_info(
            auth_method='fake_auth_method')

        self.assertRaises(exception.UnsupportedBDMVolumeAuthMethod,
                          self._volume_driver.login_storage_target,
                          connection_info)

    @mock.patch.object(volumeops.ISCSIVolumeDriver,
                       '_get_mounted_disk_from_lun')
    def _check_login_storage_target(self, mock_get_mounted_disk_from_lun,
                                    dev_number):
        connection_info = get_fake_connection_info()
        login_target = self._volume_driver._volutils.login_storage_target
        get_number = self._volume_driver._volutils.get_device_number_for_target
        get_number.return_value = dev_number

        self._volume_driver.login_storage_target(connection_info)

        get_number.assert_called_once_with(mock.sentinel.fake_iqn,
                                           mock.sentinel.fake_lun)
        if not dev_number:
            login_target.assert_called_once_with(
                mock.sentinel.fake_lun, mock.sentinel.fake_iqn,
                mock.sentinel.fake_portal, mock.sentinel.fake_user,
                mock.sentinel.fake_pass)
            mock_get_mounted_disk_from_lun.assert_called_once_with(
                mock.sentinel.fake_iqn, mock.sentinel.fake_lun, True)
        else:
            self.assertFalse(login_target.called)

    def test_login_storage_target_already_logged(self):
        self._check_login_storage_target(dev_number=1)

    def test_login_storage_target(self):
        self._check_login_storage_target(dev_number=0)

    def _check_logout_storage_target(self, disconnected_luns_count=0):
        self._volume_driver._volutils.get_target_lun_count.return_value = 1

        self._volume_driver.logout_storage_target(
            target_iqn=mock.sentinel.fake_iqn,
            disconnected_luns_count=disconnected_luns_count)

        logout_storage = self._volume_driver._volutils.logout_storage_target

        if disconnected_luns_count:
            logout_storage.assert_called_once_with(mock.sentinel.fake_iqn)
        else:
            self.assertFalse(logout_storage.called)

    def test_logout_storage_target_skip(self):
        self._check_logout_storage_target()

    def test_logout_storage_target(self):
        self._check_logout_storage_target(disconnected_luns_count=1)

    @mock.patch.object(volumeops.ISCSIVolumeDriver,
                       '_get_mounted_disk_from_lun')
    def test_get_mounted_disk_path_from_volume(self,
                                               mock_get_mounted_disk_from_lun):
        connection_info = get_fake_connection_info()
        resulted_disk_path = (
            self._volume_driver.get_mounted_disk_path_from_volume(
                connection_info))

        mock_get_mounted_disk_from_lun.assert_called_once_with(
            connection_info['data']['target_iqn'],
            connection_info['data']['target_lun'],
            wait_for_device=True)
        self.assertEqual(mock_get_mounted_disk_from_lun.return_value,
                         resulted_disk_path)

    @mock.patch.object(volumeops.ISCSIVolumeDriver,
                       '_get_mounted_disk_from_lun')
    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'logout_storage_target')
    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'login_storage_target')
    def test_attach_volume_exception(self, mock_login_storage_target,
                                     mock_logout_storage_target,
                                     mock_get_mounted_disk):
        connection_info = get_fake_connection_info()
        mock_get_mounted_disk.side_effect = os_win_exc.HyperVException

        self.assertRaises(os_win_exc.HyperVException,
                          self._volume_driver.attach_volume, connection_info,
                          mock.sentinel.instance_name)
        mock_logout_storage_target.assert_called_with(mock.sentinel.fake_iqn)

    @mock.patch.object(volumeops.ISCSIVolumeDriver,
                       '_get_mounted_disk_from_lun')
    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'login_storage_target')
    def _check_attach_volume(self, mock_login_storage_target,
                             mock_get_mounted_disk_from_lun, ebs_root):
        connection_info = get_fake_connection_info()

        get_ide_path = self._volume_driver._vmutils.get_vm_ide_controller
        get_scsi_path = self._volume_driver._vmutils.get_vm_scsi_controller
        fake_ide_path = get_ide_path.return_value
        fake_scsi_path = get_scsi_path.return_value
        fake_mounted_disk_path = mock_get_mounted_disk_from_lun.return_value
        attach_vol = self._volume_driver._vmutils.attach_volume_to_controller

        get_free_slot = self._volume_driver._vmutils.get_free_controller_slot
        get_free_slot.return_value = 1

        self._volume_driver.attach_volume(
            connection_info=connection_info,
            instance_name=mock.sentinel.instance_name,
            ebs_root=ebs_root)

        mock_login_storage_target.assert_called_once_with(connection_info)
        mock_get_mounted_disk_from_lun.assert_called_once_with(
            mock.sentinel.fake_iqn,
            mock.sentinel.fake_lun,
            wait_for_device=True)
        if ebs_root:
            get_ide_path.assert_called_once_with(
                mock.sentinel.instance_name, 0)
            attach_vol.assert_called_once_with(mock.sentinel.instance_name,
                                               fake_ide_path, 0,
                                               fake_mounted_disk_path,
                                               serial=mock.sentinel.serial)
        else:
            get_scsi_path.assert_called_once_with(mock.sentinel.instance_name)
            get_free_slot.assert_called_once_with(fake_scsi_path)
            attach_vol.assert_called_once_with(mock.sentinel.instance_name,
                                               fake_scsi_path, 1,
                                               fake_mounted_disk_path,
                                               serial=mock.sentinel.serial)

    def test_attach_volume_ebs(self):
        self._check_attach_volume(ebs_root=True)

    def test_attach_volume(self):
        self._check_attach_volume(ebs_root=False)

    @mock.patch.object(volumeops.ISCSIVolumeDriver,
                       '_get_mounted_disk_from_lun')
    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'logout_storage_target')
    def test_detach_volume(self, mock_logout_storage_target,
                           mock_get_mounted_disk_from_lun):
        connection_info = get_fake_connection_info()

        self._volume_driver.detach_volume(connection_info,
                                          mock.sentinel.instance_name)

        mock_get_mounted_disk_from_lun.assert_called_once_with(
            mock.sentinel.fake_iqn,
            mock.sentinel.fake_lun,
            wait_for_device=True)
        self._volume_driver._vmutils.detach_vm_disk.assert_called_once_with(
            mock.sentinel.instance_name,
            mock_get_mounted_disk_from_lun.return_value)
        mock_logout_storage_target.assert_called_once_with(
            mock.sentinel.fake_iqn)

    def test_get_mounted_disk_from_lun(self):
        with test.nested(
            mock.patch.object(self._volume_driver._volutils,
                              'get_device_number_for_target'),
            mock.patch.object(self._volume_driver._vmutils,
                              'get_mounted_disk_by_drive_number')
            ) as (mock_get_device_number_for_target,
                  mock_get_mounted_disk_by_drive_number):

            mock_get_device_number_for_target.return_value = 0
            mock_get_mounted_disk_by_drive_number.return_value = (
                mock.sentinel.disk_path)

            disk = self._volume_driver._get_mounted_disk_from_lun(
                mock.sentinel.target_iqn,
                mock.sentinel.target_lun)
            self.assertEqual(mock.sentinel.disk_path, disk)

    def test_get_target_from_disk_path(self):
        result = self._volume_driver.get_target_from_disk_path(
            mock.sentinel.physical_drive_path)

        mock_get_target = (
            self._volume_driver._volutils.get_target_from_disk_path)
        mock_get_target.assert_called_once_with(
            mock.sentinel.physical_drive_path)
        self.assertEqual(mock_get_target.return_value, result)

    @mock.patch('time.sleep')
    def test_get_mounted_disk_from_lun_failure(self, fake_sleep):
        self.flags(mounted_disk_query_retry_count=1, group='hyperv')

        with mock.patch.object(self._volume_driver._volutils,
                               'get_device_number_for_target') as m_device_num:
            m_device_num.side_effect = [None, -1]

            self.assertRaises(exception.NotFound,
                              self._volume_driver._get_mounted_disk_from_lun,
                              mock.sentinel.target_iqn,
                              mock.sentinel.target_lun)

    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'logout_storage_target')
    def test_disconnect_volumes(self, mock_logout_storage_target):
        block_device_info = get_fake_block_dev_info()
        connection_info = get_fake_connection_info()
        block_device_mapping = block_device_info['block_device_mapping']
        block_device_mapping[0]['connection_info'] = connection_info

        self._volume_driver.disconnect_volumes(block_device_mapping)

        mock_logout_storage_target.assert_called_once_with(
            mock.sentinel.fake_iqn, 1)

    def test_get_target_lun_count(self):
        result = self._volume_driver.get_target_lun_count(
            mock.sentinel.target_iqn)

        mock_get_lun_count = self._volume_driver._volutils.get_target_lun_count
        mock_get_lun_count.assert_called_once_with(mock.sentinel.target_iqn)
        self.assertEqual(mock_get_lun_count.return_value, result)

    @mock.patch.object(volumeops.ISCSIVolumeDriver, 'login_storage_target')
    def test_initialize_volume_connection(self, mock_login_storage_target):
        self._volume_driver.initialize_volume_connection(
            mock.sentinel.connection_info)
        mock_login_storage_target.assert_called_once_with(
            mock.sentinel.connection_info)


class SMBFSVolumeDriverTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V SMBFSVolumeDriver class."""

    _FAKE_SHARE = '//1.2.3.4/fake_share'
    _FAKE_SHARE_NORMALIZED = _FAKE_SHARE.replace('/', '\\')
    _FAKE_DISK_NAME = 'fake_volume_name.vhdx'
    _FAKE_USERNAME = 'fake_username'
    _FAKE_PASSWORD = 'fake_password'
    _FAKE_SMB_OPTIONS = '-o username=%s,password=%s' % (_FAKE_USERNAME,
                                                        _FAKE_PASSWORD)
    _FAKE_CONNECTION_INFO = {'data': {'export': _FAKE_SHARE,
                                      'name': _FAKE_DISK_NAME,
                                      'options': _FAKE_SMB_OPTIONS,
                                      'volume_id': 'fake_vol_id'}}

    def setUp(self):
        super(SMBFSVolumeDriverTestCase, self).setUp()
        self._volume_driver = volumeops.SMBFSVolumeDriver()
        self._volume_driver._vmutils = mock.MagicMock()
        self._volume_driver._smbutils = mock.MagicMock()
        self._volume_driver._volutils = mock.MagicMock()

    @mock.patch.object(volumeops.SMBFSVolumeDriver,
                       '_get_disk_path')
    def test_get_mounted_disk_path_from_volume(self, mock_get_disk_path):
        disk_path = self._volume_driver.get_mounted_disk_path_from_volume(
            mock.sentinel.conn_info)

        self.assertEqual(mock_get_disk_path.return_value, disk_path)
        mock_get_disk_path.assert_called_once_with(mock.sentinel.conn_info)

    @mock.patch.object(volumeops.SMBFSVolumeDriver, 'ensure_share_mounted')
    @mock.patch.object(volumeops.SMBFSVolumeDriver, '_get_disk_path')
    def _check_attach_volume(self, mock_get_disk_path,
                             mock_ensure_share_mounted, ebs_root=False):
        mock_get_disk_path.return_value = mock.sentinel.disk_path

        self._volume_driver.attach_volume(
            self._FAKE_CONNECTION_INFO,
            mock.sentinel.instance_name,
            ebs_root)

        if ebs_root:
            get_vm_ide_controller = (
                self._volume_driver._vmutils.get_vm_ide_controller)
            get_vm_ide_controller.assert_called_once_with(
                mock.sentinel.instance_name, 0)
            ctrller_path = get_vm_ide_controller.return_value
            slot = 0
        else:
            get_vm_scsi_controller = (
                self._volume_driver._vmutils.get_vm_scsi_controller)
            get_vm_scsi_controller.assert_called_once_with(
                mock.sentinel.instance_name)
            get_free_controller_slot = (
                self._volume_driver._vmutils.get_free_controller_slot)
            get_free_controller_slot.assert_called_once_with(
                get_vm_scsi_controller.return_value)

            ctrller_path = get_vm_scsi_controller.return_value
            slot = get_free_controller_slot.return_value

        mock_ensure_share_mounted.assert_called_once_with(
            self._FAKE_CONNECTION_INFO)
        mock_get_disk_path.assert_called_once_with(self._FAKE_CONNECTION_INFO)
        self._volume_driver._vmutils.attach_drive.assert_called_once_with(
            mock.sentinel.instance_name, mock.sentinel.disk_path,
            ctrller_path, slot)

    def test_attach_volume_ide(self):
        self._check_attach_volume(ebs_root=True)

    def test_attach_volume_scsi(self):
        self._check_attach_volume()

    @mock.patch.object(volumeops.SMBFSVolumeDriver, 'ensure_share_mounted')
    @mock.patch.object(volumeops.SMBFSVolumeDriver, '_get_disk_path')
    def test_attach_non_existing_image(self, mock_get_disk_path,
                                       mock_ensure_share_mounted):
        self._volume_driver._vmutils.attach_drive.side_effect = (
            os_win_exc.HyperVException)
        self.assertRaises(exception.VolumeAttachFailed,
                          self._volume_driver.attach_volume,
                          self._FAKE_CONNECTION_INFO,
                          mock.sentinel.instance_name)

    @mock.patch.object(volumeops.SMBFSVolumeDriver, '_get_disk_path')
    def test_detach_volume(self, mock_get_disk_path):
        mock_get_disk_path.return_value = (
            mock.sentinel.disk_path)

        self._volume_driver.detach_volume(self._FAKE_CONNECTION_INFO,
                                          mock.sentinel.instance_name)

        self._volume_driver._vmutils.detach_vm_disk.assert_called_once_with(
            mock.sentinel.instance_name, mock.sentinel.disk_path,
            is_physical=False)

    def test_parse_credentials(self):
        username, password = self._volume_driver._parse_credentials(
            self._FAKE_SMB_OPTIONS)
        self.assertEqual(self._FAKE_USERNAME, username)
        self.assertEqual(self._FAKE_PASSWORD, password)

    def test_get_export_path(self):
        result = self._volume_driver._get_export_path(
            self._FAKE_CONNECTION_INFO)

        expected = self._FAKE_SHARE.replace('/', '\\')
        self.assertEqual(expected, result)

    def test_get_disk_path(self):
        expected = os.path.join(self._FAKE_SHARE_NORMALIZED,
                                self._FAKE_DISK_NAME)

        disk_path = self._volume_driver._get_disk_path(
            self._FAKE_CONNECTION_INFO)

        self.assertEqual(expected, disk_path)

    @mock.patch.object(volumeops.SMBFSVolumeDriver, '_parse_credentials')
    def _test_ensure_mounted(self, mock_parse_credentials, is_mounted=False):
        mock_mount_smb_share = self._volume_driver._smbutils.mount_smb_share
        self._volume_driver._smbutils.check_smb_mapping.return_value = (
            is_mounted)
        mock_parse_credentials.return_value = (
            self._FAKE_USERNAME, self._FAKE_PASSWORD)

        self._volume_driver.ensure_share_mounted(
            self._FAKE_CONNECTION_INFO)

        if is_mounted:
            self.assertFalse(
                mock_mount_smb_share.called)
        else:
            mock_mount_smb_share.assert_called_once_with(
                self._FAKE_SHARE_NORMALIZED,
                username=self._FAKE_USERNAME,
                password=self._FAKE_PASSWORD)

    def test_ensure_mounted_new_share(self):
        self._test_ensure_mounted()

    def test_ensure_already_mounted(self):
        self._test_ensure_mounted(is_mounted=True)

    def test_disconnect_volumes(self):
        block_device_mapping = [
            {'connection_info': self._FAKE_CONNECTION_INFO}]
        self._volume_driver.disconnect_volumes(block_device_mapping)
        mock_unmount_share = self._volume_driver._smbutils.unmount_smb_share
        mock_unmount_share.assert_called_once_with(
            self._FAKE_SHARE_NORMALIZED)

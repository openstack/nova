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

from nova import test
from nova.virt.hyperv import basevolumeutils


def _exception_thrower():
    raise Exception("Testing exception handling.")


class BaseVolumeUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V BaseVolumeUtils class."""

    _FAKE_COMPUTER_NAME = "fake_computer_name"
    _FAKE_DOMAIN_NAME = "fake_domain_name"
    _FAKE_INITIATOR_NAME = "fake_initiator_name"
    _FAKE_INITIATOR_IQN_NAME = "iqn.1991-05.com.microsoft:fake_computer_name"
    _FAKE_DISK_PATH = 'fake_path DeviceID="123\\\\2"'
    _FAKE_MOUNT_DEVICE = '/dev/fake/mount'
    _FAKE_DEVICE_NAME = '/dev/fake/path'
    _FAKE_SWAP = {'device_name': _FAKE_DISK_PATH}

    def setUp(self):
        self._volutils = basevolumeutils.BaseVolumeUtils()
        self._volutils._conn_wmi = mock.MagicMock()
        self._volutils._conn_cimv2 = mock.MagicMock()

        super(BaseVolumeUtilsTestCase, self).setUp()

    def test_get_iscsi_initiator_ok(self):
        self._check_get_iscsi_initiator(
            mock.MagicMock(return_value=mock.sentinel.FAKE_KEY),
            self._FAKE_INITIATOR_NAME)

    def test_get_iscsi_initiator_exception(self):
        initiator_name = "%(iqn)s.%(domain)s" % {
            'iqn': self._FAKE_INITIATOR_IQN_NAME,
            'domain': self._FAKE_DOMAIN_NAME
        }

        self._check_get_iscsi_initiator(_exception_thrower, initiator_name)

    def _check_get_iscsi_initiator(self, winreg_method, expected):
        mock_computer = mock.MagicMock()
        mock_computer.name = self._FAKE_COMPUTER_NAME
        mock_computer.Domain = self._FAKE_DOMAIN_NAME
        self._volutils._conn_cimv2.Win32_ComputerSystem.return_value = [
            mock_computer]

        with mock.patch.object(basevolumeutils,
                               '_winreg', create=True) as mock_winreg:
            mock_winreg.OpenKey = winreg_method
            mock_winreg.QueryValueEx = mock.MagicMock(return_value=[expected])

            initiator_name = self._volutils.get_iscsi_initiator()
            self.assertEqual(expected, initiator_name)

    @mock.patch.object(basevolumeutils, 'driver')
    def test_volume_in_mapping(self, mock_driver):
        mock_driver.block_device_info_get_mapping.return_value = [
            {'mount_device': self._FAKE_MOUNT_DEVICE}]
        mock_driver.block_device_info_get_swap = mock.MagicMock(
            return_value=self._FAKE_SWAP)
        mock_driver.block_device_info_get_ephemerals = mock.MagicMock(
            return_value=[{'device_name': self._FAKE_DEVICE_NAME}])

        mock_driver.swap_is_usable = mock.MagicMock(return_value=True)

        self.assertTrue(self._volutils.volume_in_mapping(
            self._FAKE_MOUNT_DEVICE, mock.sentinel.FAKE_BLOCK_DEVICE_INFO))

    def test_get_drive_number_from_disk_path(self):
        fake_disk_path = (
            '\\\\WIN-I5BTVHOIFGK\\root\\virtualization\\v2:Msvm_DiskDrive.'
            'CreationClassName="Msvm_DiskDrive",DeviceID="Microsoft:353B3BE8-'
            '310C-4cf4-839E-4E1B14616136\\\\1",SystemCreationClassName='
            '"Msvm_ComputerSystem",SystemName="WIN-I5BTVHOIFGK"')
        expected_disk_number = 1

        ret_val = self._volutils._get_drive_number_from_disk_path(
            fake_disk_path)

        self.assertEqual(expected_disk_number, ret_val)

    def test_get_drive_number_not_found(self):
        fake_disk_path = 'fake_disk_path'

        ret_val = self._volutils._get_drive_number_from_disk_path(
            fake_disk_path)

        self.assertFalse(ret_val)

    @mock.patch.object(basevolumeutils.BaseVolumeUtils,
                       "_get_drive_number_from_disk_path")
    def test_get_session_id_from_mounted_disk(self, mock_get_session_id):
        mock_get_session_id.return_value = mock.sentinel.FAKE_DEVICE_NUMBER
        mock_initiator_session = self._create_initiator_session()
        mock_ses_class = self._volutils._conn_wmi.MSiSCSIInitiator_SessionClass
        mock_ses_class.return_value = [mock_initiator_session]

        session_id = self._volutils.get_session_id_from_mounted_disk(
            self._FAKE_DISK_PATH)

        self.assertEqual(mock.sentinel.FAKE_SESSION_ID, session_id)

    def test_get_devices_for_target(self):
        init_session = self._create_initiator_session()
        mock_ses_class = self._volutils._conn_wmi.MSiSCSIInitiator_SessionClass
        mock_ses_class.return_value = [init_session]
        devices = self._volutils._get_devices_for_target(
            mock.sentinel.FAKE_IQN)

        self.assertEqual(init_session.Devices, devices)

    def test_get_devices_for_target_not_found(self):
        mock_ses_class = self._volutils._conn_wmi.MSiSCSIInitiator_SessionClass
        mock_ses_class.return_value = []
        devices = self._volutils._get_devices_for_target(
            mock.sentinel.FAKE_IQN)

        self.assertEqual(0, len(devices))

    @mock.patch.object(basevolumeutils.BaseVolumeUtils,
                       '_get_devices_for_target')
    def test_get_device_number_for_target(self, fake_get_devices):
        init_session = self._create_initiator_session()
        fake_get_devices.return_value = init_session.Devices
        mock_ses_class = self._volutils._conn_wmi.MSiSCSIInitiator_SessionClass
        mock_ses_class.return_value = [init_session]
        device_number = self._volutils.get_device_number_for_target(
            mock.sentinel.FAKE_IQN, mock.sentinel.FAKE_LUN)

        self.assertEqual(mock.sentinel.FAKE_DEVICE_NUMBER, device_number)

    @mock.patch.object(basevolumeutils.BaseVolumeUtils,
                       '_get_devices_for_target')
    def test_get_target_lun_count(self, fake_get_devices):
        init_session = self._create_initiator_session()
        # Only disk devices are being counted.
        disk_device = mock.Mock(DeviceType=self._volutils._FILE_DEVICE_DISK)
        init_session.Devices.append(disk_device)
        fake_get_devices.return_value = init_session.Devices

        lun_count = self._volutils.get_target_lun_count(
            mock.sentinel.FAKE_IQN)

        self.assertEqual(1, lun_count)

    @mock.patch.object(basevolumeutils.BaseVolumeUtils,
                       "_get_drive_number_from_disk_path")
    def test_get_target_from_disk_path(self, mock_get_session_id):
        mock_get_session_id.return_value = mock.sentinel.FAKE_DEVICE_NUMBER
        init_sess = self._create_initiator_session()
        mock_ses_class = self._volutils._conn_wmi.MSiSCSIInitiator_SessionClass
        mock_ses_class.return_value = [init_sess]

        (target_name, scsi_lun) = self._volutils.get_target_from_disk_path(
            self._FAKE_DISK_PATH)

        self.assertEqual(mock.sentinel.FAKE_TARGET_NAME, target_name)
        self.assertEqual(mock.sentinel.FAKE_LUN, scsi_lun)

    def _create_initiator_session(self):
        device = mock.MagicMock()
        device.ScsiLun = mock.sentinel.FAKE_LUN
        device.DeviceNumber = mock.sentinel.FAKE_DEVICE_NUMBER
        device.TargetName = mock.sentinel.FAKE_TARGET_NAME
        init_session = mock.MagicMock()
        init_session.Devices = [device]
        init_session.SessionId = mock.sentinel.FAKE_SESSION_ID

        return init_session

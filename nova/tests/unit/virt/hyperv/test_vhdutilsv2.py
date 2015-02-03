#  Copyright 2013 Cloudbase Solutions Srl
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

from nova.tests.unit.virt.hyperv import test_vhdutils
from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutilsv2
from nova.virt.hyperv import vmutils


class VHDUtilsV2TestCase(test_vhdutils.VHDUtilsBaseTestCase):
    """Unit tests for the Hyper-V VHDUtilsV2 class."""

    _FAKE_BLOCK_SIZE = 33554432L
    _FAKE_LOG_SIZE = 1048576
    _FAKE_LOGICAL_SECTOR_SIZE = 4096
    _FAKE_METADATA_SIZE = 1048576
    _FAKE_PHYSICAL_SECTOR_SIZE = 4096L

    def setUp(self):
        super(VHDUtilsV2TestCase, self).setUp()
        self._vhdutils = vhdutilsv2.VHDUtilsV2()
        self._vhdutils._conn = mock.MagicMock()
        self._vhdutils._vmutils = mock.MagicMock()

        self._fake_file_handle = mock.MagicMock()

        self._fake_vhd_info = {
            'Path': self._FAKE_VHD_PATH,
            'ParentPath': self._FAKE_PARENT_PATH,
            'Format': self._FAKE_FORMAT,
            'MaxInternalSize': self._FAKE_MAX_INTERNAL_SIZE,
            'Type': self._FAKE_TYPE,
            'BlockSize': self._FAKE_BLOCK_SIZE,
            'LogicalSectorSize': self._FAKE_LOGICAL_SECTOR_SIZE,
            'PhysicalSectorSize': self._FAKE_PHYSICAL_SECTOR_SIZE}

    def _mock_get_vhd_info(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.GetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL, self._FAKE_VHD_INFO_XML)

    def test_get_vhd_info(self):
        self._mock_get_vhd_info()
        vhd_info = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH)

        self.assertEqual(self._FAKE_VHD_PATH, vhd_info['Path'])
        self.assertEqual(self._FAKE_PARENT_PATH, vhd_info['ParentPath'])
        self.assertEqual(self._FAKE_FORMAT, vhd_info['Format'])
        self.assertEqual(self._FAKE_MAX_INTERNAL_SIZE,
                         vhd_info['MaxInternalSize'])
        self.assertEqual(self._FAKE_TYPE, vhd_info['Type'])

    def test_get_vhd_info_no_parent(self):
        fake_vhd_xml_no_parent = self._FAKE_VHD_INFO_XML.replace(
            self._FAKE_PARENT_PATH, "")

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.GetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL, fake_vhd_xml_no_parent)

        vhd_info = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH)

        self.assertEqual(self._FAKE_VHD_PATH, vhd_info['Path'])
        self.assertIsNone(vhd_info['ParentPath'])
        self.assertEqual(self._FAKE_FORMAT, vhd_info['Format'])
        self.assertEqual(self._FAKE_MAX_INTERNAL_SIZE,
                         vhd_info['MaxInternalSize'])
        self.assertEqual(self._FAKE_TYPE, vhd_info['Type'])

    def test_create_dynamic_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)

        self._vhdutils.create_dynamic_vhd(self._FAKE_VHD_PATH,
                                          self._FAKE_MAX_INTERNAL_SIZE,
                                          constants.DISK_FORMAT_VHDX)

        self.assertTrue(mock_img_svc.CreateVirtualHardDisk.called)

    def test_create_differencing_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'ParentPath': self._FAKE_PARENT_PATH,
                          'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)

        self._vhdutils.create_differencing_vhd(self._FAKE_VHD_PATH,
                                               self._FAKE_PARENT_PATH)

        self.assertTrue(mock_img_svc.CreateVirtualHardDisk.called)

    def test_reconnect_parent_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        fake_new_parent_path = 'fake_new_parent_path'

        self._vhdutils._get_vhd_info_xml = mock.MagicMock(
            return_value=self._FAKE_VHD_INFO_XML)

        mock_img_svc.SetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.reconnect_parent_vhd(self._FAKE_VHD_PATH,
                                            fake_new_parent_path)

        expected_virt_disk_data = self._FAKE_VHD_INFO_XML.replace(
            self._FAKE_PARENT_PATH, fake_new_parent_path)
        mock_img_svc.SetVirtualHardDiskSettingData.assert_called_once_with(
            VirtualDiskSettingData=expected_virt_disk_data)

    def test_reconnect_parent_vhd_exception(self):
        # Test that reconnect_parent_vhd raises an exception if the
        # vhd info XML does not contain the ParentPath property.
        fake_vhd_info_xml = self._FAKE_VHD_INFO_XML.replace('ParentPath',
                                                            'FakeParentPath')
        self._vhdutils._get_vhd_info_xml = mock.Mock(
            return_value=fake_vhd_info_xml)

        self.assertRaises(vmutils.HyperVException,
                          self._vhdutils.reconnect_parent_vhd,
                          self._FAKE_VHD_PATH,
                          mock.sentinel.new_parent_path)

    def test_resize_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.ResizeVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)
        self._vhdutils.get_internal_vhd_size_by_file_size = mock.MagicMock(
            return_value=self._FAKE_MAX_INTERNAL_SIZE)

        self._vhdutils.resize_vhd(self._FAKE_VHD_PATH,
                                  self._FAKE_MAX_INTERNAL_SIZE)

        mock_img_svc.ResizeVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            MaxInternalSize=self._FAKE_MAX_INTERNAL_SIZE)

        self.mock_get = self._vhdutils.get_internal_vhd_size_by_file_size
        self.mock_get.assert_called_once_with(self._FAKE_VHD_PATH,
                                              self._FAKE_MAX_INTERNAL_SIZE)

    def _test_get_vhdx_internal_size(self, vhd_type):
        self._vhdutils.get_vhd_info = mock.MagicMock()
        self._vhdutils.get_vhd_parent_path = mock.Mock(
            return_value=self._FAKE_PARENT_PATH)

        if vhd_type == 4:
            self._vhdutils.get_vhd_info.side_effect = [
                {'Type': vhd_type}, self._fake_vhd_info]
        else:
            self._vhdutils.get_vhd_info.return_value = self._fake_vhd_info

    @mock.patch('nova.virt.hyperv.vhdutils.VHDUtils.get_vhd_format')
    def test_get_vhdx_internal_size(self, mock_get_vhd_format):
        mock_get_vhd_format.return_value = constants.DISK_FORMAT_VHDX
        self._mock_get_vhd_info()
        self._vhdutils._get_vhdx_log_size = mock.MagicMock(
            return_value=self._FAKE_LOG_SIZE)
        self._vhdutils._get_vhdx_metadata_size_and_offset = mock.MagicMock(
            return_value=(self._FAKE_METADATA_SIZE, 1024))
        self._vhdutils._get_vhdx_block_size = mock.MagicMock(
            return_value=self._FAKE_BLOCK_SIZE)

        file_mock = mock.MagicMock()
        with mock.patch('__builtin__.open', file_mock):
            internal_size = (
                self._vhdutils.get_internal_vhd_size_by_file_size(
                    self._FAKE_VHD_PATH, self._FAKE_MAX_INTERNAL_SIZE))

        self.assertEqual(self._FAKE_MAX_INTERNAL_SIZE - self._FAKE_BLOCK_SIZE,
                         internal_size)

    def test_get_vhdx_internal_size_dynamic(self):
        self._test_get_vhdx_internal_size(3)

    def test_get_vhdx_internal_size_differencing(self):
        self._test_get_vhdx_internal_size(4)

    def test_get_vhdx_current_header(self):
        VHDX_HEADER_OFFSETS = [64 * 1024, 128 * 1024]
        fake_sequence_numbers = ['\x01\x00\x00\x00\x00\x00\x00\x00',
                                 '\x02\x00\x00\x00\x00\x00\x00\x00']
        self._fake_file_handle.read = mock.MagicMock(
            side_effect=fake_sequence_numbers)

        offset = self._vhdutils._get_vhdx_current_header_offset(
            self._fake_file_handle)
        self.assertEqual(offset, VHDX_HEADER_OFFSETS[1])

    def test_get_vhdx_metadata_size(self):
        fake_metadata_offset = '\x01\x00\x00\x00\x00\x00\x00\x00'
        fake_metadata_size = '\x01\x00\x00\x00'
        self._fake_file_handle.read = mock.MagicMock(
            side_effect=[fake_metadata_offset, fake_metadata_size])

        metadata_size, metadata_offset = (
            self._vhdutils._get_vhdx_metadata_size_and_offset(
                self._fake_file_handle))
        self.assertEqual(metadata_size, 1)
        self.assertEqual(metadata_offset, 1)

    def test_get_block_size(self):
        self._vhdutils._get_vhdx_metadata_size_and_offset = mock.MagicMock(
            return_value=(self._FAKE_METADATA_SIZE, 1024))
        fake_block_size = '\x01\x00\x00\x00'
        self._fake_file_handle.read = mock.MagicMock(
            return_value=fake_block_size)

        block_size = self._vhdutils._get_vhdx_block_size(
            self._fake_file_handle)
        self.assertEqual(block_size, 1)

    def test_get_log_size(self):
        fake_current_header_offset = 64 * 1024
        self._vhdutils._get_vhdx_current_header_offset = mock.MagicMock(
            return_value=fake_current_header_offset)
        fake_log_size = '\x01\x00\x00\x00'
        self._fake_file_handle.read = mock.MagicMock(
            return_value=fake_log_size)

        log_size = self._vhdutils._get_vhdx_log_size(self._fake_file_handle)
        self.assertEqual(log_size, 1)

    def test_get_supported_vhd_format(self):
        fmt = self._vhdutils.get_best_supported_vhd_format()
        self.assertEqual(constants.DISK_FORMAT_VHDX, fmt)

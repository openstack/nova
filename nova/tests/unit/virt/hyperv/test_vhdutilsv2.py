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
from oslo.utils import units

from nova import test
from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutilsv2


class VHDUtilsV2TestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VHDUtilsV2 class."""

    _FAKE_VHD_PATH = "C:\\fake_path.vhdx"
    _FAKE_PARENT_VHD_PATH = "C:\\fake_parent_path.vhdx"
    _FAKE_FORMAT = 3
    _FAKE_MAK_INTERNAL_SIZE = units.Gi
    _FAKE_TYPE = 3
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_RET_VAL = 0
    _FAKE_VHD_FORMAT = 'vhdx'
    _FAKE_BLOCK_SIZE = 33554432
    _FAKE_LOG_SIZE = 1048576
    _FAKE_LOGICAL_SECTOR_SIZE = 4096
    _FAKE_METADATA_SIZE = 1048576
    _FAKE_VHD_INFO = {'ParentPath': _FAKE_PARENT_VHD_PATH,
                      'Format': _FAKE_FORMAT,
                      'BlockSize': _FAKE_BLOCK_SIZE,
                      'LogicalSectorSize': _FAKE_LOGICAL_SECTOR_SIZE,
                      'Type': _FAKE_TYPE}

    def setUp(self):
        self._vhdutils = vhdutilsv2.VHDUtilsV2()
        self._vhdutils._conn = mock.MagicMock()
        self._vhdutils._vmutils = mock.MagicMock()
        self._vhdutils.get_vhd_format = mock.MagicMock(
            return_value=self._FAKE_VHD_FORMAT)

        self._fake_file_handle = mock.MagicMock()
        self._fake_vhd_info_xml = (
            '<INSTANCE CLASSNAME="Msvm_VirtualHardDiskSettingData">'
            '<PROPERTY NAME="BlockSize" TYPE="uint32">'
            '<VALUE>33554432</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="Caption" TYPE="string">'
            '<VALUE>Virtual Hard Disk Setting Data</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="Description" TYPE="string">'
            '<VALUE>Setting Data for a Virtual Hard Disk.</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="ElementName" TYPE="string">'
            '<VALUE>fake_path.vhdx</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="Format" TYPE="uint16">'
            '<VALUE>%(format)s</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="InstanceID" TYPE="string">'
            '<VALUE>52794B89-AC06-4349-AC57-486CAAD52F69</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="LogicalSectorSize" TYPE="uint32">'
            '<VALUE>512</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="MaxInternalSize" TYPE="uint64">'
            '<VALUE>%(max_internal_size)s</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="ParentPath" TYPE="string">'
            '<VALUE>%(parent_path)s</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="Path" TYPE="string">'
            '<VALUE>%(path)s</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="PhysicalSectorSize" TYPE="uint32">'
            '<VALUE>4096</VALUE>'
            '</PROPERTY>'
            '<PROPERTY NAME="Type" TYPE="uint16">'
            '<VALUE>%(type)s</VALUE>'
            '</PROPERTY>'
            '</INSTANCE>' %
            {'path': self._FAKE_VHD_PATH,
             'parent_path': self._FAKE_PARENT_VHD_PATH,
             'format': self._FAKE_FORMAT,
             'max_internal_size': self._FAKE_MAK_INTERNAL_SIZE,
             'type': self._FAKE_TYPE})

        super(VHDUtilsV2TestCase, self).setUp()

    def test_get_vhd_info(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.GetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL, self._fake_vhd_info_xml)

        vhd_info = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH)

        self.assertEqual(self._FAKE_VHD_PATH, vhd_info['Path'])
        self.assertEqual(self._FAKE_PARENT_VHD_PATH, vhd_info['ParentPath'])
        self.assertEqual(self._FAKE_FORMAT, vhd_info['Format'])
        self.assertEqual(self._FAKE_MAK_INTERNAL_SIZE,
                         vhd_info['MaxInternalSize'])
        self.assertEqual(self._FAKE_TYPE, vhd_info['Type'])

    def test_get_vhd_info_no_parent(self):
        fake_vhd_xml_no_parent = self._fake_vhd_info_xml.replace(
            self._FAKE_PARENT_VHD_PATH, "")

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.GetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL, fake_vhd_xml_no_parent)

        vhd_info = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH)

        self.assertEqual(self._FAKE_VHD_PATH, vhd_info['Path'])
        self.assertIsNone(vhd_info['ParentPath'])
        self.assertEqual(self._FAKE_FORMAT, vhd_info['Format'])
        self.assertEqual(self._FAKE_MAK_INTERNAL_SIZE,
                         vhd_info['MaxInternalSize'])
        self.assertEqual(self._FAKE_TYPE, vhd_info['Type'])

    def test_create_dynamic_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)

        self._vhdutils.create_dynamic_vhd(self._FAKE_VHD_PATH,
                                          self._FAKE_MAK_INTERNAL_SIZE,
                                          constants.DISK_FORMAT_VHDX)

        self.assertTrue(mock_img_svc.CreateVirtualHardDisk.called)

    def test_create_differencing_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'ParentPath': self._FAKE_PARENT_VHD_PATH,
                          'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)

        self._vhdutils.create_differencing_vhd(self._FAKE_VHD_PATH,
                                               self._FAKE_PARENT_VHD_PATH)

        self.assertTrue(mock_img_svc.CreateVirtualHardDisk.called)

    def test_reconnect_parent_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]

        self._vhdutils._get_vhd_info_xml = mock.MagicMock(
            return_value=self._fake_vhd_info_xml)

        mock_img_svc.SetVirtualHardDiskSettingData.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.reconnect_parent_vhd(self._FAKE_VHD_PATH,
                                            self._FAKE_PARENT_VHD_PATH)

        mock_img_svc.SetVirtualHardDiskSettingData.assert_called_once_with(
            VirtualDiskSettingData=self._fake_vhd_info_xml)

    def test_resize_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.ResizeVirtualHardDisk.return_value = (self._FAKE_JOB_PATH,
                                                           self._FAKE_RET_VAL)
        self._vhdutils.get_internal_vhd_size_by_file_size = mock.MagicMock(
            return_value=self._FAKE_MAK_INTERNAL_SIZE)

        self._vhdutils.resize_vhd(self._FAKE_VHD_PATH,
                                  self._FAKE_MAK_INTERNAL_SIZE)

        mock_img_svc.ResizeVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            MaxInternalSize=self._FAKE_MAK_INTERNAL_SIZE)

        self.mock_get = self._vhdutils.get_internal_vhd_size_by_file_size
        self.mock_get.assert_called_once_with(self._FAKE_VHD_PATH,
                                              self._FAKE_MAK_INTERNAL_SIZE)

    def _test_get_vhdx_internal_size(self, vhd_type):
        self._vhdutils.get_vhd_info = mock.MagicMock()
        self._vhdutils.get_vhd_parent_path = mock.Mock(
            return_value=self._FAKE_PARENT_VHD_PATH)

        if vhd_type == 4:
            self._vhdutils.get_vhd_info.side_effect = [
                {'Type': vhd_type}, self._FAKE_VHD_INFO]
        else:
            self._vhdutils.get_vhd_info.return_value = self._FAKE_VHD_INFO
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
                    self._FAKE_VHD_PATH, self._FAKE_MAK_INTERNAL_SIZE))

        self.assertEqual(self._FAKE_MAK_INTERNAL_SIZE - self._FAKE_BLOCK_SIZE,
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

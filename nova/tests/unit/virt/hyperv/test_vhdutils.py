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
from oslo_utils import units

from nova import test
from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils


class VHDUtilsBaseTestCase(test.NoDBTestCase):
    "Base Class unit test classes of Hyper-V VHD Utils classes."

    _FAKE_VHD_PATH = "C:\\fake_path.vhdx"
    _FAKE_PARENT_PATH = "C:\\fake_parent_path.vhdx"
    _FAKE_FORMAT = 3
    _FAKE_TYPE = 3
    _FAKE_MAX_INTERNAL_SIZE = units.Gi
    _FAKE_DYNAMIC_BLK_SIZE = 2097152L
    _FAKE_BAD_TYPE = 5

    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_RET_VAL = 0
    _FAKE_VHD_INFO_XML = (
        """<INSTANCE CLASSNAME="Msvm_VirtualHardDiskSettingData">
<PROPERTY NAME="BlockSize" TYPE="uint32">
<VALUE>33554432</VALUE>
</PROPERTY>
<PROPERTY NAME="Caption" TYPE="string">
<VALUE>Virtual Hard Disk Setting Data</VALUE>
</PROPERTY>
<PROPERTY NAME="Description" TYPE="string">
<VALUE>Setting Data for a Virtual Hard Disk.</VALUE>
</PROPERTY>
<PROPERTY NAME="ElementName" TYPE="string">
<VALUE>fake_path.vhdx</VALUE>
</PROPERTY>
<PROPERTY NAME="Format" TYPE="uint16">
<VALUE>%(format)s</VALUE>
</PROPERTY>
<PROPERTY NAME="InstanceID" TYPE="string">
<VALUE>52794B89-AC06-4349-AC57-486CAAD52F69</VALUE>
</PROPERTY>
<PROPERTY NAME="LogicalSectorSize" TYPE="uint32">
<VALUE>4096</VALUE>
</PROPERTY>
<PROPERTY NAME="MaxInternalSize" TYPE="uint64">
<VALUE>%(max_internal_size)s</VALUE>
</PROPERTY>
<PROPERTY NAME="ParentPath" TYPE="string">
<VALUE>%(parent_path)s</VALUE>
</PROPERTY>
<PROPERTY NAME="Path" TYPE="string">
<VALUE>%(path)s</VALUE>
</PROPERTY>
<PROPERTY NAME="PhysicalSectorSize" TYPE="uint32">
<VALUE>4096</VALUE>
</PROPERTY>
<PROPERTY NAME="Type" TYPE="uint16">
<VALUE>%(type)s</VALUE>
</PROPERTY>
</INSTANCE>""" % {'path': _FAKE_VHD_PATH,
                  'parent_path': _FAKE_PARENT_PATH,
                  'format': _FAKE_FORMAT,
                  'max_internal_size': _FAKE_MAX_INTERNAL_SIZE,
                  'type': _FAKE_TYPE})


class VHDUtilsTestCase(VHDUtilsBaseTestCase):
    """Unit tests for the Hyper-V VHDUtils class."""

    def setUp(self):
        super(VHDUtilsTestCase, self).setUp()
        self._vhdutils = vhdutils.VHDUtils()
        self._vhdutils._conn = mock.MagicMock()
        self._vhdutils._vmutils = mock.MagicMock()

        self._fake_vhd_info = {
            'ParentPath': self._FAKE_PARENT_PATH,
            'MaxInternalSize': self._FAKE_MAX_INTERNAL_SIZE,
            'Type': self._FAKE_TYPE}

    def test_validate_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.ValidateVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.validate_vhd(self._FAKE_VHD_PATH)
        mock_img_svc.ValidateVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH)

    def test_get_vhd_info(self):
        self._mock_get_vhd_info()
        vhd_info = self._vhdutils.get_vhd_info(self._FAKE_VHD_PATH)
        self.assertEqual(self._fake_vhd_info, vhd_info)

    def _mock_get_vhd_info(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.GetVirtualHardDiskInfo.return_value = (
            self._FAKE_VHD_INFO_XML, self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

    def test_create_dynamic_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateDynamicVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.create_dynamic_vhd(self._FAKE_VHD_PATH,
                                          self._FAKE_MAX_INTERNAL_SIZE,
                                          constants.DISK_FORMAT_VHD)

        mock_img_svc.CreateDynamicVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            MaxInternalSize=self._FAKE_MAX_INTERNAL_SIZE)
        self._vhdutils._vmutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def test_reconnect_parent_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.ReconnectParentVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.reconnect_parent_vhd(self._FAKE_VHD_PATH,
                                            self._FAKE_PARENT_PATH)
        mock_img_svc.ReconnectParentVirtualHardDisk.assert_called_once_with(
            ChildPath=self._FAKE_VHD_PATH,
            ParentPath=self._FAKE_PARENT_PATH,
            Force=True)
        self._vhdutils._vmutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def test_merge_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.MergeVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.merge_vhd(self._FAKE_VHD_PATH, self._FAKE_VHD_PATH)

        mock_img_svc.MergeVirtualHardDisk.assert_called_once_with(
            SourcePath=self._FAKE_VHD_PATH,
            DestinationPath=self._FAKE_VHD_PATH)
        self._vhdutils._vmutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def test_resize_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.ExpandVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.get_internal_vhd_size_by_file_size = mock.MagicMock(
            return_value=self._FAKE_MAX_INTERNAL_SIZE)

        self._vhdutils.resize_vhd(self._FAKE_VHD_PATH,
                                  self._FAKE_MAX_INTERNAL_SIZE)

        mock_img_svc.ExpandVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            MaxInternalSize=self._FAKE_MAX_INTERNAL_SIZE)
        self._vhdutils._vmutils.check_ret_val.assert_called_once_with(
            self._FAKE_RET_VAL, self._FAKE_JOB_PATH)

    def _mocked_get_internal_vhd_size(self, root_vhd_size, vhd_type):
        mock_get_vhd_info = mock.MagicMock(return_value={'Type': vhd_type})
        mock_get_blk_size = mock.MagicMock(
            return_value=self._FAKE_DYNAMIC_BLK_SIZE)
        with mock.patch.multiple(self._vhdutils,
                                 get_vhd_info=mock_get_vhd_info,
                                 _get_vhd_dynamic_blk_size=mock_get_blk_size):

            return self._vhdutils.get_internal_vhd_size_by_file_size(
                None, root_vhd_size)

    def test_create_differencing_vhd(self):
        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateDifferencingVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.create_differencing_vhd(self._FAKE_VHD_PATH,
                                               self._FAKE_PARENT_PATH)

        mock_img_svc.CreateDifferencingVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            ParentPath=self._FAKE_PARENT_PATH)

    def test_get_internal_vhd_size_by_file_size_fixed(self):
        root_vhd_size = 1 * 1024 ** 3
        real_size = self._mocked_get_internal_vhd_size(
            root_vhd_size, constants.VHD_TYPE_FIXED)

        expected_vhd_size = 1 * 1024 ** 3 - 512
        self.assertEqual(expected_vhd_size, real_size)

    def test_get_internal_vhd_size_by_file_size_dynamic(self):
        root_vhd_size = 20 * 1024 ** 3
        real_size = self._mocked_get_internal_vhd_size(
            root_vhd_size, constants.VHD_TYPE_DYNAMIC)

        expected_vhd_size = 20 * 1024 ** 3 - 43008
        self.assertEqual(expected_vhd_size, real_size)

    def test_get_internal_vhd_size_by_file_size_differencing(self):
        # For differencing images, the internal size of the parent vhd
        # is returned
        vhdutil = vhdutils.VHDUtils()
        root_vhd_size = 20 * 1024 ** 3
        vhdutil.get_vhd_info = mock.MagicMock()
        vhdutil.get_vhd_parent_path = mock.MagicMock()
        vhdutil.get_vhd_parent_path.return_value = self._FAKE_VHD_PATH
        vhdutil.get_vhd_info.side_effect = [
            {'Type': 4}, {'Type': constants.VHD_TYPE_DYNAMIC}]

        vhdutil._get_vhd_dynamic_blk_size = mock.MagicMock()
        vhdutil._get_vhd_dynamic_blk_size.return_value = 2097152

        real_size = vhdutil.get_internal_vhd_size_by_file_size(None,
                                                               root_vhd_size)
        expected_vhd_size = 20 * 1024 ** 3 - 43008
        self.assertEqual(expected_vhd_size, real_size)

    def test_get_vhd_format_vhdx(self):
        with mock.patch('nova.virt.hyperv.vhdutils.open',
                        mock.mock_open(read_data=vhdutils.VHDX_SIGNATURE),
                        create=True):

            format = self._vhdutils.get_vhd_format(self._FAKE_VHD_PATH)

            self.assertEqual(constants.DISK_FORMAT_VHDX, format)

    def test_get_vhd_format_vhd(self):
        with mock.patch('nova.virt.hyperv.vhdutils.open',
                        mock.mock_open(read_data=vhdutils.VHD_SIGNATURE),
                        create=True) as mock_open:
            f = mock_open.return_value
            f.tell.return_value = 1024

            format = self._vhdutils.get_vhd_format(self._FAKE_VHD_PATH)

            self.assertEqual(constants.DISK_FORMAT_VHD, format)

    def test_get_vhd_format_invalid_format(self):
        with mock.patch('nova.virt.hyperv.vhdutils.open',
                        mock.mock_open(read_data='invalid'),
                        create=True) as mock_open:
            f = mock_open.return_value
            f.tell.return_value = 1024

            self.assertRaises(vmutils.HyperVException,
                              self._vhdutils.get_vhd_format,
                              self._FAKE_VHD_PATH)

    def test_get_vhd_format_zero_length_file(self):
        with mock.patch('nova.virt.hyperv.vhdutils.open',
                        mock.mock_open(read_data=''),
                        create=True) as mock_open:
            f = mock_open.return_value
            f.tell.return_value = 0

            self.assertRaises(vmutils.HyperVException,
                              self._vhdutils.get_vhd_format,
                              self._FAKE_VHD_PATH)

            f.seek.assert_called_once_with(0, 2)

    def test_get_supported_vhd_format(self):
        fmt = self._vhdutils.get_best_supported_vhd_format()
        self.assertEqual(constants.DISK_FORMAT_VHD, fmt)

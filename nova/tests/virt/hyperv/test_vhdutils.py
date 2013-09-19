# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import test

from nova.virt.hyperv import constants
from nova.virt.hyperv import vhdutils
from nova.virt.hyperv import vmutils


class VHDUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VHDUtils class."""

    _FAKE_VHD_PATH = "C:\\fake_path.vhdx"
    _FAKE_FORMAT = 3
    _FAKE_MAK_INTERNAL_SIZE = 1000
    _FAKE_JOB_PATH = 'fake_job_path'
    _FAKE_RET_VAL = 0

    def setUp(self):
        self._vhdutils = vhdutils.VHDUtils()
        self._vhdutils._conn = mock.MagicMock()
        self._vhdutils._vmutils = mock.MagicMock()
        super(VHDUtilsTestCase, self).setUp()

    def test_create_dynamic_vhd(self):
        self._vhdutils.get_vhd_info = mock.MagicMock(
            return_value={'Format': self._FAKE_FORMAT})

        mock_img_svc = self._vhdutils._conn.Msvm_ImageManagementService()[0]
        mock_img_svc.CreateDynamicVirtualHardDisk.return_value = (
            self._FAKE_JOB_PATH, self._FAKE_RET_VAL)

        self._vhdutils.create_dynamic_vhd(self._FAKE_VHD_PATH,
                                          self._FAKE_MAK_INTERNAL_SIZE,
                                          constants.DISK_FORMAT_VHD)

        mock_img_svc.CreateDynamicVirtualHardDisk.assert_called_once_with(
            Path=self._FAKE_VHD_PATH,
            MaxInternalSize=self._FAKE_MAK_INTERNAL_SIZE)

    def test_get_internal_vhd_size_by_file_size_fixed(self):
        vhdutil = vhdutils.VHDUtils()
        root_vhd_size = 1 * 1024 ** 3
        vhdutil.get_vhd_info = mock.MagicMock()
        vhdutil.get_vhd_info.return_value = {'Type': constants.VHD_TYPE_FIXED}

        real_size = vhdutil._get_internal_vhd_size_by_file_size(None,
                                                                root_vhd_size)
        expected_vhd_size = 1 * 1024 ** 3 - 512
        self.assertEqual(expected_vhd_size, real_size)

    def test_get_internal_vhd_size_by_file_size_dynamic(self):
        vhdutil = vhdutils.VHDUtils()
        root_vhd_size = 20 * 1024 ** 3
        vhdutil.get_vhd_info = mock.MagicMock()
        vhdutil.get_vhd_info.return_value = {'Type':
                                             constants.VHD_TYPE_DYNAMIC}
        vhdutil._get_vhd_dynamic_blk_size = mock.MagicMock()
        vhdutil._get_vhd_dynamic_blk_size.return_value = 2097152

        real_size = vhdutil._get_internal_vhd_size_by_file_size(None,
                                                                root_vhd_size)
        expected_vhd_size = 20 * 1024 ** 3 - 43008
        self.assertEqual(expected_vhd_size, real_size)

    def test_get_internal_vhd_size_by_file_size_unsupported(self):
        vhdutil = vhdutils.VHDUtils()
        root_vhd_size = 20 * 1024 ** 3
        vhdutil.get_vhd_info = mock.MagicMock()
        vhdutil.get_vhd_info.return_value = {'Type': 5}

        self.assertRaises(vmutils.HyperVException,
                          vhdutil._get_internal_vhd_size_by_file_size,
                          None, root_vhd_size)

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

import mock

from nova import exception
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import vmutils


class PathUtilsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V PathUtils class."""

    def setUp(self):
        super(PathUtilsTestCase, self).setUp()
        self.fake_instance_dir = os.path.join('C:', 'fake_instance_dir')
        self.fake_instance_name = 'fake_instance_name'

        self._pathutils = pathutils.PathUtils()

    def _test_smb_conn(self, smb_available=True):
        self._mock_wmi.x_wmi = Exception
        self._mock_wmi.WMI.side_effect = None if smb_available else Exception

        self._pathutils._set_smb_conn()

        if smb_available:
            expected_conn = self._mock_wmi.WMI.return_value
            self.assertEqual(expected_conn, self._pathutils._smb_conn)
        else:
            self.assertRaises(vmutils.HyperVException,
                              getattr,
                              self._pathutils, '_smb_conn')

    def test_smb_conn_available(self):
        self._test_smb_conn()

    def test_smb_conn_unavailable(self):
        self._test_smb_conn(smb_available=False)

    @mock.patch.object(pathutils.PathUtils, 'rename')
    @mock.patch.object(os.path, 'isfile')
    @mock.patch.object(os, 'listdir')
    def test_move_folder_files(self, mock_listdir, mock_isfile, mock_rename):
        src_dir = 'src'
        dest_dir = 'dest'
        fname = 'tmp_file.txt'
        subdir = 'tmp_folder'
        src_fname = os.path.join(src_dir, fname)
        dest_fname = os.path.join(dest_dir, fname)

        # making sure src_subdir is not moved.
        mock_listdir.return_value = [fname, subdir]
        mock_isfile.side_effect = [True, False]

        self._pathutils.move_folder_files(src_dir, dest_dir)
        mock_rename.assert_called_once_with(src_fname, dest_fname)

    def _mock_lookup_configdrive_path(self, ext):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)

        def mock_exists(*args, **kwargs):
            path = args[0]
            return True if path[(path.rfind('.') + 1):] == ext else False
        self._pathutils.exists = mock_exists
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name)
        return configdrive_path

    def test_lookup_configdrive_path(self):
        for format_ext in constants.DISK_FORMAT_MAP:
            configdrive_path = self._mock_lookup_configdrive_path(format_ext)
            fake_path = os.path.join(self.fake_instance_dir,
                                     'configdrive.' + format_ext)
            self.assertEqual(configdrive_path, fake_path)

    def test_lookup_configdrive_path_non_exist(self):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)
        self._pathutils.exists = mock.MagicMock(return_value=False)
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name)
        self.assertIsNone(configdrive_path)

    @mock.patch.object(pathutils.PathUtils, 'unmount_smb_share')
    @mock.patch('os.path.exists')
    def _test_check_smb_mapping(self, mock_exists, mock_unmount_smb_share,
                                existing_mappings=True, share_available=False):
        mock_exists.return_value = share_available

        fake_mappings = (
            [mock.sentinel.smb_mapping] if existing_mappings else [])

        self._pathutils._smb_conn.Msft_SmbMapping.return_value = (
            fake_mappings)

        ret_val = self._pathutils.check_smb_mapping(
            mock.sentinel.share_path)

        self.assertEqual(existing_mappings and share_available, ret_val)
        if existing_mappings and not share_available:
            mock_unmount_smb_share.assert_called_once_with(
                mock.sentinel.share_path, force=True)

    def test_check_mapping(self):
        self._test_check_smb_mapping()

    def test_remake_unavailable_mapping(self):
        self._test_check_smb_mapping(existing_mappings=True,
                                     share_available=False)

    def test_available_mapping(self):
        self._test_check_smb_mapping(existing_mappings=True,
                                     share_available=True)

    def test_mount_smb_share(self):
        fake_create = self._pathutils._smb_conn.Msft_SmbMapping.Create
        self._pathutils.mount_smb_share(mock.sentinel.share_path,
                                        mock.sentinel.username,
                                        mock.sentinel.password)
        fake_create.assert_called_once_with(
            RemotePath=mock.sentinel.share_path,
            UserName=mock.sentinel.username,
            Password=mock.sentinel.password)

    def _test_unmount_smb_share(self, force=False):
        fake_mapping = mock.Mock()
        smb_mapping_class = self._pathutils._smb_conn.Msft_SmbMapping
        smb_mapping_class.return_value = [fake_mapping]

        self._pathutils.unmount_smb_share(mock.sentinel.share_path,
                                          force)

        smb_mapping_class.assert_called_once_with(
            RemotePath=mock.sentinel.share_path)
        fake_mapping.Remove.assert_called_once_with(Force=force)

    def test_soft_unmount_smb_share(self):
        self._test_unmount_smb_share()

    def test_force_unmount_smb_share(self):
        self._test_unmount_smb_share(force=True)

    @mock.patch('time.sleep')
    @mock.patch('shutil.rmtree')
    def test_rmtree(self, mock_rmtree, mock_sleep):
        class WindowsError(Exception):
            def __init__(self, winerror=None):
                self.winerror = winerror

        mock_rmtree.side_effect = [WindowsError(
            pathutils.ERROR_DIR_IS_NOT_EMPTY), True]
        fake_windows_error = WindowsError
        with mock.patch('__builtin__.WindowsError',
                        fake_windows_error, create=True):
            self._pathutils.rmtree(mock.sentinel.FAKE_PATH)

        mock_rmtree.assert_has_calls([mock.call(mock.sentinel.FAKE_PATH),
                                      mock.call(mock.sentinel.FAKE_PATH)])
        mock_sleep.assert_called_once_with(1)

    @mock.patch('os.path.join')
    def test_get_instances_sub_dir(self, fake_path_join):

        class WindowsError(Exception):
            def __init__(self, winerror=None):
                self.winerror = winerror

        fake_dir_name = "fake_dir_name"
        fake_windows_error = WindowsError
        self._pathutils._check_create_dir = mock.MagicMock(
            side_effect=WindowsError(pathutils.ERROR_INVALID_NAME))
        with mock.patch('__builtin__.WindowsError',
                        fake_windows_error, create=True):
            self.assertRaises(exception.AdminRequired,
                              self._pathutils._get_instances_sub_dir,
                              fake_dir_name)

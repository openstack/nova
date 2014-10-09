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

from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import constants
from nova.virt.hyperv import pathutils


class PathUtilsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V PathUtils class."""

    def setUp(self):
        super(PathUtilsTestCase, self).setUp()
        self.fake_instance_dir = os.path.join('C:', 'fake_instance_dir')
        self.fake_instance_name = 'fake_instance_name'

        self._pathutils = pathutils.PathUtils()

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

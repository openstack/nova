# Copyright 2013 OpenStack Foundation
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

import nova.privsep.fs
from nova import test


class PrivsepFilesystemHelpersTestCase(test.NoDBTestCase):
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_list_partitions(self, mock_execute):
        parted_return = "BYT;\n...\n"
        parted_return += "1:2s:11s:10s:ext3::boot;\n"
        parted_return += "2:20s:11s:10s::bob:;\n"
        mock_execute.return_value = (parted_return, None)

        partitions = nova.privsep.fs.unprivileged_list_partitions("abc")

        self.assertEqual(2, len(partitions))
        self.assertEqual((1, 2, 10, "ext3", "", "boot"), partitions[0])
        self.assertEqual((2, 20, 10, "", "bob", ""), partitions[1])


class MkfsTestCase(test.NoDBTestCase):
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_ext4(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs('ext4', '/my/block/dev')
        mock_execute.assert_called_once_with('mkfs', '-t', 'ext4', '-F',
            '/my/block/dev')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_msdos(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs('msdos', '/my/msdos/block/dev')
        mock_execute.assert_called_once_with('mkfs', '-t', 'msdos',
            '/my/msdos/block/dev')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_swap(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs('swap', '/my/swap/block/dev')
        mock_execute.assert_called_once_with('mkswap', '/my/swap/block/dev')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_ext4_withlabel(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs('ext4', '/my/block/dev', 'ext4-vol')
        mock_execute.assert_called_once_with(
            'mkfs', '-t', 'ext4', '-F', '-L', 'ext4-vol', '/my/block/dev')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_msdos_withlabel(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs(
            'msdos', '/my/msdos/block/dev', 'msdos-vol')
        mock_execute.assert_called_once_with(
            'mkfs', '-t', 'msdos', '-n', 'msdos-vol', '/my/msdos/block/dev')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mkfs_swap_withlabel(self, mock_execute):
        nova.privsep.fs.unprivileged_mkfs(
            'swap', '/my/swap/block/dev', 'swap-vol')
        mock_execute.assert_called_once_with(
            'mkswap', '-L', 'swap-vol', '/my/swap/block/dev')

    HASH_VFAT = nova.privsep.fs._get_hash_str(
        nova.privsep.fs.FS_FORMAT_VFAT)[:7]
    HASH_EXT4 = nova.privsep.fs._get_hash_str(
        nova.privsep.fs.FS_FORMAT_EXT4)[:7]
    HASH_NTFS = nova.privsep.fs._get_hash_str(
        nova.privsep.fs.FS_FORMAT_NTFS)[:7]

    def test_get_file_extension_for_os_type(self):
        self.assertEqual(self.HASH_VFAT,
                         nova.privsep.fs.get_file_extension_for_os_type(
                             None, None))
        self.assertEqual(self.HASH_EXT4,
                         nova.privsep.fs.get_file_extension_for_os_type(
                             'linux', None))
        self.assertEqual(self.HASH_NTFS,
                         nova.privsep.fs.get_file_extension_for_os_type(
                             'windows', None))

    def test_get_file_extension_for_os_type_with_overrides(self):
        with mock.patch('nova.privsep.fs._DEFAULT_MKFS_COMMAND',
                        'custom mkfs command'):
            self.assertEqual("a74d253",
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'linux', None))
            self.assertEqual("a74d253",
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'windows', None))
            self.assertEqual("a74d253",
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'osx', None))

        with mock.patch.dict(nova.privsep.fs._MKFS_COMMAND,
                             {'osx': 'custom mkfs command'}, clear=True):
            self.assertEqual(self.HASH_VFAT,
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 None, None))
            self.assertEqual(self.HASH_EXT4,
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'linux', None))
            self.assertEqual(self.HASH_NTFS,
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'windows', None))
            self.assertEqual("a74d253",
                             nova.privsep.fs.get_file_extension_for_os_type(
                                 'osx', None))

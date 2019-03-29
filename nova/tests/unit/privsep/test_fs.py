# Copyright 2013 OpenStack Foundation
# Copyright 2019 Aptira Pty Ltd
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
from nova.tests import fixtures


class PrivsepFilesystemHelpersTestCase(test.NoDBTestCase):
    """Test filesystem related utility methods."""

    def setUp(self):
        super(PrivsepFilesystemHelpersTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mount_simple(self, mock_execute):
        nova.privsep.fs.mount(None, '/dev/nosuch', '/fake/path', None)
        mock_execute.assert_called_with('mount', '/dev/nosuch', '/fake/path')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_mount_less_simple(self, mock_execute):
        nova.privsep.fs.mount('ext4', '/dev/nosuch', '/fake/path',
                              ['-o', 'remount'])
        mock_execute.assert_called_with('mount', '-t', 'ext4',
                                        '-o', 'remount',
                                         '/dev/nosuch', '/fake/path')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_umount(self, mock_execute):
        nova.privsep.fs.umount('/fake/path')
        mock_execute.assert_called_with('umount', '/fake/path',
                                        attempts=3, delay_on_retry=True)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_lvcreate_simple(self, mock_execute):
        nova.privsep.fs.lvcreate(1024, 'lv', 'vg')
        mock_execute.assert_called_with('lvcreate', '-L', '1024b', '-n', 'lv',
                                        'vg', attempts=3)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_lvcreate_preallocated(self, mock_execute):
        nova.privsep.fs.lvcreate(1024, 'lv', 'vg', preallocated=512)
        mock_execute.assert_called_with('lvcreate', '-L', '512b',
                                        '--virtualsize', '1024b',
                                        '-n', 'lv', 'vg', attempts=3)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_vginfo(self, mock_execute):
        nova.privsep.fs.vginfo('vg')
        mock_execute.assert_called_with('vgs', '--noheadings', '--nosuffix',
                                        '--separator', '|', '--units', 'b',
                                        '-o', 'vg_size,vg_free', 'vg')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_lvlist(self, mock_execute):
        nova.privsep.fs.lvlist('vg')
        mock_execute.assert_called_with('lvs', '--noheadings', '-o',
                                        'lv_name', 'vg')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_lvinfo(self, mock_execute):
        nova.privsep.fs.lvinfo('/path/to/lv')
        mock_execute.assert_called_with('lvs', '-o', 'vg_all,lv_all',
                                        '--separator', '|', '/path/to/lv')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_lvremove(self, mock_execute):
        nova.privsep.fs.lvremove('/path/to/lv')
        mock_execute.assert_called_with('lvremove', '-f', '/path/to/lv',
                                        attempts=3)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_blockdev_size(self, mock_execute):
        nova.privsep.fs.blockdev_size('/dev/nosuch')
        mock_execute.assert_called_with('blockdev', '--getsize64',
                                        '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_blockdev_flush(self, mock_execute):
        nova.privsep.fs.blockdev_flush('/dev/nosuch')
        mock_execute.assert_called_with('blockdev', '--flushbufs',
                                        '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_clear_simple(self, mock_execute):
        nova.privsep.fs.clear('/dev/nosuch', 1024)
        mock_execute.assert_called_with('shred', '-n0', '-z', '-s1024',
                                        '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_clear_with_shred(self, mock_execute):
        nova.privsep.fs.clear('/dev/nosuch', 1024, shred=True)
        mock_execute.assert_called_with('shred', '-n3', '-s1024',
                                        '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_loopsetup(self, mock_execute):
        nova.privsep.fs.loopsetup('/dev/nosuch')
        mock_execute.assert_called_with('losetup', '--find', '--show',
                                        '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_loopremove(self, mock_execute):
        nova.privsep.fs.loopremove('/dev/nosuch')
        mock_execute.assert_called_with('losetup', '--detach', '/dev/nosuch',
                                        attempts=3)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_nbd_connect(self, mock_execute):
        nova.privsep.fs.nbd_connect('/dev/nosuch', '/fake/path')
        mock_execute.assert_called_with('qemu-nbd', '-c', '/dev/nosuch',
                                        '/fake/path')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_nbd_disconnect(self, mock_execute):
        nova.privsep.fs.nbd_disconnect('/dev/nosuch')
        mock_execute.assert_called_with('qemu-nbd', '-d', '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_device_maps(self, mock_execute):
        nova.privsep.fs.create_device_maps('/dev/nosuch')
        mock_execute.assert_called_with('kpartx', '-a', '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_remove_device_maps(self, mock_execute):
        nova.privsep.fs.remove_device_maps('/dev/nosuch')
        mock_execute.assert_called_with('kpartx', '-d', '/dev/nosuch')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_get_filesystem_type(self, mock_execute):
        nova.privsep.fs.get_filesystem_type('/dev/nosuch')
        mock_execute.assert_called_with('blkid', '-o', 'value', '-s',
                                        'TYPE', '/dev/nosuch',
                                        check_exit_code=[0, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_privileged_e2fsck(self, mock_execute):
        nova.privsep.fs.e2fsck('/path/nosuch')
        mock_execute.assert_called_with('e2fsck', '-fp', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_privileged_e2fsck_with_flags(self, mock_execute):
        nova.privsep.fs.e2fsck('/path/nosuch', flags='festive')
        mock_execute.assert_called_with('e2fsck', 'festive', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_unprivileged_e2fsck(self, mock_execute):
        nova.privsep.fs.unprivileged_e2fsck('/path/nosuch')
        mock_execute.assert_called_with('e2fsck', '-fp', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_unprivileged_e2fsck_with_flags(self, mock_execute):
        nova.privsep.fs.unprivileged_e2fsck('/path/nosuch', flags='festive')
        mock_execute.assert_called_with('e2fsck', 'festive', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_privileged_resize2fs(self, mock_execute):
        nova.privsep.fs.resize2fs('/path/nosuch', [0, 1, 2])
        mock_execute.assert_called_with('resize2fs', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_privileged_resize2fs_with_size(self, mock_execute):
        nova.privsep.fs.resize2fs('/path/nosuch', [0, 1, 2], 1024)
        mock_execute.assert_called_with('resize2fs', '/path/nosuch', 1024,
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_unprivileged_resize2fs(self, mock_execute):
        nova.privsep.fs.unprivileged_resize2fs('/path/nosuch', [0, 1, 2])
        mock_execute.assert_called_with('resize2fs', '/path/nosuch',
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_unprivileged_resize2fs_with_size(self, mock_execute):
        nova.privsep.fs.unprivileged_resize2fs('/path/nosuch', [0, 1, 2], 1024)
        mock_execute.assert_called_with('resize2fs', '/path/nosuch', 1024,
                                        check_exit_code=[0, 1, 2])

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_partition_table(self, mock_execute):
        nova.privsep.fs.create_partition_table('/dev/nosuch', 'style')
        mock_execute.assert_called_with('parted', '--script', '/dev/nosuch',
                                        'mklabel', 'style',
                                        check_exit_code=True)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_create_partition(self, mock_execute):
        nova.privsep.fs.create_partition('/dev/nosuch', 'style', 0, 100)
        mock_execute.assert_called_with('parted', '--script', '/dev/nosuch',
                                        '--', 'mkpart', 'style', 0, 100,
                                        check_exit_code=True)

    @mock.patch('oslo_concurrency.processutils.execute')
    def _test_list_partitions(self, meth, mock_execute):
        parted_return = "BYT;\n...\n"
        parted_return += "1:2s:11s:10s:ext3::boot;\n"
        parted_return += "2:20s:11s:10s::bob:;\n"
        mock_execute.return_value = (parted_return, None)

        partitions = meth("abc")

        self.assertEqual(2, len(partitions))
        self.assertEqual((1, 2, 10, "ext3", "", "boot"), partitions[0])
        self.assertEqual((2, 20, 10, "", "bob", ""), partitions[1])

    def test_privileged_list_partitions(self):
        self._test_list_partitions(nova.privsep.fs.list_partitions)

    def test_unprivileged_list_partitions(self):
        self._test_list_partitions(
            nova.privsep.fs.unprivileged_list_partitions)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_resize_partition(self, mock_execute):
        nova.privsep.fs.resize_partition('/dev/nosuch', 0, 100, True)
        mock_execute.assert_has_calls([
            mock.call('parted', '--script', '/dev/nosuch', 'rm', '1'),
            mock.call('parted', '--script', '/dev/nosuch', 'mkpart',
                      'primary', '0s', '100s'),
            mock.call('parted', '--script', '/dev/nosuch',
                      'set', '1', 'boot', 'on')])


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

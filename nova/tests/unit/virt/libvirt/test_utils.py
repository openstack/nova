# Copyright 2012 NTT Data. All Rights Reserved.
# Copyright 2012 Yahoo! Inc. All Rights Reserved.
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

import functools
import os
import tempfile

import mock
from oslo.config import cfg
from oslo_concurrency import processutils

from nova import exception
from nova.openstack.common import fileutils
from nova import test
from nova import utils
from nova.virt.disk import api as disk
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


class LibvirtUtilsTestCase(test.NoDBTestCase):

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_get_disk_type(self, mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
blah BLAH: bb
"""
        mock_execute.return_value = (example_output, '')
        disk_type = libvirt_utils.get_disk_type(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('raw', disk_type)

    @mock.patch('nova.utils.execute')
    def test_copy_image_local_cp(self, mock_execute):
        libvirt_utils.copy_image('src', 'dest')
        mock_execute.assert_called_once_with('cp', 'src', 'dest')

    _rsync_call = functools.partial(mock.call,
                                    'rsync', '--sparse', '--compress')

    @mock.patch('nova.utils.execute')
    def test_copy_image_rsync(self, mock_execute):
        libvirt_utils.copy_image('src', 'dest', host='host')

        mock_execute.assert_has_calls([
            self._rsync_call('--dry-run', 'src', 'host:dest'),
            self._rsync_call('src', 'host:dest'),
        ])
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_copy_image_scp(self, mock_execute):
        mock_execute.side_effect = [
            processutils.ProcessExecutionError,
            mock.DEFAULT,
        ]

        libvirt_utils.copy_image('src', 'dest', host='host')

        mock_execute.assert_has_calls([
            self._rsync_call('--dry-run', 'src', 'host:dest'),
            mock.call('scp', 'src', 'host:dest'),
        ])
        self.assertEqual(2, mock_execute.call_count)

    @mock.patch('os.path.exists', return_value=True)
    def test_disk_type(self, mock_exists):
        # Seems like lvm detection
        # if its in /dev ??
        for p in ['/dev/b', '/dev/blah/blah']:
            d_type = libvirt_utils.get_disk_type(p)
            self.assertEqual('lvm', d_type)

        # Try rbd detection
        d_type = libvirt_utils.get_disk_type('rbd:pool/instance')
        self.assertEqual('rbd', d_type)

        # Try the other types
        template_output = """image: %(path)s
file format: %(format)s
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
"""
        path = '/myhome/disk.config'
        for f in ['raw', 'qcow2']:
            output = template_output % ({
                'format': f,
                'path': path,
            })
            with mock.patch('nova.utils.execute',
                return_value=(output, '')) as mock_execute:
                d_type = libvirt_utils.get_disk_type(path)
                mock_execute.assert_called_once_with(
                    'env', 'LC_ALL=C', 'LANG=C',
                    'qemu-img', 'info', path)
                self.assertEqual(f, d_type)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_disk_backing(self, mock_execute, mock_exists):
        path = '/myhome/disk.config'
        template_output = """image: %(path)s
file format: raw
virtual size: 2K (2048 bytes)
cluster_size: 65536
disk size: 96K
"""
        output = template_output % ({
            'path': path,
        })
        mock_execute.return_value = (output, '')
        d_backing = libvirt_utils.get_disk_backing_file(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertIsNone(d_backing)

    def _test_disk_size(self, mock_execute, path, expected_size):
        d_size = libvirt_utils.get_disk_size(path)
        self.assertEqual(expected_size, d_size)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)

    @mock.patch('os.path.exists', return_value=True)
    def test_disk_size(self, mock_exists):
        path = '/myhome/disk.config'
        template_output = """image: %(path)s
file format: raw
virtual size: %(v_size)s (%(vsize_b)s bytes)
cluster_size: 65536
disk size: 96K
"""
        for i in range(0, 128):
            bytes = i * 65336
            kbytes = bytes / 1024
            mbytes = kbytes / 1024
            output = template_output % ({
                'v_size': "%sM" % (mbytes),
                'vsize_b': i,
                'path': path,
            })
            with mock.patch('nova.utils.execute',
                return_value=(output, '')) as mock_execute:
                self._test_disk_size(mock_execute, path, i)
            output = template_output % ({
                'v_size': "%sK" % (kbytes),
                'vsize_b': i,
                'path': path,
            })
            with mock.patch('nova.utils.execute',
                return_value=(output, '')) as mock_execute:
                self._test_disk_size(mock_execute, path, i)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_canon(self, mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
blah BLAH: bb
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_canon2(self, mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: QCOW2
virtual size: 67108844
cluster_size: 65536
disk size: 963434
backing file: /var/lib/nova/a328c7998805951a_2
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('qcow2', image_info.file_format)
        self.assertEqual(67108844, image_info.virtual_size)
        self.assertEqual(963434, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)
        self.assertEqual('/var/lib/nova/a328c7998805951a_2',
                         image_info.backing_file)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_backing_file_actual(self,
                                      mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1     d9a9784a500742a7bb95627bb3aace38      0 2012-08-20 10:52:46 00:00:00.000
backing file: /var/lib/nova/a328c7998805951a_2 (actual path: /b/3a988059e51a_2)
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(1, len(image_info.snapshots))
        self.assertEqual('/b/3a988059e51a_2',
                         image_info.backing_file)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_convert(self, mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
3        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
4        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
junk stuff: bbb
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_snaps(self, mock_execute, mock_exists):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
3        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
4        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(3, len(image_info.snapshots))

    def test_valid_hostname_normal(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("hello.world.com"))

    def test_valid_hostname_ipv4addr(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("10.0.2.1"))

    def test_valid_hostname_ipv6addr(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("240:2ac3::2"))

    def test_valid_hostname_bad(self):
        self.assertFalse(libvirt_utils.is_valid_hostname("foo/?com=/bin/sh"))

    @mock.patch('nova.utils.execute')
    def test_create_image(self, mock_execute):
        libvirt_utils.create_image('raw', '/some/path', '10G')
        libvirt_utils.create_image('qcow2', '/some/stuff', '1234567891234')
        expected_args = [(('qemu-img', 'create', '-f', 'raw',
                           '/some/path', '10G'),),
                         (('qemu-img', 'create', '-f', 'qcow2',
                           '/some/stuff', '1234567891234'),)]
        self.assertEqual(expected_args, mock_execute.call_args_list)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_create_cow_image(self, mock_execute, mock_exists):
        mock_execute.return_value = ('stdout', None)
        libvirt_utils.create_cow_image('/some/path', '/the/new/cow')
        expected_args = [(('env', 'LC_ALL=C', 'LANG=C',
                           'qemu-img', 'info', '/some/path'),),
                         (('qemu-img', 'create', '-f', 'qcow2',
                           '-o', 'backing_file=/some/path',
                           '/the/new/cow'),)]
        self.assertEqual(expected_args, mock_execute.call_args_list)

    def test_pick_disk_driver_name(self):
        type_map = {'kvm': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'qemu': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'xen': ([True, 'phy'], [False, 'qemu'], [None, 'qemu']),
                    'uml': ([True, None], [False, None], [None, None]),
                    'lxc': ([True, None], [False, None], [None, None])}

        for (virt_type, checks) in type_map.iteritems():
            if virt_type == "xen":
                # NOTE(aloga): Xen is tested in test_pick_disk_driver_name_xen
                version = 4004000
            else:
                version = 1005001

            self.flags(virt_type=virt_type, group='libvirt')
            for (is_block_dev, expected_result) in checks:
                result = libvirt_utils.pick_disk_driver_name(version,
                                                             is_block_dev)
                self.assertEqual(result, expected_result)

    def test_pick_disk_driver_name_xen(self):
        version_map = ((4000000, "tap"),
                       (4001000, "tap2"),
                       (4002000, "qemu"))
        self.flags(virt_type="xen", group='libvirt')
        for ver, drv in version_map:
            result = libvirt_utils.pick_disk_driver_name(ver, False)
            self.assertEqual(drv, result)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_get_disk_size(self, mock_execute, mock_exists):
        path = '/some/path'
        example_output = """image: 00000001
file format: raw
virtual size: 4.4M (4592640 bytes)
disk size: 4.4M
"""
        mock_execute.return_value = (example_output, '')
        self.assertEqual(4592640, disk.get_disk_size('/some/path'))
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path)
        mock_exists.assert_called_once_with(path)

    def test_copy_image(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            src_fd, src_path = tempfile.mkstemp()
            try:
                with os.fdopen(src_fd, 'w') as fp:
                    fp.write('canary')

                libvirt_utils.copy_image(src_path, dst_path)
                with open(dst_path, 'r') as fp:
                    self.assertEqual(fp.read(), 'canary')
            finally:
                os.unlink(src_path)
        finally:
            os.unlink(dst_path)

    def test_write_to_file(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            libvirt_utils.write_to_file(dst_path, 'hello')
            with open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
        finally:
            os.unlink(dst_path)

    def test_write_to_file_with_umask(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)
            os.unlink(dst_path)

            libvirt_utils.write_to_file(dst_path, 'hello', umask=0o277)
            with open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
            mode = os.stat(dst_path).st_mode
            self.assertEqual(mode & 0o277, 0)
        finally:
            os.unlink(dst_path)

    @mock.patch.object(utils, 'execute')
    def test_chown(self, mock_execute):
        libvirt_utils.chown('/some/path', 'soren')
        mock_execute.assert_called_once_with('chown', 'soren', '/some/path',
                                             run_as_root=True)

    @mock.patch.object(utils, 'execute')
    def test_chown_for_id_maps(self, mock_execute):
        id_maps = [vconfig.LibvirtConfigGuestUIDMap(),
                   vconfig.LibvirtConfigGuestUIDMap(),
                   vconfig.LibvirtConfigGuestGIDMap(),
                   vconfig.LibvirtConfigGuestGIDMap()]
        id_maps[0].target = 10000
        id_maps[0].count = 2000
        id_maps[1].start = 2000
        id_maps[1].target = 40000
        id_maps[1].count = 2000
        id_maps[2].target = 10000
        id_maps[2].count = 2000
        id_maps[3].start = 2000
        id_maps[3].target = 40000
        id_maps[3].count = 2000
        libvirt_utils.chown_for_id_maps('/some/path', id_maps)
        execute_args = ('nova-idmapshift', '-i',
                        '-u', '0:10000:2000,2000:40000:2000',
                        '-g', '0:10000:2000,2000:40000:2000',
                        '/some/path')
        mock_execute.assert_called_once_with(*execute_args, run_as_root=True)

    def _do_test_extract_snapshot(self, mock_execute,
                                  dest_format='raw', out_format='raw'):
        libvirt_utils.extract_snapshot('/path/to/disk/image', 'qcow2',
                                       '/extracted/snap', dest_format)
        mock_execute.assert_called_once_with(
            'qemu-img', 'convert', '-f', 'qcow2', '-O', out_format,
            '/path/to/disk/image', '/extracted/snap')

    @mock.patch.object(utils, 'execute')
    def test_extract_snapshot_raw(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute)

    @mock.patch.object(utils, 'execute')
    def test_extract_snapshot_iso(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute, dest_format='iso')

    @mock.patch.object(utils, 'execute')
    def test_extract_snapshot_qcow2(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute,
                                       dest_format='qcow2', out_format='qcow2')

    def test_load_file(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            # We have a test for write_to_file. If that is sound, this suffices
            libvirt_utils.write_to_file(dst_path, 'hello')
            self.assertEqual(libvirt_utils.load_file(dst_path), 'hello')
        finally:
            os.unlink(dst_path)

    def test_file_open(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            # We have a test for write_to_file. If that is sound, this suffices
            libvirt_utils.write_to_file(dst_path, 'hello')
            with libvirt_utils.file_open(dst_path, 'r') as fp:
                self.assertEqual(fp.read(), 'hello')
        finally:
            os.unlink(dst_path)

    def test_get_fs_info(self):

        class FakeStatResult(object):

            def __init__(self):
                self.f_bsize = 4096
                self.f_frsize = 4096
                self.f_blocks = 2000
                self.f_bfree = 1000
                self.f_bavail = 900
                self.f_files = 2000
                self.f_ffree = 1000
                self.f_favail = 900
                self.f_flag = 4096
                self.f_namemax = 255

        self.path = None

        def fake_statvfs(path):
            self.path = path
            return FakeStatResult()

        self.stubs.Set(os, 'statvfs', fake_statvfs)

        fs_info = libvirt_utils.get_fs_info('/some/file/path')
        self.assertEqual('/some/file/path', self.path)
        self.assertEqual(8192000, fs_info['total'])
        self.assertEqual(3686400, fs_info['free'])
        self.assertEqual(4096000, fs_info['used'])

    @mock.patch('nova.virt.images.fetch_to_raw')
    def test_fetch_image(self, mock_images):
        context = 'opaque context'
        target = '/tmp/targetfile'
        image_id = '4'
        user_id = 'fake'
        project_id = 'fake'
        libvirt_utils.fetch_image(context, target, image_id,
                                  user_id, project_id)
        mock_images.assert_called_once_with(
            context, image_id, target, user_id, project_id,
            max_size=0)

    def test_fetch_raw_image(self):

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        def fake_rename(old, new):
            self.executes.append(('mv', old, new))

        def fake_unlink(path):
            self.executes.append(('rm', path))

        def fake_rm_on_error(path, remove=None):
            self.executes.append(('rm', '-f', path))

        def fake_qemu_img_info(path):
            class FakeImgInfo(object):
                pass

            file_format = path.split('.')[-1]
            if file_format == 'part':
                file_format = path.split('.')[-2]
            elif file_format == 'converted':
                file_format = 'raw'

            if 'backing' in path:
                backing_file = 'backing'
            else:
                backing_file = None

            if 'big' in path:
                virtual_size = 2
            else:
                virtual_size = 1

            FakeImgInfo.file_format = file_format
            FakeImgInfo.backing_file = backing_file
            FakeImgInfo.virtual_size = virtual_size

            return FakeImgInfo()

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os, 'rename', fake_rename)
        self.stubs.Set(os, 'unlink', fake_unlink)
        self.stubs.Set(images, 'fetch', lambda *_, **__: None)
        self.stubs.Set(images, 'qemu_img_info', fake_qemu_img_info)
        self.stubs.Set(fileutils, 'delete_if_exists', fake_rm_on_error)

        # Since the remove param of fileutils.remove_path_on_error()
        # is initialized at load time, we must provide a wrapper
        # that explicitly resets it to our fake delete_if_exists()
        old_rm_path_on_error = fileutils.remove_path_on_error
        f = functools.partial(old_rm_path_on_error, remove=fake_rm_on_error)
        self.stubs.Set(fileutils, 'remove_path_on_error', f)

        context = 'opaque context'
        image_id = '4'
        user_id = 'fake'
        project_id = 'fake'

        target = 't.qcow2'
        self.executes = []
        expected_commands = [('qemu-img', 'convert', '-O', 'raw',
                              't.qcow2.part', 't.qcow2.converted'),
                             ('rm', 't.qcow2.part'),
                             ('mv', 't.qcow2.converted', 't.qcow2')]
        images.fetch_to_raw(context, image_id, target, user_id, project_id,
                            max_size=1)
        self.assertEqual(self.executes, expected_commands)

        target = 't.raw'
        self.executes = []
        expected_commands = [('mv', 't.raw.part', 't.raw')]
        images.fetch_to_raw(context, image_id, target, user_id, project_id)
        self.assertEqual(self.executes, expected_commands)

        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw,
                          context, image_id, target, user_id, project_id)
        self.assertEqual(self.executes, expected_commands)

        target = 'big.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'big.qcow2.part')]
        self.assertRaises(exception.FlavorDiskTooSmall,
                          images.fetch_to_raw,
                          context, image_id, target, user_id, project_id,
                          max_size=1)
        self.assertEqual(self.executes, expected_commands)

        del self.executes

    def test_get_disk_backing_file(self):
        with_actual_path = False

        def fake_execute(*args, **kwargs):
            if with_actual_path:
                return ("some: output\n"
                        "backing file: /foo/bar/baz (actual path: /a/b/c)\n"
                        "...: ...\n"), ''
            else:
                return ("some: output\n"
                        "backing file: /foo/bar/baz\n"
                        "...: ...\n"), ''

        def return_true(*args, **kwargs):
            return True

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os.path, 'exists', return_true)

        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'baz')
        with_actual_path = True
        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'c')

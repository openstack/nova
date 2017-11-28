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

import ddt
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import fileutils
import six

from nova import context
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt.disk import api as disk
from nova.virt import images
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


@ddt.ddt
class LibvirtUtilsTestCase(test.NoDBTestCase):

    @mock.patch('nova.utils.execute')
    def test_copy_image_local(self, mock_execute):
        libvirt_utils.copy_image('src', 'dest')
        mock_execute.assert_called_once_with('cp', '-r', 'src', 'dest')

    @mock.patch('nova.virt.libvirt.volume.remotefs.SshDriver.copy_file')
    def test_copy_image_remote_ssh(self, mock_rem_fs_remove):
        self.flags(remote_filesystem_transport='ssh', group='libvirt')
        libvirt_utils.copy_image('src', 'dest', host='host')
        mock_rem_fs_remove.assert_called_once_with('src', 'host:dest',
            on_completion=None, on_execute=None, compression=True)

    @mock.patch('nova.virt.libvirt.volume.remotefs.RsyncDriver.copy_file')
    def test_copy_image_remote_rsync(self, mock_rem_fs_remove):
        self.flags(remote_filesystem_transport='rsync', group='libvirt')
        libvirt_utils.copy_image('src', 'dest', host='host')
        mock_rem_fs_remove.assert_called_once_with('src', 'host:dest',
            on_completion=None, on_execute=None, compression=True)

    @mock.patch('os.path.exists', return_value=True)
    def test_disk_type_from_path(self, mock_exists):
        # Seems like lvm detection
        # if its in /dev ??
        for p in ['/dev/b', '/dev/blah/blah']:
            d_type = libvirt_utils.get_disk_type_from_path(p)
            self.assertEqual('lvm', d_type)

        # Try rbd detection
        d_type = libvirt_utils.get_disk_type_from_path('rbd:pool/instance')
        self.assertEqual('rbd', d_type)

        # Try the other types
        path = '/myhome/disk.config'
        d_type = libvirt_utils.get_disk_type_from_path(path)
        self.assertIsNone(d_type)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.path.isdir', return_value=True)
    def test_disk_type_ploop(self, mock_isdir, mock_exists):
        path = '/some/path'
        d_type = libvirt_utils.get_disk_type_from_path(path)
        mock_isdir.assert_called_once_with(path)
        mock_exists.assert_called_once_with("%s/DiskDescriptor.xml" % path)
        self.assertEqual('ploop', d_type)

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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
        mock_exists.assert_called_once_with(path)
        self.assertIsNone(d_backing)

    def _test_disk_size(self, mock_execute, path, expected_size):
        d_size = libvirt_utils.get_disk_size(path)
        self.assertEqual(expected_size, d_size)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)

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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_canon_qemu_2_10(self, mock_execute, mock_exists):
        images.QEMU_VERSION = images.QEMU_VERSION_REQ_SHARED
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
                                             'qemu-img', 'info', path,
                                             '--force-share',
                                             prlimit=images.QEMU_IMG_LIMITS)
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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
        mock_exists.assert_called_once_with(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('qcow2', image_info.file_format)
        self.assertEqual(67108844, image_info.virtual_size)
        self.assertEqual(963434, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)
        self.assertEqual('/var/lib/nova/a328c7998805951a_2',
                         image_info.backing_file)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.path.isdir', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_qemu_info_ploop(self, mock_execute, mock_isdir, mock_exists):
        path = "/var/lib/nova"
        example_output = """image: root.hds
file format: parallels
virtual size: 3.0G (3221225472 bytes)
disk size: 706M
"""
        mock_execute.return_value = (example_output, '')
        image_info = images.qemu_img_info(path)
        mock_execute.assert_called_once_with('env', 'LC_ALL=C', 'LANG=C',
                                             'qemu-img', 'info',
                                             os.path.join(path, 'root.hds'),
                                             prlimit=images.QEMU_IMG_LIMITS)
        mock_isdir.assert_called_once_with(path)
        self.assertEqual(2, mock_exists.call_count)
        self.assertEqual(path, mock_exists.call_args_list[0][0][0])
        self.assertEqual(os.path.join(path, 'DiskDescriptor.xml'),
                             mock_exists.call_args_list[1][0][0])
        self.assertEqual('root.hds', image_info.image)
        self.assertEqual('parallels', image_info.file_format)
        self.assertEqual(3221225472, image_info.virtual_size)
        self.assertEqual(740294656, image_info.disk_size)

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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
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
                           'qemu-img', 'info', '/some/path'),
                           {'prlimit': images.QEMU_IMG_LIMITS}),
                         (('qemu-img', 'create', '-f', 'qcow2',
                           '-o', 'backing_file=/some/path',
                           '/the/new/cow'),)]
        self.assertEqual(expected_args, mock_execute.call_args_list)

    @ddt.unpack
    @ddt.data({'fs_type': 'some_fs_type',
               'default_eph_format': None,
               'expected_fs_type': 'some_fs_type'},
              {'fs_type': None,
               'default_eph_format': None,
               'expected_fs_type': disk.FS_FORMAT_EXT4},
              {'fs_type': None,
               'default_eph_format': 'eph_format',
               'expected_fs_type': 'eph_format'})
    def test_create_ploop_image(self, fs_type,
                                default_eph_format,
                                expected_fs_type):
        with test.nested(mock.patch('oslo_utils.fileutils.ensure_tree'),
                         mock.patch('nova.privsep.libvirt.ploop_init')
                         ) as (mock_ensure_tree, mock_ploop_init):
            self.flags(default_ephemeral_format=default_eph_format)
            libvirt_utils.create_ploop_image('expanded', '/some/path',
                                             '5G', fs_type)
            mock_ensure_tree.assert_has_calls([
                mock.call('/some/path')])
            mock_ploop_init.assert_has_calls([
                mock.call('5G', 'expanded', expected_fs_type,
                          '/some/path/root.hds')])

    def test_pick_disk_driver_name(self):
        type_map = {'kvm': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'qemu': ([True, 'qemu'], [False, 'qemu'], [None, 'qemu']),
                    'uml': ([True, None], [False, None], [None, None]),
                    'lxc': ([True, None], [False, None], [None, None])}
        # NOTE(aloga): Xen is tested in test_pick_disk_driver_name_xen

        version = 1005001
        for (virt_type, checks) in type_map.items():
            self.flags(virt_type=virt_type, group='libvirt')
            for (is_block_dev, expected_result) in checks:
                result = libvirt_utils.pick_disk_driver_name(version,
                                                             is_block_dev)
                self.assertEqual(result, expected_result)

    @mock.patch('nova.privsep.libvirt.xend_probe')
    @mock.patch('nova.utils.execute')
    def test_pick_disk_driver_name_xen(self, mock_execute, mock_xend_probe):

        def execute_side_effect(*args, **kwargs):
            if args == ('tap-ctl', 'check'):
                if mock_execute.blktap is True:
                    return ('ok\n', '')
                elif mock_execute.blktap is False:
                    return ('some error\n', '')
                else:
                    raise OSError(2, "No such file or directory")
            raise Exception('Unexpected call')
        mock_execute.side_effect = execute_side_effect

        def xend_probe_side_effect():
            if mock_execute.xend is True:
                return ('', '')
            elif mock_execute.xend is False:
                raise processutils.ProcessExecutionError("error")
            else:
                raise OSError(2, "No such file or directory")
        mock_xend_probe.side_effect = xend_probe_side_effect

        self.flags(virt_type="xen", group='libvirt')
        versions = [4000000, 4001000, 4002000, 4003000, 4005000]
        for version in versions:
            # block dev
            result = libvirt_utils.pick_disk_driver_name(version, True)
            self.assertEqual(result, "phy")
            self.assertFalse(mock_execute.called)
            mock_execute.reset_mock()
            # file dev
            for blktap in True, False, None:
                mock_execute.blktap = blktap
                for xend in True, False, None:
                    mock_execute.xend = xend
                    result = libvirt_utils.pick_disk_driver_name(version,
                                                                 False)
                    # qemu backend supported only by libxl which is
                    # production since xen 4.2. libvirt use libxl if
                    # xend service not started.
                    if version >= 4002000 and xend is not True:
                        self.assertEqual(result, 'qemu')
                    elif blktap:
                        if version == 4000000:
                            self.assertEqual(result, 'tap')
                        else:
                            self.assertEqual(result, 'tap2')
                    else:
                        self.assertEqual(result, 'file')
                    # default is_block_dev False
                    self.assertEqual(result,
                        libvirt_utils.pick_disk_driver_name(version))
                    mock_execute.reset_mock()

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
                                             'qemu-img', 'info', path,
                                             prlimit=images.QEMU_IMG_LIMITS)
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

    def _do_test_extract_snapshot(self, mock_execute, src_format='qcow2',
                                  dest_format='raw', out_format='raw'):
        libvirt_utils.extract_snapshot('/path/to/disk/image', src_format,
                                       '/extracted/snap', dest_format)
        qemu_img_cmd = ('qemu-img', 'convert', '-f',
                        src_format, '-O', out_format)
        if CONF.libvirt.snapshot_compression and dest_format == "qcow2":
            qemu_img_cmd += ('-c',)
        qemu_img_cmd += ('/path/to/disk/image', '/extracted/snap')
        mock_execute.assert_called_once_with(*qemu_img_cmd)

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

    @mock.patch.object(utils, 'execute')
    def test_extract_snapshot_qcow2_and_compression(self, mock_execute):
        self.flags(snapshot_compression=True, group='libvirt')
        self._do_test_extract_snapshot(mock_execute,
                                       dest_format='qcow2', out_format='qcow2')

    @mock.patch.object(utils, 'execute')
    def test_extract_snapshot_parallels(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute,
                                       src_format='raw',
                                       dest_format='ploop',
                                       out_format='parallels')

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

        self.stub_out('os.statvfs', fake_statvfs)

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
        libvirt_utils.fetch_image(context, target, image_id)
        mock_images.assert_called_once_with(
            context, image_id, target)

    @mock.patch('nova.virt.images.fetch')
    def test_fetch_initrd_image(self, mock_images):
        _context = context.RequestContext(project_id=123,
                                          project_name="aubergine",
                                          user_id=456,
                                          user_name="pie")
        target = '/tmp/targetfile'
        image_id = '4'
        libvirt_utils.fetch_raw_image(_context, target, image_id)
        mock_images.assert_called_once_with(
            _context, image_id, target)

    @mock.patch('nova.utils.supports_direct_io', return_value=True)
    def test_fetch_raw_image(self, mock_direct_io):

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

            FakeImgInfo.file_format = file_format
            FakeImgInfo.backing_file = backing_file
            FakeImgInfo.virtual_size = 1

            return FakeImgInfo()

        self.stub_out('nova.utils.execute', fake_execute)
        self.stub_out('os.rename', fake_rename)
        self.stub_out('os.unlink', fake_unlink)
        self.stub_out('nova.virt.images.fetch', lambda *_, **__: None)
        self.stub_out('nova.virt.images.qemu_img_info', fake_qemu_img_info)
        self.stub_out('oslo_utils.fileutils.delete_if_exists',
                      fake_rm_on_error)

        # Since the remove param of fileutils.remove_path_on_error()
        # is initialized at load time, we must provide a wrapper
        # that explicitly resets it to our fake delete_if_exists()
        old_rm_path_on_error = fileutils.remove_path_on_error
        f = functools.partial(old_rm_path_on_error, remove=fake_rm_on_error)
        self.stub_out('oslo_utils.fileutils.remove_path_on_error', f)

        context = 'opaque context'
        image_id = '4'

        target = 't.qcow2'
        self.executes = []
        expected_commands = [('qemu-img', 'convert', '-t', 'none',
                              '-O', 'raw', '-f', 'qcow2',
                              't.qcow2.part', 't.qcow2.converted'),
                             ('rm', 't.qcow2.part'),
                             ('mv', 't.qcow2.converted', 't.qcow2')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(self.executes, expected_commands)

        target = 't.raw'
        self.executes = []
        expected_commands = [('mv', 't.raw.part', 't.raw')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(self.executes, expected_commands)

        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw, context, image_id, target)
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

        self.stub_out('nova.utils.execute', fake_execute)
        self.stub_out('os.path.exists', return_true)

        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'baz')
        with_actual_path = True
        out = libvirt_utils.get_disk_backing_file('')
        self.assertEqual(out, 'c')

    def test_get_instance_path_at_destination(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                   uuid=uuids.instance)

        migrate_data = None
        inst_path_at_dest = libvirt_utils.get_instance_path_at_destination(
            instance, migrate_data)
        expected_path = os.path.join(CONF.instances_path, instance['uuid'])
        self.assertEqual(expected_path, inst_path_at_dest)

        migrate_data = {}
        inst_path_at_dest = libvirt_utils.get_instance_path_at_destination(
            instance, migrate_data)
        expected_path = os.path.join(CONF.instances_path, instance['uuid'])
        self.assertEqual(expected_path, inst_path_at_dest)

        migrate_data = objects.LibvirtLiveMigrateData(
            instance_relative_path='fake_relative_path')
        inst_path_at_dest = libvirt_utils.get_instance_path_at_destination(
            instance, migrate_data)
        expected_path = os.path.join(CONF.instances_path, 'fake_relative_path')
        self.assertEqual(expected_path, inst_path_at_dest)

    def test_get_arch(self):
        image_meta = objects.ImageMeta.from_dict(
            {'properties': {'architecture': "X86_64"}})
        image_arch = libvirt_utils.get_arch(image_meta)
        self.assertEqual(obj_fields.Architecture.X86_64, image_arch)

    def test_is_mounted(self):
        mount_path = "/var/lib/nova/mnt"
        source = "192.168.0.1:/nova"
        proc_with_mnt = """/dev/sda3 / xfs rw,seclabel,attr2,inode64 0 0
tmpfs /tmp tmpfs rw,seclabel 0 0
hugetlbfs /dev/hugepages hugetlbfs rw,seclabel,relatime 0 0
mqueue /dev/mqueue mqueue rw,seclabel,relatime 0 0
debugfs /sys/kernel/debug debugfs rw,seclabel,relatime 0 0
nfsd /proc/fs/nfsd nfsd rw,relatime 0 0
/dev/sda1 /boot ext4 rw,seclabel,relatime,data=ordered 0 0
sunrpc /var/lib/nfs/rpc_pipefs rpc_pipefs rw,relatime 0 0
192.168.0.1:/nova /var/lib/nova/mnt nfs4 rw,relatime,vers=4.1
"""
        proc_wrong_mnt = """/dev/sda3 / xfs rw,seclabel,attr2,inode64 0 0
tmpfs /tmp tmpfs rw,seclabel 0 0
hugetlbfs /dev/hugepages hugetlbfs rw,seclabel,relatime 0 0
mqueue /dev/mqueue mqueue rw,seclabel,relatime 0 0
debugfs /sys/kernel/debug debugfs rw,seclabel,relatime 0 0
nfsd /proc/fs/nfsd nfsd rw,relatime 0 0
/dev/sda1 /boot ext4 rw,seclabel,relatime,data=ordered 0 0
sunrpc /var/lib/nfs/rpc_pipefs rpc_pipefs rw,relatime 0 0
192.168.0.2:/nova /var/lib/nova/mnt nfs4 rw,relatime,vers=4.1
"""
        proc_without_mnt = """/dev/sda3 / xfs rw,seclabel,,attr2,inode64 0 0
tmpfs /tmp tmpfs rw,seclabel 0 0
hugetlbfs /dev/hugepages hugetlbfs rw,seclabel,relatime 0 0
mqueue /dev/mqueue mqueue rw,seclabel,relatime 0 0
debugfs /sys/kernel/debug debugfs rw,seclabel,relatime 0 0
nfsd /proc/fs/nfsd nfsd rw,relatime 0 0
/dev/sda1 /boot ext4 rw,seclabel,relatime,data=ordered 0 0
sunrpc /var/lib/nfs/rpc_pipefs rpc_pipefs rw,relatime 0 0
"""
        with mock.patch.object(os.path, 'ismount') as mock_ismount:
            # is_mounted(mount_path) with no source is equivalent to
            # os.path.ismount(mount_path)
            mock_ismount.return_value = False
            self.assertFalse(libvirt_utils.is_mounted(mount_path))

            mock_ismount.return_value = True
            self.assertTrue(libvirt_utils.is_mounted(mount_path))

            # Source is given, and matches source in /proc/mounts
            proc_mnt = mock.mock_open(read_data=proc_with_mnt)
            with mock.patch.object(six.moves.builtins, "open", proc_mnt):
                self.assertTrue(libvirt_utils.is_mounted(mount_path, source))

            # Source is given, and doesn't match source in /proc/mounts
            proc_mnt = mock.mock_open(read_data=proc_wrong_mnt)
            with mock.patch.object(six.moves.builtins, "open", proc_mnt):
                self.assertFalse(libvirt_utils.is_mounted(mount_path, source))

            # Source is given, and mountpoint isn't present in /proc/mounts
            # Note that this shouldn't occur, as os.path.ismount should have
            # previously returned False in this case.
            proc_umnt = mock.mock_open(read_data=proc_without_mnt)
            with mock.patch.object(six.moves.builtins, "open", proc_umnt):
                self.assertFalse(libvirt_utils.is_mounted(mount_path, source))

    def test_find_disk_file_device(self):
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        xml = """
          <domain type='kvm'>
            <os>
              <type>linux</type>
            </os>
            <devices>
              <disk type="file" device="disk">
                <driver name="qemu" type="qcow2" cache="none" io="native"/>
                <source file="/tmp/hello"/>
                <target bus="ide" dev="/dev/hda"/>
              </disk>
            </devices>
          </domain>
        """
        virt_dom = mock.Mock(XMLDesc=mock.Mock(return_value=xml))
        guest = libvirt_guest.Guest(virt_dom)
        disk_path, format = libvirt_utils.find_disk(guest)
        self.assertEqual('/tmp/hello', disk_path)
        self.assertEqual('qcow2', format)

    def test_find_disk_block_device(self):
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        xml = """
          <domain type='kvm'>
            <os>
              <type>linux</type>
            </os>
            <devices>
              <disk type="block" device="disk">
                <driver name="qemu" type="raw"/>
                <source dev="/dev/nova-vg/hello"/>
                <target bus="ide" dev="/dev/hda"/>
              </disk>
            </devices>
          </domain>
        """
        virt_dom = mock.Mock(XMLDesc=mock.Mock(return_value=xml))
        guest = libvirt_guest.Guest(virt_dom)
        disk_path, format = libvirt_utils.find_disk(guest)
        self.assertEqual('/dev/nova-vg/hello', disk_path)
        self.assertEqual('raw', format)

    def test_find_disk_rbd(self):
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        xml = """
          <domain type='kvm'>
            <os>
              <type>linux</type>
            </os>
            <devices>
              <disk type="network" device="disk">
                <driver name="qemu" type="raw"/>
                <source name="pool/image" protocol="rbd">
                  <host name="1.2.3.4" port="456"/>
                </source>
                <target bus="virtio" dev="/dev/vda"/>
              </disk>
            </devices>
          </domain>
        """
        virt_dom = mock.Mock(XMLDesc=mock.Mock(return_value=xml))
        guest = libvirt_guest.Guest(virt_dom)
        disk_path, format = libvirt_utils.find_disk(guest)
        self.assertEqual('rbd:pool/image', disk_path)
        self.assertEqual('raw', format)

    def test_find_disk_lxc(self):
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        xml = """
          <domain type='lxc'>
            <os>
              <type>exe</type>
            </os>
            <devices>
              <filesystem type="mount">
                <source dir="/myhome/rootfs"/>
                <target dir="/"/>
              </filesystem>
            </devices>
          </domain>
        """
        virt_dom = mock.Mock(XMLDesc=mock.Mock(return_value=xml))
        guest = libvirt_guest.Guest(virt_dom)
        disk_path, format = libvirt_utils.find_disk(guest)
        self.assertEqual('/myhome/disk', disk_path)
        self.assertIsNone(format)

    def test_find_disk_parallels(self):
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        xml = """
          <domain type='parallels'>
            <os>
              <type>exe</type>
            </os>
            <devices>
              <filesystem type='file'>"
                <driver format='ploop' type='ploop'/>"
                <source file='/test/disk'/>"
                <target dir='/'/>
              </filesystem>"
            </devices>
          </domain>
        """
        virt_dom = mock.Mock(XMLDesc=mock.Mock(return_value=xml))
        guest = libvirt_guest.Guest(virt_dom)
        disk_path, format = libvirt_utils.find_disk(guest)
        self.assertEqual('/test/disk', disk_path)
        self.assertEqual('ploop', format)

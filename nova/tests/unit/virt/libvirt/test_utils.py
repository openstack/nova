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
import grp
import os
import pwd
import tempfile
from unittest import mock

import ddt
import os_traits
from oslo_config import cfg
from oslo_utils import fileutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import utils as compute_utils
from nova import context
from nova import exception
from nova.image import format_inspector
from nova import objects
from nova.objects import fields as obj_fields
import nova.privsep.fs
import nova.privsep.qemu
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_instance
from nova.virt import images
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


@ddt.ddt
class LibvirtUtilsTestCase(test.NoDBTestCase):

    @mock.patch('oslo_concurrency.processutils.execute')
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

    def test_valid_hostname_normal(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("hello.world.com"))

    def test_valid_hostname_ipv4addr(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("10.0.2.1"))

    def test_valid_hostname_ipv6addr(self):
        self.assertTrue(libvirt_utils.is_valid_hostname("240:2ac3::2"))

    def test_valid_hostname_bad(self):
        self.assertFalse(libvirt_utils.is_valid_hostname("foo/?com=/bin/sh"))

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('nova.virt.images.qemu_img_info')
    @mock.patch('nova.image.format_inspector.detect_file_format')
    def _test_create_image(
        self, path, disk_format, disk_size, mock_detect, mock_info,
        mock_execute, mock_ntf, backing_file=None, encryption=None,
        safety_check=True
    ):
        if isinstance(backing_file, dict):
            backing_info = backing_file
            backing_file = backing_info.pop('file', None)
        else:
            backing_info = {}
        backing_backing_file = backing_info.pop('backing_file', None)
        backing_fmt = backing_info.pop('backing_fmt',
                                       mock.sentinel.backing_fmt)

        mock_info.return_value = mock.Mock(
            file_format=backing_fmt,
            cluster_size=mock.sentinel.cluster_size,
            backing_file=backing_backing_file,
            format_specific=backing_info,
        )
        fh = mock_ntf.return_value.__enter__.return_value

        mock_detect.return_value.safety_check.return_value = safety_check

        libvirt_utils.create_image(
            path, disk_format, disk_size, backing_file=backing_file,
            encryption=encryption,
        )

        cow_opts = []

        if backing_file is None:
            mock_info.assert_not_called()
        else:
            mock_info.assert_called_once_with(backing_file)
            cow_opts = [
                '-o',
                f'backing_file={backing_file},'
                f'backing_fmt={backing_fmt},'
                f'cluster_size={mock.sentinel.cluster_size}',
            ]

        encryption_opts = []

        if encryption:
            encryption_opts = [
                '--object', f"secret,id=sec,file={fh.name}",
                '-o', 'encrypt.key-secret=sec',
                '-o', f"encrypt.format={encryption.get('format')}",
            ]

            encryption_options = {
                'cipher-alg': 'aes-256',
                'cipher-mode': 'xts',
                'hash-alg': 'sha256',
                'iter-time': 2000,
                'ivgen-alg': 'plain64',
                'ivgen-hash-alg': 'sha256',
            }
            for option, value in encryption_options.items():
                encryption_opts += [
                    '-o',
                    f'encrypt.{option}={value}',
                ]

        expected_args = (
            'env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'create', '-f',
            disk_format, *cow_opts, *encryption_opts, path,
        )
        if disk_size is not None:
            expected_args += (disk_size,)

        self.assertEqual([(expected_args,)], mock_execute.call_args_list)
        if backing_file:
            mock_detect.return_value.safety_check.assert_called_once_with()

    def test_create_image_raw(self):
        self._test_create_image('/some/path', 'raw', '10G')

    def test_create_image_qcow2(self):
        self._test_create_image(
            '/some/stuff', 'qcow2', '1234567891234',
        )

    def test_create_image_backing_file(self):
        self._test_create_image(
            '/some/stuff', 'qcow2', '1234567891234',
            backing_file=mock.sentinel.backing_file,
        )

    def test_create_image_base_has_backing_file(self):
        self.assertRaises(
            exception.InvalidDiskInfo,
            self._test_create_image,
            '/some/stuff', 'qcow2', '1234567891234',
            backing_file={'file': mock.sentinel.backing_file,
                          'backing_file': mock.sentinel.backing_backing_file},
        )

    def test_create_image_base_has_data_file(self):
        self.assertRaises(
            exception.InvalidDiskInfo,
            self._test_create_image,
            '/some/stuff', 'qcow2', '1234567891234',
            backing_file={'file': mock.sentinel.backing_file,
                          'backing_file': mock.sentinel.backing_backing_file,
                          'data': {'data-file': mock.sentinel.data_file}},
        )

    def test_create_image_size_none(self):
        self._test_create_image(
            '/some/stuff', 'qcow2', None,
            backing_file=mock.sentinel.backing_file,
        )

    def test_create_image_vmdk(self):
        self._test_create_image(
            '/some/vmdk', 'vmdk', '1234567891234',
            backing_file={'file': mock.sentinel.backing_file,
                          'backing_fmt': 'vmdk',
                          'backing_file': None,
                          'data': {'create-type': 'monolithicSparse'}}
        )

    def test_create_image_vmdk_invalid_type(self):
        self.assertRaises(exception.ImageUnacceptable,
            self._test_create_image,
            '/some/vmdk', 'vmdk', '1234567891234',
            backing_file={'file': mock.sentinel.backing_file,
                          'backing_fmt': 'vmdk',
                          'backing_file': None,
                          'data': {'create-type': 'monolithicFlat'}}
        )

    def test_create_image_encryption(self):
        encryption = {
            'secret': 'a_secret',
            'format': 'luks',
        }
        self._test_create_image(
            '/some/stuff', 'qcow2', '1234567891234',
            encryption=encryption,
        )

    @ddt.unpack
    @ddt.data({'fs_type': 'some_fs_type',
               'default_eph_format': None,
               'expected_fs_type': 'some_fs_type'},
              {'fs_type': None,
               'default_eph_format': None,
               'expected_fs_type': nova.privsep.fs.FS_FORMAT_EXT4},
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

    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=False)
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_no_directio(self, mock_execute,
                                  mock_direct_io,
                                  mock_disk_op_sema):
        # Test a single variant with no support for direct IO.
        # This could be removed if we add unit tests for convert_image().
        src_format = 'qcow2'
        dest_format = 'raw'
        out_format = 'raw'

        libvirt_utils.extract_snapshot('/path/to/disk/image', src_format,
                                       '/extracted/snap', dest_format)
        qemu_img_cmd = ('qemu-img', 'convert', '-t', 'writeback',
                        '-O', out_format, '-f', src_format, )
        if CONF.libvirt.snapshot_compression and dest_format == "qcow2":
            qemu_img_cmd += ('-c',)
        qemu_img_cmd += ('/path/to/disk/image', '/extracted/snap')
        mock_disk_op_sema.__enter__.assert_called_once()
        mock_direct_io.assert_called_once_with(CONF.instances_path)
        mock_execute.assert_called_once_with(*qemu_img_cmd)

    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    def _do_test_extract_snapshot(self, mock_execute, mock_direct_io,
                                  mock_disk_op_sema,
                                  src_format='qcow2',
                                  dest_format='raw', out_format='raw'):
        libvirt_utils.extract_snapshot('/path/to/disk/image', src_format,
                                       '/extracted/snap', dest_format)
        qemu_img_cmd = ('qemu-img', 'convert', '-t', 'none',
                        '-O', out_format, '-f', src_format, )
        if CONF.libvirt.snapshot_compression and dest_format == "qcow2":
            qemu_img_cmd += ('-c',)
        qemu_img_cmd += ('/path/to/disk/image', '/extracted/snap')
        mock_disk_op_sema.__enter__.assert_called_once()
        mock_direct_io.assert_called_once_with(CONF.instances_path)
        mock_execute.assert_called_once_with(*qemu_img_cmd)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_raw(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute)

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_iso(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute, dest_format='iso')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_qcow2(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute,
                                       dest_format='qcow2', out_format='qcow2')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_qcow2_and_compression(self, mock_execute):
        self.flags(snapshot_compression=True, group='libvirt')
        self._do_test_extract_snapshot(mock_execute,
                                       dest_format='qcow2', out_format='qcow2')

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_extract_snapshot_parallels(self, mock_execute):
        self._do_test_extract_snapshot(mock_execute,
                                       src_format='raw',
                                       dest_format='ploop',
                                       out_format='parallels')

    def test_load_file(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            with open(dst_path, 'w') as f:
                f.write('hello')
            self.assertEqual(libvirt_utils.load_file(dst_path), 'hello')
        finally:
            os.unlink(dst_path)

    def test_file_open(self):
        dst_fd, dst_path = tempfile.mkstemp()
        try:
            os.close(dst_fd)

            with open(dst_path, 'w') as f:
                f.write('hello')
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
        trusted_certs = objects.TrustedCerts(
            ids=['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8',
                 '674736e3-f25c-405c-8362-bbf991e0ce0a'])
        libvirt_utils.fetch_image(context, target, image_id, trusted_certs)
        mock_images.assert_called_once_with(
            context, image_id, target, trusted_certs)

    @mock.patch('nova.virt.images.fetch')
    def test_fetch_initrd_image(self, mock_images):
        _context = context.RequestContext(project_id=123,
                                          project_name="aubergine",
                                          user_id=456,
                                          user_name="pie")
        target = '/tmp/targetfile'
        image_id = '4'
        trusted_certs = objects.TrustedCerts(
            ids=['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8',
                 '674736e3-f25c-405c-8362-bbf991e0ce0a'])
        libvirt_utils.fetch_raw_image(_context, target, image_id,
                                      trusted_certs)
        mock_images.assert_called_once_with(
            _context, image_id, target, trusted_certs)

    @mock.patch.object(images, 'IMAGE_API')
    @mock.patch.object(format_inspector, 'detect_file_format')
    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    @mock.patch('nova.privsep.qemu.unprivileged_convert_image')
    def test_fetch_raw_image(self, mock_convert_image, mock_direct_io,
                             mock_disk_op_sema, mock_detect, mock_glance):

        def fake_rename(old, new):
            self.executes.append(('mv', old, new))

        def fake_unlink(path):
            self.executes.append(('rm', path))

        def fake_rm_on_error(path, remove=None):
            self.executes.append(('rm', '-f', path))

        def fake_qemu_img_info(path, format=None):
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
            FakeImgInfo.format_specific = None if file_format == 'raw' else {}

            return FakeImgInfo()

        self.stub_out('os.rename', fake_rename)
        self.stub_out('os.unlink', fake_unlink)
        self.stub_out('nova.virt.images.fetch', lambda *_, **__: None)
        self.stub_out('nova.virt.images.qemu_img_info', fake_qemu_img_info)
        self.stub_out('oslo_utils.fileutils.delete_if_exists',
                      fake_rm_on_error)

        mock_inspector = mock_detect.return_value

        # Since the remove param of fileutils.remove_path_on_error()
        # is initialized at load time, we must provide a wrapper
        # that explicitly resets it to our fake delete_if_exists()
        old_rm_path_on_error = fileutils.remove_path_on_error
        f = functools.partial(old_rm_path_on_error, remove=fake_rm_on_error)
        self.stub_out('oslo_utils.fileutils.remove_path_on_error', f)

        context = 'opaque context'
        image_id = '4'

        # Make sure qcow2 gets converted to raw
        mock_inspector.safety_check.return_value = True
        mock_inspector.__str__.return_value = 'qcow2'
        mock_glance.get.return_value = {'disk_format': 'qcow2'}
        target = 't.qcow2'
        self.executes = []
        expected_commands = [('rm', 't.qcow2.part'),
                             ('mv', 't.qcow2.converted', 't.qcow2')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(self.executes, expected_commands)
        mock_disk_op_sema.__enter__.assert_called_once()
        mock_convert_image.assert_called_with(
            't.qcow2.part', 't.qcow2.converted', 'qcow2', 'raw',
            CONF.instances_path, False)
        mock_convert_image.reset_mock()
        mock_inspector.safety_check.assert_called_once_with()
        mock_detect.assert_called_once_with('t.qcow2.part')

        # Make sure raw does not get converted
        mock_detect.reset_mock()
        mock_inspector.safety_check.reset_mock()
        mock_inspector.safety_check.return_value = True
        mock_inspector.__str__.return_value = 'raw'
        mock_glance.get.return_value = {'disk_format': 'raw'}
        target = 't.raw'
        self.executes = []
        expected_commands = [('mv', 't.raw.part', 't.raw')]
        images.fetch_to_raw(context, image_id, target)
        self.assertEqual(self.executes, expected_commands)
        mock_convert_image.assert_not_called()
        mock_inspector.safety_check.assert_called_once_with()
        mock_detect.assert_called_once_with('t.raw.part')

        # Make sure safety check failure prevents us from proceeding
        mock_detect.reset_mock()
        mock_inspector.safety_check.reset_mock()
        mock_inspector.safety_check.return_value = False
        mock_inspector.__str__.return_value = 'qcow2'
        mock_glance.get.return_value = {'disk_format': 'qcow2'}
        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw, context, image_id, target)
        self.assertEqual(self.executes, expected_commands)
        mock_convert_image.assert_not_called()
        mock_inspector.safety_check.assert_called_once_with()
        mock_detect.assert_called_once_with('backing.qcow2.part')

        # Make sure a format mismatch prevents us from proceeding
        mock_detect.reset_mock()
        mock_inspector.safety_check.reset_mock()
        mock_inspector.safety_check.side_effect = (
            format_inspector.ImageFormatError)
        mock_glance.get.return_value = {'disk_format': 'qcow2'}
        target = 'backing.qcow2'
        self.executes = []
        expected_commands = [('rm', '-f', 'backing.qcow2.part')]
        self.assertRaises(exception.ImageUnacceptable,
                          images.fetch_to_raw, context, image_id, target)
        self.assertEqual(self.executes, expected_commands)
        mock_convert_image.assert_not_called()
        mock_inspector.safety_check.assert_called_once_with()
        mock_detect.assert_called_once_with('backing.qcow2.part')

        del self.executes

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
            with mock.patch('builtins.open', proc_mnt):
                self.assertTrue(libvirt_utils.is_mounted(mount_path, source))

            # Source is given, and doesn't match source in /proc/mounts
            proc_mnt = mock.mock_open(read_data=proc_wrong_mnt)
            with mock.patch('builtins.open', proc_mnt):
                self.assertFalse(libvirt_utils.is_mounted(mount_path, source))

            # Source is given, and mountpoint isn't present in /proc/mounts
            # Note that this shouldn't occur, as os.path.ismount should have
            # previously returned False in this case.
            proc_umnt = mock.mock_open(read_data=proc_without_mnt)
            with mock.patch('builtins.open', proc_umnt):
                self.assertFalse(libvirt_utils.is_mounted(mount_path, source))

    def test_find_disk_file_device(self):
        self.useFixture(nova_fixtures.LibvirtFixture())
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
        self.useFixture(nova_fixtures.LibvirtFixture())
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
        self.useFixture(nova_fixtures.LibvirtFixture())
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
        self.useFixture(nova_fixtures.LibvirtFixture())
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
        self.useFixture(nova_fixtures.LibvirtFixture())
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

    @mock.patch('nova.virt.libvirt.utils.get_arch')
    def test_get_machine_type_from_fallbacks(self, mock_get_arch):
        """Test hardcoded arch-specific fallbacks for default machine type"""
        image_meta = objects.ImageMeta.from_dict({"disk_format": "raw"})
        host_cpu_archs = {
            obj_fields.Architecture.ARMV7: "virt",
            obj_fields.Architecture.AARCH64: "virt",
            obj_fields.Architecture.S390: "s390-ccw-virtio",
            obj_fields.Architecture.S390X: "s390-ccw-virtio",
            obj_fields.Architecture.I686: "pc",
            obj_fields.Architecture.X86_64: "pc",
        }
        for arch, expected_mtype in host_cpu_archs.items():
            mock_get_arch.return_value = arch
            mtype = libvirt_utils.get_machine_type(image_meta)
            self.assertEqual(expected_mtype, mtype)

    def test_get_machine_type_from_conf(self):
        self.useFixture(nova_fixtures.ConfPatcher(
            group="libvirt", hw_machine_type=['x86_64=q35', 'i686=legacy']))
        self.assertEqual('q35',
                         libvirt_utils.get_default_machine_type('x86_64'))

    def test_get_machine_type_no_conf_or_fallback(self):
        self.assertIsNone(libvirt_utils.get_default_machine_type('sparc'))

    def test_get_machine_type_missing_conf_and_fallback(self):
        self.useFixture(nova_fixtures.ConfPatcher(
            group="libvirt", hw_machine_type=['x86_64=q35', 'i686=legacy']))
        self.assertIsNone(libvirt_utils.get_default_machine_type('sparc'))

    def test_get_machine_type_survives_invalid_conf(self):
        self.useFixture(nova_fixtures.ConfPatcher(
            group="libvirt", hw_machine_type=['x86_64=q35', 'foo']))
        self.assertEqual('q35',
                         libvirt_utils.get_default_machine_type('x86_64'))

    def test_get_machine_type_from_image(self):
        image_meta = objects.ImageMeta.from_dict({
            "disk_format": "raw", "properties": {"hw_machine_type": "q35"}
        })
        os_mach_type = libvirt_utils.get_machine_type(image_meta)
        self.assertEqual('q35', os_mach_type)

    def test_make_reverse_cpu_traits_mapping(self):
        for k in libvirt_utils.make_reverse_cpu_traits_mapping():
            self.assertIsInstance(k, str)

    def test_get_flags_by_flavor_specs(self):
        flavor = objects.Flavor(
            id=1, flavorid='fakeid-1', name='fake1.small', memory_mb=128,
            vcpus=1, root_gb=1, ephemeral_gb=0, swap=0, rxtx_factor=0,
            deleted=False, extra_specs={
                'trait:%s' % os_traits.HW_CPU_X86_3DNOW: 'required',
                'trait:%s' % os_traits.HW_CPU_X86_SSE2: 'required',
                'trait:%s' % os_traits.HW_CPU_HYPERTHREADING: 'required',
                'trait:%s' % os_traits.HW_CPU_X86_INTEL_VMX: 'required',
                'trait:%s' % os_traits.HW_CPU_X86_VMX: 'required',
                'trait:%s' % os_traits.HW_CPU_X86_SVM: 'required',
                'trait:%s' % os_traits.HW_CPU_X86_AMD_SVM: 'required',
            })
        traits = libvirt_utils.get_flags_by_flavor_specs(flavor)
        # we shouldn't see the hyperthreading trait since that's a valid trait
        # but not a CPU flag
        self.assertEqual(set(['3dnow', 'sse2', 'vmx', 'svm']), traits)

    @mock.patch('nova.virt.libvirt.utils.copy_image')
    @mock.patch('nova.privsep.path.chown')
    @mock.patch('nova.privsep.path.move_tree')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('os.path.exists', return_value=True)
    def test_save_migrate_vtpm(
        self, mock_exists, mock_ensure, mock_move, mock_chown, mock_copy,
    ):
        def _on_execute():
            pass

        def _on_completion():
            pass

        libvirt_utils.save_and_migrate_vtpm_dir(
            uuids.instance, 'base_resize', 'base', 'host', _on_execute,
            _on_completion,
        )

        vtpm_dir = f'/var/lib/libvirt/swtpm/{uuids.instance}'
        swtpm_dir = 'base_resize/swtpm'
        mock_exists.assert_called_once_with(vtpm_dir)
        mock_ensure.assert_called_once_with(swtpm_dir)
        mock_move.assert_called_once_with(vtpm_dir, swtpm_dir)
        mock_chown.assert_called_once_with(
            swtpm_dir, os.geteuid(), os.getegid(), recursive=True,
        )
        mock_copy.assert_called_once_with(
            swtpm_dir, 'base', host='host', on_completion=_on_completion,
            on_execute=_on_execute,
        )

    @mock.patch('nova.privsep.path.move_tree')
    @mock.patch('nova.privsep.path.chown')
    @mock.patch('nova.virt.libvirt.utils.copy_image')
    @mock.patch('os.path.exists', return_value=False)
    def test_save_migrate_vtpm_not_enabled(
        self, mock_exists, mock_copy_image, mock_chown, mock_move,
    ):
        def _dummy():
            pass

        libvirt_utils.save_and_migrate_vtpm_dir(
            uuids.instance, 'base_resize', 'base', 'host', _dummy, _dummy,
        )

        mock_exists.assert_called_once_with(
            f'/var/lib/libvirt/swtpm/{uuids.instance}')
        mock_copy_image.assert_not_called()
        mock_chown.assert_not_called()
        mock_move.assert_not_called()

    @mock.patch('grp.getgrnam')
    @mock.patch('pwd.getpwnam')
    @mock.patch('nova.privsep.path.chmod')
    @mock.patch('nova.privsep.path.makedirs')
    @mock.patch('nova.privsep.path.move_tree')
    @mock.patch('nova.privsep.path.chown')
    @mock.patch('os.path.exists')
    @mock.patch('os.path.isdir')
    def _test_restore_vtpm(
        self, exists, mock_isdir, mock_exists, mock_chown, mock_move,
        mock_makedirs, mock_chmod, mock_getpwnam, mock_getgrnam,
    ):
        mock_exists.return_value = exists
        mock_isdir.return_value = True
        mock_getpwnam.return_value = pwd.struct_passwd(
            ('swtpm', '*', 1234, 1234, None, '/home/test', '/bin/bash'))
        mock_getgrnam.return_value = grp.struct_group(('swtpm', '*', 4321, []))

        libvirt_utils.restore_vtpm_dir('dummy')

        if not exists:
            mock_makedirs.assert_called_once_with(libvirt_utils.VTPM_DIR)
            mock_chmod.assert_called_once_with(libvirt_utils.VTPM_DIR, 0o711)

        mock_getpwnam.assert_called_once_with(CONF.libvirt.swtpm_user)
        mock_getgrnam.assert_called_once_with(CONF.libvirt.swtpm_group)
        mock_chown.assert_called_with('dummy', 1234, 4321, recursive=True)
        mock_move.assert_called_with('dummy', libvirt_utils.VTPM_DIR)

    def test_restore_vtpm(self):
        self._test_restore_vtpm(True)

    def test_restore_vtpm_not_exist(self):
        self._test_restore_vtpm(False)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('os.path.isdir', return_value=False)
    def test_restore_vtpm_notdir(self, mock_isdir, mock_exists):
        self.assertRaises(exception.Invalid,
                          libvirt_utils.restore_vtpm_dir, 'dummy')

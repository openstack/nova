# Copyright 2012 OpenStack Foundation
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

import tempfile

import fixtures
import mock
from oslo_concurrency import processutils

from nova import test
from nova import utils
from nova.virt.disk import api
from nova.virt.disk.mount import api as mount
from nova.virt.image import model as imgmodel


class FakeMount(object):
    device = None

    @staticmethod
    def instance_for_format(image, mountdir, partition):
        return FakeMount()

    def get_dev(self):
        pass

    def unget_dev(self):
        pass


class APITestCase(test.NoDBTestCase):
    def test_can_resize_need_fs_type_specified(self):
        # NOTE(mikal): Bug 1094373 saw a regression where we failed to
        # treat a failure to mount as a failure to be able to resize the
        # filesystem
        def _fake_get_disk_size(path):
            return 10
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.api.get_disk_size', _fake_get_disk_size))

        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        def fake_returns_true(*args, **kwargs):
            return True

        def fake_returns_nothing(*args, **kwargs):
            return ''
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.get_dev',
                fake_returns_true))
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.map_dev',
                fake_returns_true))
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.vfs.localfs.VFSLocalFS.get_image_fs',
                fake_returns_nothing))

        # Force the use of localfs, which is what was used during the failure
        # reported in the bug
        def fake_import_fails(*args, **kwargs):
            raise Exception('Failed')
        self.useFixture(fixtures.MonkeyPatch(
                'oslo_utils.import_module',
                fake_import_fails))

        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        image = imgmodel.LocalFileImage(imgfile.name, imgmodel.FORMAT_QCOW2)
        self.assertFalse(api.is_image_extendable(image))

    def test_is_image_extendable_raw(self):
        imgfile = tempfile.NamedTemporaryFile()

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('e2label', imgfile)
        self.mox.ReplayAll()

        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_RAW)
        self.addCleanup(imgfile.close)
        self.assertTrue(api.is_image_extendable(image))

    def test_resize2fs_success(self):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('e2fsck',
                      '-fp',
                      imgfile,
                      check_exit_code=[0, 1, 2],
                      run_as_root=False)
        utils.execute('resize2fs',
                      imgfile,
                      check_exit_code=False,
                      run_as_root=False)

        self.mox.ReplayAll()
        api.resize2fs(imgfile)

    def test_resize2fs_e2fsck_fails(self):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('e2fsck',
                      '-fp',
                      imgfile,
                      check_exit_code=[0, 1, 2],
                      run_as_root=False).AndRaise(
                          processutils.ProcessExecutionError("fs error"))
        self.mox.ReplayAll()
        api.resize2fs(imgfile)

    def test_extend_qcow_success(self):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10
        device = "/dev/sdh"
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_QCOW2)

        self.flags(resize_fs_using_block_device=True)
        mounter = FakeMount.instance_for_format(
            image, None, None)
        mounter.device = device

        self.mox.StubOutWithMock(api, 'can_resize_image')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(api, 'is_image_extendable')
        self.mox.StubOutWithMock(mounter, 'get_dev')
        self.mox.StubOutWithMock(mounter, 'unget_dev')
        self.mox.StubOutWithMock(api, 'resize2fs')
        self.mox.StubOutWithMock(mount.Mount, 'instance_for_format',
                                 use_mock_anything=True)

        api.can_resize_image(imgfile, imgsize).AndReturn(True)
        utils.execute('qemu-img', 'resize', imgfile, imgsize)
        api.is_image_extendable(image).AndReturn(True)
        mount.Mount.instance_for_format(image, None, None).AndReturn(mounter)
        mounter.get_dev().AndReturn(True)
        api.resize2fs(mounter.device, run_as_root=True, check_exit_code=[0])
        mounter.unget_dev()

        self.mox.ReplayAll()
        api.extend(image, imgsize)

    @mock.patch.object(api, 'can_resize_image', return_value=True)
    @mock.patch.object(api, 'is_image_extendable')
    @mock.patch.object(utils, 'execute')
    def test_extend_qcow_no_resize(self, mock_execute, mock_extendable,
                                   mock_can_resize_image):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_QCOW2)

        self.flags(resize_fs_using_block_device=False)

        api.extend(image, imgsize)

        mock_can_resize_image.assert_called_once_with(imgfile, imgsize)
        mock_execute.assert_called_once_with('qemu-img', 'resize', imgfile,
                                             imgsize)
        self.assertFalse(mock_extendable.called)

    def test_extend_raw_success(self):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_RAW)

        self.mox.StubOutWithMock(api, 'can_resize_image')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(api, 'resize2fs')

        api.can_resize_image(imgfile, imgsize).AndReturn(True)
        utils.execute('qemu-img', 'resize', imgfile, imgsize)
        utils.execute('e2label', image.path)
        api.resize2fs(imgfile, run_as_root=False, check_exit_code=[0])

        self.mox.ReplayAll()
        api.extend(image, imgsize)

    HASH_VFAT = utils.get_hash_str(api.FS_FORMAT_VFAT)[:7]
    HASH_EXT4 = utils.get_hash_str(api.FS_FORMAT_EXT4)[:7]
    HASH_NTFS = utils.get_hash_str(api.FS_FORMAT_NTFS)[:7]

    def test_get_file_extension_for_os_type(self):
        self.assertEqual(self.HASH_VFAT,
                         api.get_file_extension_for_os_type(None, None))
        self.assertEqual(self.HASH_EXT4,
                         api.get_file_extension_for_os_type('linux', None))
        self.assertEqual(self.HASH_NTFS,
                         api.get_file_extension_for_os_type(
                             'windows', None))

    def test_get_file_extension_for_os_type_with_overrides(self):
        with mock.patch('nova.virt.disk.api._DEFAULT_MKFS_COMMAND',
                        'custom mkfs command'):
            self.assertEqual("a74d253",
                             api.get_file_extension_for_os_type(
                                 'linux', None))
            self.assertEqual("a74d253",
                             api.get_file_extension_for_os_type(
                                 'windows', None))
            self.assertEqual("a74d253",
                             api.get_file_extension_for_os_type('osx', None))

        with mock.patch.dict(api._MKFS_COMMAND,
                             {'osx': 'custom mkfs command'}, clear=True):
            self.assertEqual(self.HASH_VFAT,
                             api.get_file_extension_for_os_type(None, None))
            self.assertEqual(self.HASH_EXT4,
                             api.get_file_extension_for_os_type('linux', None))
            self.assertEqual(self.HASH_NTFS,
                             api.get_file_extension_for_os_type(
                                 'windows', None))
            self.assertEqual("a74d253",
                             api.get_file_extension_for_os_type(
                                 'osx', None))

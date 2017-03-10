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

import mock
from oslo_concurrency import processutils
from oslo_utils import units

from nova import test
from nova import utils
from nova.virt.disk import api
from nova.virt.disk.mount import api as mount
from nova.virt.disk.vfs import localfs
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
    @mock.patch.object(localfs.VFSLocalFS, 'get_image_fs', autospec=True,
                       return_value='')
    def test_can_resize_need_fs_type_specified(self, mock_image_fs):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        image = imgmodel.LocalFileImage(imgfile.name, imgmodel.FORMAT_QCOW2)
        self.assertFalse(api.is_image_extendable(image))
        self.assertTrue(mock_image_fs.called)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_is_image_extendable_raw(self, mock_exec):
        imgfile = tempfile.NamedTemporaryFile()
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_RAW)
        self.addCleanup(imgfile.close)
        self.assertTrue(api.is_image_extendable(image))
        mock_exec.assert_called_once_with('e2label', imgfile)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_resize2fs_success(self, mock_exec):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)

        api.resize2fs(imgfile)

        mock_exec.assert_has_calls(
            [mock.call('e2fsck',
                       '-fp',
                       imgfile,
                       check_exit_code=[0, 1, 2],
                       run_as_root=False),
             mock.call('resize2fs',
                       imgfile,
                       check_exit_code=False,
                       run_as_root=False)])

    @mock.patch.object(utils, 'execute', autospec=True,
                       side_effect=processutils.ProcessExecutionError(
                           "fs error"))
    def test_resize2fs_e2fsck_fails(self, mock_exec):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        api.resize2fs(imgfile)

        mock_exec.assert_called_once_with('e2fsck',
                                          '-fp',
                                          imgfile,
                                          check_exit_code=[0, 1, 2],
                                          run_as_root=False)

    @mock.patch.object(api, 'can_resize_image', autospec=True,
                       return_value=True)
    @mock.patch.object(api, 'is_image_extendable', autospec=True,
                       return_value=True)
    @mock.patch.object(api, 'resize2fs', autospec=True)
    @mock.patch.object(mount.Mount, 'instance_for_format')
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_extend_qcow_success(self, mock_exec, mock_inst, mock_resize,
                                 mock_extendable, mock_can_resize):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10
        device = "/dev/sdh"
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_QCOW2)

        self.flags(resize_fs_using_block_device=True)
        mounter = FakeMount.instance_for_format(
            image, None, None)
        mounter.device = device
        mock_inst.return_value = mounter

        with test.nested(
            mock.patch.object(mounter, 'get_dev', autospec=True,
                              return_value=True),
            mock.patch.object(mounter, 'unget_dev', autospec=True),
        ) as (mock_get_dev, mock_unget_dev):

            api.extend(image, imgsize)

            mock_can_resize.assert_called_once_with(imgfile, imgsize)
            mock_exec.assert_called_once_with('qemu-img', 'resize',
                                              imgfile, imgsize)
            mock_extendable.assert_called_once_with(image)
            mock_inst.assert_called_once_with(image, None, None)
            mock_resize.assert_called_once_with(mounter.device,
                                                run_as_root=True,
                                                check_exit_code=[0])

            mock_get_dev.assert_called_once_with()
            mock_unget_dev.assert_called_once_with()

    @mock.patch.object(api, 'can_resize_image', autospec=True,
                       return_value=True)
    @mock.patch.object(api, 'is_image_extendable', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
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

    @mock.patch.object(api, 'can_resize_image', autospec=True,
                       return_value=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_extend_ploop(self, mock_execute, mock_can_resize_image):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10 * units.Gi
        imgsize_mb = str(imgsize // units.Mi) + 'M'
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_PLOOP)

        api.extend(image, imgsize)
        mock_can_resize_image.assert_called_once_with(image.path,
                                                      imgsize)
        mock_execute.assert_called_once_with('prl_disk_tool', 'resize',
                                             '--size', imgsize_mb,
                                             '--resize_partition',
                                             '--hdd', imgfile,
                                             run_as_root=True)

    @mock.patch.object(api, 'can_resize_image', autospec=True,
                       return_value=True)
    @mock.patch.object(api, 'resize2fs', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_extend_raw_success(self, mock_exec, mock_resize,
                                mock_can_resize):
        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        imgsize = 10
        image = imgmodel.LocalFileImage(imgfile, imgmodel.FORMAT_RAW)

        api.extend(image, imgsize)

        mock_exec.assert_has_calls(
            [mock.call('qemu-img', 'resize', imgfile, imgsize),
             mock.call('e2label', image.path)])
        mock_resize.assert_called_once_with(imgfile, run_as_root=False,
                                            check_exit_code=[0])
        mock_can_resize.assert_called_once_with(imgfile, imgsize)

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

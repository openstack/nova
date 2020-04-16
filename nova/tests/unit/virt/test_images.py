#    Copyright 2013 IBM Corp.
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
from oslo_concurrency import processutils
import six

from nova.compute import utils as compute_utils
from nova import exception
from nova import test
from nova.virt import images


class QemuTestCase(test.NoDBTestCase):
    def test_qemu_info_with_bad_path(self):
        self.assertRaises(exception.DiskNotFound,
                          images.qemu_img_info,
                          '/path/that/does/not/exist')

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch.object(os.path, 'exists', return_value=True)
    def test_qemu_info_with_errors(self, path_exists, mock_exec):
        err = processutils.ProcessExecutionError(
            exit_code=1, stderr='No such file or directory')
        mock_exec.side_effect = err
        self.assertRaises(exception.DiskNotFound,
                          images.qemu_img_info,
                          '/fake/path')

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch('nova.privsep.qemu.unprivileged_qemu_img_info',
                return_value={})
    def test_qemu_info_with_no_errors(self, path_exists,
                                      utils_execute):
        image_info = images.qemu_img_info('/fake/path')
        self.assertTrue(image_info)

    @mock.patch('nova.privsep.qemu.unprivileged_qemu_img_info',
                return_value={})
    def test_qemu_info_with_rbd_path(self, utils_execute):
        # Assert that the use of a RBD URI as the path doesn't raise
        # exception.DiskNotFound
        image_info = images.qemu_img_info('rbd:volume/pool')
        self.assertTrue(image_info)

    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    @mock.patch.object(processutils, 'execute',
                       side_effect=processutils.ProcessExecutionError)
    def test_convert_image_with_errors(self, mocked_execute, mock_direct_io,
                                       mock_disk_op_sema):
        self.assertRaises(exception.ImageUnacceptable,
                          images.convert_image,
                          '/path/that/does/not/exist',
                          '/other/path/that/does/not/exist',
                          'qcow2',
                          'raw')
        mock_disk_op_sema.__enter__.assert_called_once()

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch.object(os.path, 'exists', return_value=True)
    def test_convert_image_with_prlimit_fail(self, path, mocked_execute):
        mocked_execute.side_effect = \
            processutils.ProcessExecutionError(exit_code=-9)
        exc = self.assertRaises(exception.InvalidDiskInfo,
                                images.qemu_img_info,
                                '/fake/path')
        self.assertIn('qemu-img aborted by prlimits', six.text_type(exc))

    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch.object(os.path, 'exists', return_value=True)
    def test_qemu_img_info_with_disk_not_found(self, exists, mocked_execute):
        """Tests that the initial os.path.exists check passes but the qemu-img
        command fails because the path is gone by the time the command runs.
        """
        path = '/opt/stack/data/nova/instances/some-uuid/disk'
        stderr = (u"qemu-img: Could not open "
                  "'/opt/stack/data/nova/instances/some-uuid/disk': "
                  "Could not open '/opt/stack/data/nova/instances/some-uuid/"
                  "disk': No such file or directory\n")
        mocked_execute.side_effect = (
            processutils.ProcessExecutionError(
                exit_code=1, stderr=stderr))
        self.assertRaises(exception.DiskNotFound, images.qemu_img_info, path)
        exists.assert_called_once_with(path)
        mocked_execute.assert_called_once()

    @mock.patch.object(images, 'convert_image',
                       side_effect=exception.ImageUnacceptable)
    @mock.patch.object(images, 'qemu_img_info')
    @mock.patch.object(images, 'fetch')
    def test_fetch_to_raw_errors(self, convert_image, qemu_img_info, fetch):
        qemu_img_info.backing_file = None
        qemu_img_info.file_format = 'qcow2'
        qemu_img_info.virtual_size = 20
        self.assertRaisesRegex(exception.ImageUnacceptable,
                               'Image href123 is unacceptable.*',
                               images.fetch_to_raw,
                               None, 'href123', '/no/path')

    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=True)
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_convert_image_with_direct_io_support(self, mock_execute,
                                                  mock_direct_io,
                                                  mock_disk_op_sema):
        images._convert_image('source', 'dest', 'in_format', 'out_format',
                              run_as_root=False)
        expected = ('qemu-img', 'convert', '-t', 'none', '-O', 'out_format',
                    '-f', 'in_format', 'source', 'dest')
        mock_disk_op_sema.__enter__.assert_called_once()
        self.assertTupleEqual(expected, mock_execute.call_args[0])

    @mock.patch.object(compute_utils, 'disk_ops_semaphore')
    @mock.patch('nova.privsep.utils.supports_direct_io', return_value=False)
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_convert_image_without_direct_io_support(self, mock_execute,
                                                     mock_direct_io,
                                                     mock_disk_op_sema):
        images._convert_image('source', 'dest', 'in_format', 'out_format',
                              run_as_root=False)
        expected = ('qemu-img', 'convert', '-t', 'writeback',
                    '-O', 'out_format', '-f', 'in_format', 'source', 'dest')
        mock_disk_op_sema.__enter__.assert_called_once()
        self.assertTupleEqual(expected, mock_execute.call_args[0])

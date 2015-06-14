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

from nova import exception
from nova import test
from nova import utils
from nova.virt import images


class QemuTestCase(test.NoDBTestCase):
    def test_qemu_info_with_bad_path(self):
        self.assertRaises(exception.InvalidDiskInfo,
                          images.qemu_img_info,
                          '/path/that/does/not/exist')

    @mock.patch.object(os.path, 'exists', return_value=True)
    def test_qemu_info_with_errors(self, path_exists):
        self.assertRaises(processutils.ProcessExecutionError,
                          images.qemu_img_info,
                          '/fake/path')

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(utils, 'execute',
                       return_value=('stdout', None))
    def test_qemu_info_with_no_errors(self, path_exists,
                                      utils_execute):
        image_info = images.qemu_img_info('/fake/path')
        self.assertTrue(image_info)
        self.assertTrue(str(image_info))

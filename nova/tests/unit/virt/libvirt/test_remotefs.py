# Copyright 2014 Cloudbase Solutions Srl
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
from oslo_concurrency import processutils

from nova import test
from nova import utils
from nova.virt.libvirt import remotefs


class RemoteFSTestCase(test.NoDBTestCase):
    """Remote filesystem operations test case."""

    @mock.patch.object(utils, 'execute')
    def _test_mount_share(self, mock_execute, already_mounted=False):
        if already_mounted:
            err_msg = 'Device or resource busy'
            mock_execute.side_effect = [
                None, processutils.ProcessExecutionError(err_msg)]

        remotefs.mount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path,
            mock.sentinel.export_type,
            options=[mock.sentinel.mount_options])

        mock_execute.assert_any_call('mkdir', '-p',
                                     mock.sentinel.mount_path)
        mock_execute.assert_any_call('mount', '-t', mock.sentinel.export_type,
                                     mock.sentinel.mount_options,
                                     mock.sentinel.export_path,
                                     mock.sentinel.mount_path,
                                     run_as_root=True)

    def test_mount_new_share(self):
        self._test_mount_share()

    def test_mount_already_mounted_share(self):
        self._test_mount_share(already_mounted=True)

    @mock.patch.object(utils, 'execute')
    def test_unmount_share(self, mock_execute):
        remotefs.unmount_share(
            mock.sentinel.mount_path, mock.sentinel.export_path)

        mock_execute.assert_any_call('umount', mock.sentinel.mount_path,
                                     run_as_root=True, attempts=3,
                                     delay_on_retry=True)

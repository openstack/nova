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

from nova import test
from nova.virt.hyperv import livemigrationutils


class LiveMigrationUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V LiveMigrationUtils class."""

    def setUp(self):
        self.liveutils = livemigrationutils.LiveMigrationUtils()
        self.liveutils._vmutils = mock.MagicMock()
        self.liveutils._volutils = mock.MagicMock()

        super(LiveMigrationUtilsTestCase, self).setUp()

    def test_get_physical_disk_paths(self):
        ide_path = {mock.sentinel.IDE_PATH: mock.sentinel.IDE_HOST_RESOURCE}
        scsi_path = {mock.sentinel.SCSI_PATH: mock.sentinel.SCSI_HOST_RESOURCE}
        ide_ctrl = self.liveutils._vmutils.get_vm_ide_controller.return_value
        scsi_ctrl = self.liveutils._vmutils.get_vm_scsi_controller.return_value
        mock_get_controller_paths = (
            self.liveutils._vmutils.get_controller_volume_paths)

        mock_get_controller_paths.side_effect = [ide_path, scsi_path]

        result = self.liveutils._get_physical_disk_paths(mock.sentinel.VM_NAME)

        expected = dict(ide_path)
        expected.update(scsi_path)
        self.assertDictContainsSubset(expected, result)
        calls = [mock.call(ide_ctrl), mock.call(scsi_ctrl)]
        mock_get_controller_paths.assert_has_calls(calls)

    def test_get_physical_disk_paths_no_ide(self):
        scsi_path = {mock.sentinel.SCSI_PATH: mock.sentinel.SCSI_HOST_RESOURCE}
        scsi_ctrl = self.liveutils._vmutils.get_vm_scsi_controller.return_value
        mock_get_controller_paths = (
            self.liveutils._vmutils.get_controller_volume_paths)

        self.liveutils._vmutils.get_vm_ide_controller.return_value = None
        mock_get_controller_paths.return_value = scsi_path

        result = self.liveutils._get_physical_disk_paths(mock.sentinel.VM_NAME)

        self.assertEqual(scsi_path, result)
        mock_get_controller_paths.assert_called_once_with(scsi_ctrl)

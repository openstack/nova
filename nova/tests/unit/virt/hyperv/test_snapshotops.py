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

import os

import mock
from os_win import exceptions as os_win_exc

from nova.compute import task_states
from nova import exception
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import snapshotops


class SnapshotOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V SnapshotOps class."""

    def setUp(self):
        super(SnapshotOpsTestCase, self).setUp()

        self.context = 'fake_context'
        self._snapshotops = snapshotops.SnapshotOps()
        self._snapshotops._pathutils = mock.MagicMock()
        self._snapshotops._vmutils = mock.MagicMock()
        self._snapshotops._vhdutils = mock.MagicMock()

    @mock.patch('nova.image.glance.get_remote_image_service')
    def test_save_glance_image(self, mock_get_remote_image_service):
        image_metadata = {"is_public": False,
                          "disk_format": "vhd",
                          "container_format": "bare",
                          "properties": {}}
        glance_image_service = mock.MagicMock()
        mock_get_remote_image_service.return_value = (glance_image_service,
                                                      mock.sentinel.IMAGE_ID)
        self._snapshotops._save_glance_image(context=self.context,
                                             image_id=mock.sentinel.IMAGE_ID,
                                             image_vhd_path=mock.sentinel.PATH)
        mock_get_remote_image_service.assert_called_once_with(
            self.context, mock.sentinel.IMAGE_ID)
        self._snapshotops._pathutils.open.assert_called_with(
            mock.sentinel.PATH, 'rb')
        glance_image_service.update.assert_called_once_with(
            self.context, mock.sentinel.IMAGE_ID, image_metadata,
            self._snapshotops._pathutils.open().__enter__())

    @mock.patch('nova.virt.hyperv.snapshotops.SnapshotOps._save_glance_image')
    def _test_snapshot(self, mock_save_glance_image, base_disk_path):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_update = mock.MagicMock()
        fake_src_path = os.path.join('fake', 'path')
        self._snapshotops._pathutils.lookup_root_vhd_path.return_value = (
            fake_src_path)
        fake_exp_dir = os.path.join(os.path.join('fake', 'exp'), 'dir')
        self._snapshotops._pathutils.get_export_dir.return_value = fake_exp_dir
        self._snapshotops._vhdutils.get_vhd_parent_path.return_value = (
            base_disk_path)
        fake_snapshot_path = (
            self._snapshotops._vmutils.take_vm_snapshot.return_value)

        self._snapshotops.snapshot(context=self.context,
                                   instance=mock_instance,
                                   image_id=mock.sentinel.IMAGE_ID,
                                   update_task_state=mock_update)

        self._snapshotops._vmutils.take_vm_snapshot.assert_called_once_with(
            mock_instance.name)
        mock_lookup_path = self._snapshotops._pathutils.lookup_root_vhd_path
        mock_lookup_path.assert_called_once_with(mock_instance.name)
        mock_get_vhd_path = self._snapshotops._vhdutils.get_vhd_parent_path
        mock_get_vhd_path.assert_called_once_with(fake_src_path)
        self._snapshotops._pathutils.get_export_dir.assert_called_once_with(
            mock_instance.name)

        expected = [mock.call(fake_src_path,
                              os.path.join(fake_exp_dir,
                                           os.path.basename(fake_src_path)))]
        dest_vhd_path = os.path.join(fake_exp_dir,
                                     os.path.basename(fake_src_path))
        if base_disk_path:
            basename = os.path.basename(base_disk_path)
            base_dest_disk_path = os.path.join(fake_exp_dir, basename)
            expected.append(mock.call(base_disk_path, base_dest_disk_path))
            mock_reconnect = self._snapshotops._vhdutils.reconnect_parent_vhd
            mock_reconnect.assert_called_once_with(dest_vhd_path,
                                                   base_dest_disk_path)
            self._snapshotops._vhdutils.merge_vhd.assert_called_once_with(
                dest_vhd_path)
            mock_save_glance_image.assert_called_once_with(
                self.context, mock.sentinel.IMAGE_ID, base_dest_disk_path)
        else:
            mock_save_glance_image.assert_called_once_with(
                self.context, mock.sentinel.IMAGE_ID, dest_vhd_path)
        self._snapshotops._pathutils.copyfile.has_calls(expected)
        expected_update = [
            mock.call(task_state=task_states.IMAGE_PENDING_UPLOAD),
            mock.call(task_state=task_states.IMAGE_UPLOADING,
                      expected_state=task_states.IMAGE_PENDING_UPLOAD)]
        mock_update.has_calls(expected_update)
        self._snapshotops._vmutils.remove_vm_snapshot.assert_called_once_with(
            fake_snapshot_path)
        self._snapshotops._pathutils.rmtree.assert_called_once_with(
            fake_exp_dir)

    def test_snapshot(self):
        base_disk_path = os.path.join('fake', 'disk')
        self._test_snapshot(base_disk_path=base_disk_path)

    def test_snapshot_no_base_disk(self):
        self._test_snapshot(base_disk_path=None)

    @mock.patch.object(snapshotops.SnapshotOps, '_snapshot')
    def test_snapshot_instance_not_found(self, mock_snapshot):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        mock_snapshot.side_effect = os_win_exc.HyperVVMNotFoundException(
            vm_name=mock_instance.name)

        self.assertRaises(exception.InstanceNotFound,
                          self._snapshotops.snapshot,
                          self.context, mock_instance, mock.sentinel.image_id,
                          mock.sentinel.update_task_state)

        mock_snapshot.assert_called_once_with(self.context, mock_instance,
                                              mock.sentinel.image_id,
                                              mock.sentinel.update_task_state)

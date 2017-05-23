# Copyright 2012 Cloudbase Solutions Srl
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

"""
Management class for VM snapshot operations.
"""
import os

from os_win import utilsfactory
from oslo_log import log as logging

from nova.compute import task_states
from nova.i18n import _
from nova.image import glance
from nova.virt.hyperv import pathutils

LOG = logging.getLogger(__name__)


class SnapshotOps(object):
    def __init__(self):
        self._pathutils = pathutils.PathUtils()
        self._vmutils = utilsfactory.get_vmutils()
        self._vhdutils = utilsfactory.get_vhdutils()

    def _save_glance_image(self, context, image_id, image_vhd_path):
        (glance_image_service,
         image_id) = glance.get_remote_image_service(context, image_id)
        image_metadata = {"is_public": False,
                          "disk_format": "vhd",
                          "container_format": "bare"}
        with self._pathutils.open(image_vhd_path, 'rb') as f:
            glance_image_service.update(context, image_id, image_metadata, f,
                                        purge_props=False)

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance."""
        instance_name = instance.name

        LOG.debug("Creating snapshot for instance %s", instance_name)
        snapshot_path = self._vmutils.take_vm_snapshot(instance_name)
        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        export_dir = None

        try:
            src_vhd_path = self._pathutils.lookup_root_vhd_path(instance_name)

            LOG.debug("Getting info for VHD %s", src_vhd_path)
            src_base_disk_path = self._vhdutils.get_vhd_parent_path(
                src_vhd_path)

            export_dir = self._pathutils.get_export_dir(instance_name)

            dest_vhd_path = os.path.join(export_dir, os.path.basename(
                src_vhd_path))
            LOG.debug('Copying VHD %(src_vhd_path)s to %(dest_vhd_path)s',
                      {'src_vhd_path': src_vhd_path,
                       'dest_vhd_path': dest_vhd_path})
            self._pathutils.copyfile(src_vhd_path, dest_vhd_path)

            image_vhd_path = None
            if not src_base_disk_path:
                image_vhd_path = dest_vhd_path
            else:
                basename = os.path.basename(src_base_disk_path)
                dest_base_disk_path = os.path.join(export_dir, basename)
                LOG.debug('Copying base disk %(src_vhd_path)s to '
                          '%(dest_base_disk_path)s',
                          {'src_vhd_path': src_vhd_path,
                           'dest_base_disk_path': dest_base_disk_path})
                self._pathutils.copyfile(src_base_disk_path,
                                         dest_base_disk_path)

                LOG.debug("Reconnecting copied base VHD "
                          "%(dest_base_disk_path)s and diff "
                          "VHD %(dest_vhd_path)s",
                          {'dest_base_disk_path': dest_base_disk_path,
                           'dest_vhd_path': dest_vhd_path})
                self._vhdutils.reconnect_parent_vhd(dest_vhd_path,
                                                    dest_base_disk_path)

                LOG.debug("Merging diff disk %s into its parent.",
                          dest_vhd_path)
                self._vhdutils.merge_vhd(dest_vhd_path)
                image_vhd_path = dest_base_disk_path

            LOG.debug("Updating Glance image %(image_id)s with content from "
                      "merged disk %(image_vhd_path)s",
                      {'image_id': image_id, 'image_vhd_path': image_vhd_path})
            update_task_state(task_state=task_states.IMAGE_UPLOADING,
                              expected_state=task_states.IMAGE_PENDING_UPLOAD)
            self._save_glance_image(context, image_id, image_vhd_path)

            LOG.debug("Snapshot image %(image_id)s updated for VM "
                      "%(instance_name)s",
                      {'image_id': image_id, 'instance_name': instance_name})
        finally:
            try:
                LOG.debug("Removing snapshot %s", image_id)
                self._vmutils.remove_vm_snapshot(snapshot_path)
            except Exception:
                LOG.exception(_('Failed to remove snapshot for VM %s'),
                              instance_name, instance=instance)
            if export_dir:
                LOG.debug('Removing directory: %s', export_dir)
                self._pathutils.rmtree(export_dir)

# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import shutil
import sys

from nova import exception
from nova import flags
from nova.image import glance
from nova.openstack.common import log as logging
from nova.virt.hyperv import baseops
from nova.virt.hyperv import constants
from nova.virt.hyperv import ioutils
from nova.virt.hyperv import vmutils
from xml.etree import ElementTree

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import wmi

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class SnapshotOps(baseops.BaseOps):
    def __init__(self):
        super(SnapshotOps, self).__init__()
        self._vmutils = vmutils.VMUtils()

    def snapshot(self, context, instance, name):
        """Create snapshot from a running VM instance."""
        instance_name = instance["name"]
        vm = self._vmutils.lookup(self._conn, instance_name)
        if vm is None:
            raise exception.InstanceNotFound(instance=instance_name)
        vm = self._conn.Msvm_ComputerSystem(ElementName=instance_name)[0]
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        LOG.debug(_("Creating snapshot for instance %s"), instance_name)
        (job_path, ret_val, snap_setting_data) = \
            vs_man_svc.CreateVirtualSystemSnapshot(vm.path_())
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self._vmutils.check_job_status(job_path)
            if success:
                job_wmi_path = job_path.replace('\\', '/')
                job = wmi.WMI(moniker=job_wmi_path)
                snap_setting_data = job.associators(
                    wmi_result_class='Msvm_VirtualSystemSettingData')[0]
        else:
            success = (ret_val == 0)
        if not success:
            raise vmutils.HyperVException(
                _('Failed to create snapshot for VM %s') %
                    instance_name)

        export_folder = None
        f = None

        try:
            src_vhd_path = os.path.join(FLAGS.instances_path, instance_name,
                instance_name + ".vhd")

            image_man_svc = self._conn.Msvm_ImageManagementService()[0]

            LOG.debug(_("Getting info for VHD %s"), src_vhd_path)
            (src_vhd_info, job_path, ret_val) = \
                image_man_svc.GetVirtualHardDiskInfo(src_vhd_path)
            if ret_val == constants.WMI_JOB_STATUS_STARTED:
                success = self._vmutils.check_job_status(job_path)
            else:
                success = (ret_val == 0)
            if not success:
                raise vmutils.HyperVException(
                    _("Failed to get info for disk %s") %
                        (src_vhd_path))

            src_base_disk_path = None
            et = ElementTree.fromstring(src_vhd_info)
            for item in et.findall("PROPERTY"):
                if item.attrib["NAME"] == "ParentPath":
                    src_base_disk_path = item.find("VALUE").text
                    break

            export_folder = self._vmutils.make_export_path(instance_name)

            dest_vhd_path = os.path.join(export_folder, os.path.basename(
                src_vhd_path))
            LOG.debug(_('Copying VHD %(src_vhd_path)s to %(dest_vhd_path)s'),
                locals())
            shutil.copyfile(src_vhd_path, dest_vhd_path)

            image_vhd_path = None
            if not src_base_disk_path:
                image_vhd_path = dest_vhd_path
            else:
                dest_base_disk_path = os.path.join(export_folder,
                    os.path.basename(src_base_disk_path))
                LOG.debug(_('Copying base disk %(src_vhd_path)s to '
                    '%(dest_base_disk_path)s'), locals())
                shutil.copyfile(src_base_disk_path, dest_base_disk_path)

                LOG.debug(_("Reconnecting copied base VHD "
                    "%(dest_base_disk_path)s and diff VHD %(dest_vhd_path)s"),
                    locals())
                (job_path, ret_val) = \
                    image_man_svc.ReconnectParentVirtualHardDisk(
                        ChildPath=dest_vhd_path,
                        ParentPath=dest_base_disk_path,
                        Force=True)
                if ret_val == constants.WMI_JOB_STATUS_STARTED:
                    success = self._vmutils.check_job_status(job_path)
                else:
                    success = (ret_val == 0)
                if not success:
                    raise vmutils.HyperVException(
                        _("Failed to reconnect base disk "
                            "%(dest_base_disk_path)s and diff disk "
                            "%(dest_vhd_path)s") %
                            locals())

                LOG.debug(_("Merging base disk %(dest_base_disk_path)s and "
                    "diff disk %(dest_vhd_path)s"),
                    locals())
                (job_path, ret_val) = image_man_svc.MergeVirtualHardDisk(
                    SourcePath=dest_vhd_path,
                    DestinationPath=dest_base_disk_path)
                if ret_val == constants.WMI_JOB_STATUS_STARTED:
                    success = self._vmutils.check_job_status(job_path)
                else:
                    success = (ret_val == 0)
                if not success:
                    raise vmutils.HyperVException(
                        _("Failed to merge base disk %(dest_base_disk_path)s "
                            "and diff disk %(dest_vhd_path)s") %
                            locals())
                image_vhd_path = dest_base_disk_path

            (glance_image_service, image_id) = \
                glance.get_remote_image_service(context, name)
            image_metadata = {"is_public": False,
                      "disk_format": "vhd",
                      "container_format": "bare",
                      "properties": {}}
            f = ioutils.open(image_vhd_path, 'rb')
            LOG.debug(
                _("Updating Glance image %(image_id)s with content from "
                    "merged disk %(image_vhd_path)s"),
                    locals())
            glance_image_service.update(context, image_id, image_metadata, f)

            LOG.debug(_("Snapshot image %(image_id)s updated for VM "
                "%(instance_name)s"), locals())
        finally:
            LOG.debug(_("Removing snapshot %s"), name)
            (job_path, ret_val) = vs_man_svc.RemoveVirtualSystemSnapshot(
                snap_setting_data.path_())
            if ret_val == constants.WMI_JOB_STATUS_STARTED:
                success = self._vmutils.check_job_status(job_path)
            else:
                success = (ret_val == 0)
            if not success:
                raise vmutils.HyperVException(
                    _('Failed to remove snapshot for VM %s') %
                        instance_name)
            if f:
                f.close()
            if export_folder:
                LOG.debug(_('Removing folder %s '), export_folder)
                shutil.rmtree(export_folder)

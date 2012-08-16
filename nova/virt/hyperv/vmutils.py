# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Cloudbase Solutions Srl / Pedro Navarro Perez
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
Utility class for VM related operations.
"""

import os
import shutil
import sys
import time
import uuid

from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.virt.hyperv import constants
from nova.virt import images

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import wmi

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class HyperVException(exception.NovaException):
    def __init__(self, message=None):
        super(HyperVException, self).__init__(message)


class VMUtils(object):
    def lookup(self, conn, i):
        vms = conn.Msvm_ComputerSystem(ElementName=i)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise HyperVException(_('duplicate name found: %s') % i)
        else:
            return vms[0].ElementName

    #TODO(alexpilotti): use the reactor to poll instead of sleep
    def check_job_status(self, jobpath):
        """Poll WMI job state for completion"""
        job_wmi_path = jobpath.replace('\\', '/')
        job = wmi.WMI(moniker=job_wmi_path)

        while job.JobState == constants.WMI_JOB_STATE_RUNNING:
            time.sleep(0.1)
            job = wmi.WMI(moniker=job_wmi_path)
        if job.JobState != constants.WMI_JOB_STATE_COMPLETED:
            LOG.debug(_("WMI job failed: %(ErrorSummaryDescription)s - "
                "%(ErrorDescription)s - %(ErrorCode)s") % job)
            return False
        desc = job.Description
        elap = job.ElapsedTime
        LOG.debug(_("WMI job succeeded: %(desc)s, Elapsed=%(elap)s ")
                % locals())
        return True

    def get_vhd_path(self, instance_name):
        base_vhd_folder = os.path.join(FLAGS.instances_path, instance_name)
        if not os.path.exists(base_vhd_folder):
                LOG.debug(_('Creating folder %s '), base_vhd_folder)
                os.makedirs(base_vhd_folder)
        return os.path.join(base_vhd_folder, instance_name + ".vhd")

    def get_base_vhd_path(self, image_name):
        base_dir = os.path.join(FLAGS.instances_path, '_base')
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        return os.path.join(base_dir, image_name + ".vhd")

    def make_export_path(self, instance_name):
        export_folder = os.path.join(FLAGS.instances_path, "export",
                instance_name)
        if os.path.isdir(export_folder):
            LOG.debug(_('Removing existing folder %s '), export_folder)
            shutil.rmtree(export_folder)
        LOG.debug(_('Creating folder %s '), export_folder)
        os.makedirs(export_folder)
        return export_folder

    def clone_wmi_obj(self, conn, wmi_class, wmi_obj):
        """Clone a WMI object"""
        cl = conn.__getattr__(wmi_class)  # get the class
        newinst = cl.new()
        #Copy the properties from the original.
        for prop in wmi_obj._properties:
            if prop == "VirtualSystemIdentifiers":
                strguid = []
                strguid.append(str(uuid.uuid4()))
                newinst.Properties_.Item(prop).Value = strguid
            else:
                newinst.Properties_.Item(prop).Value = \
                    wmi_obj.Properties_.Item(prop).Value
        return newinst

    def add_virt_resource(self, conn, res_setting_data, target_vm):
        """Add a new resource (disk/nic) to the VM"""
        vs_man_svc = conn.Msvm_VirtualSystemManagementService()[0]
        (job, new_resources, ret_val) = vs_man_svc.\
                    AddVirtualSystemResources([res_setting_data.GetText_(1)],
                                                target_vm.path_())
        success = True
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self.check_job_status(job)
        else:
            success = (ret_val == 0)
        if success:
            return new_resources
        else:
            return None

    def remove_virt_resource(self, conn, res_setting_data, target_vm):
        """Add a new resource (disk/nic) to the VM"""
        vs_man_svc = conn.Msvm_VirtualSystemManagementService()[0]
        (job, ret_val) = vs_man_svc.\
                    RemoveVirtualSystemResources([res_setting_data.path_()],
                                                target_vm.path_())
        success = True
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self.check_job_status(job)
        else:
            success = (ret_val == 0)
        return success

    def fetch_image(self, target, context, image_id, user, project,
        *args, **kwargs):
        images.fetch(context, image_id, target, user, project)

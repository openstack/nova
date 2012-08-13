# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Cloudbase Solutions Srl
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
Hyper-V classes to be used in testing.
"""

import sys
import time

from nova import exception
from nova.virt.hyperv import constants
from nova.virt.hyperv import volumeutils
from xml.etree import ElementTree

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import wmi


class HyperVUtils(object):
    def __init__(self):
        self.__conn = None
        self.__conn_v2 = None
        self.__conn_cimv2 = None
        self.__conn_wmi = None
        self._volumeutils = volumeutils.VolumeUtils()

    @property
    def _conn(self):
        if self.__conn is None:
            self.__conn = wmi.WMI(moniker='//./root/virtualization')
        return self.__conn

    @property
    def _conn_v2(self):
        if self.__conn_v2 is None:
            self.__conn_v2 = wmi.WMI(moniker='//./root/virtualization/v2')
        return self.__conn_v2

    @property
    def _conn_cimv2(self):
        if self.__conn_cimv2 is None:
            self.__conn_cimv2 = wmi.WMI(moniker='//./root/cimv2')
        return self.__conn_cimv2

    @property
    def _conn_wmi(self):
        if self.__conn_wmi is None:
            self.__conn_wmi = wmi.WMI(moniker='//./root/wmi')
        return self.__conn_wmi

    def create_vhd(self, path):
        image_service = self._conn.query(
            "Select * from Msvm_ImageManagementService")[0]
        (job, ret_val) = image_service.CreateDynamicVirtualHardDisk(
                Path=path, MaxInternalSize=3 * 1024 * 1024)

        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        else:
            success = (ret_val == 0)
        if not success:
            raise Exception('Failed to create Dynamic disk %s with error %d'
                    % (path, ret_val))

    def _check_job_status(self, jobpath):
        """Poll WMI job state for completion"""
        job_wmi_path = jobpath.replace('\\', '/')
        job = wmi.WMI(moniker=job_wmi_path)

        while job.JobState == constants.WMI_JOB_STATE_RUNNING:
            time.sleep(0.1)
            job = wmi.WMI(moniker=job_wmi_path)
        return job.JobState == constants.WMI_JOB_STATE_COMPLETED

    def _get_vm(self, vm_name, conn=None):
        if conn is None:
            conn = self._conn
        vml = conn.Msvm_ComputerSystem(ElementName=vm_name)
        if not len(vml):
            raise exception.InstanceNotFound(instance=vm_name)
        return vml[0]

    def remote_vm_exists(self, server, vm_name):
        conn = wmi.WMI(moniker='//' + server + '/root/virtualization')
        return self._vm_exists(conn, vm_name)

    def vm_exists(self, vm_name):
        return self._vm_exists(self._conn, vm_name)

    def _vm_exists(self, conn, vm_name):
        return len(conn.Msvm_ComputerSystem(ElementName=vm_name)) > 0

    def _get_vm_summary(self, vm_name):
        vm = self._get_vm(vm_name)
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(
                       wmi_association_class='Msvm_SettingsDefineState',
                       wmi_result_class='Msvm_VirtualSystemSettingData')
        settings_paths = [v.path_() for v in vmsettings]
        return vs_man_svc.GetSummaryInformation([100, 105],
            settings_paths)[1][0]

    def get_vm_uptime(self, vm_name):
        return self._get_vm_summary(vm_name).UpTime

    def get_vm_state(self, vm_name):
        return self._get_vm_summary(vm_name).EnabledState

    def set_vm_state(self, vm_name, req_state):
        self._set_vm_state(self._conn, vm_name, req_state)

    def _set_vm_state(self, conn, vm_name, req_state):
        vm = self._get_vm(vm_name, conn)
        (job, ret_val) = vm.RequestStateChange(req_state)

        success = False
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        elif ret_val == 0:
            success = True
        elif ret_val == 32775:
            #Invalid state for current operation. Typically means it is
            #already in the state requested
            success = True
        if not success:
            raise Exception(_("Failed to change vm state of %(vm_name)s"
                    " to %(req_state)s") % locals())

    def get_vm_disks(self, vm_name):
        return self._get_vm_disks(self._conn, vm_name)

    def _get_vm_disks(self, conn, vm_name):
        vm = self._get_vm(vm_name, conn)
        vmsettings = vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
            wmi_result_class='MSVM_ResourceAllocationSettingData')

        disks = [r for r in rasds
            if r.ResourceSubType == 'Microsoft Virtual Hard Disk']
        disk_files = []
        for disk in disks:
            disk_files.extend([c for c in disk.Connection])

        volumes = [r for r in rasds
            if r.ResourceSubType == 'Microsoft Physical Disk Drive']
        volume_drives = []
        for volume in volumes:
            hostResources = volume.HostResource
            drive_path = hostResources[0]
            volume_drives.append(drive_path)

        return (disk_files, volume_drives)

    def remove_remote_vm(self, server, vm_name):
        conn = wmi.WMI(moniker='//' + server + '/root/virtualization')
        conn_cimv2 = wmi.WMI(moniker='//' + server + '/root/cimv2')
        self._remove_vm(vm_name, conn, conn_cimv2)

    def remove_vm(self, vm_name):
        self._remove_vm(vm_name, self._conn, self._conn_cimv2)

    def _remove_vm(self, vm_name, conn, conn_cimv2):
        vm = self._get_vm(vm_name, conn)
        vs_man_svc = conn.Msvm_VirtualSystemManagementService()[0]
        #Stop the VM first.
        self._set_vm_state(conn, vm_name, 3)

        (disk_files, volume_drives) = self._get_vm_disks(conn, vm_name)

        (job, ret_val) = vs_man_svc.DestroyVirtualSystem(vm.path_())
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        elif ret_val == 0:
            success = True
        if not success:
            raise Exception(_('Failed to destroy vm %s') % vm_name)

        #Delete associated vhd disk files.
        for disk in disk_files:
            vhd_file = conn_cimv2.query(
            "Select * from CIM_DataFile where Name = '" +
                disk.replace("'", "''") + "'")[0]
            vhd_file.Delete()

    def _get_target_iqn(self, volume_id):
        return 'iqn.2010-10.org.openstack:volume-' + volume_id

    def logout_iscsi_volume_sessions(self, volume_id):
        target_iqn = self._get_target_iqn(volume_id)
        self._volumeutils.logout_storage_target(self._conn_wmi, target_iqn)

    def iscsi_volume_sessions_exist(self, volume_id):
        target_iqn = self._get_target_iqn(volume_id)
        return len(self._conn_wmi.query(
                    "SELECT * FROM MSiSCSIInitiator_SessionClass \
                    WHERE TargetName='" + target_iqn + "'")) > 0

    def get_vm_count(self):
        return len(self._conn.query(
            "Select * from Msvm_ComputerSystem where Description "
            "<> 'Microsoft Hosting Computer System'"))

    def get_vm_snapshots_count(self, vm_name):
        return len(self._conn.query(
                "Select * from Msvm_VirtualSystemSettingData where \
                SettingType = 5 and SystemName = '" + vm_name + "'"))

    def get_vhd_parent_path(self, vhd_path):

        image_man_svc = self._conn.Msvm_ImageManagementService()[0]

        (vhd_info, job_path, ret_val) = \
            image_man_svc.GetVirtualHardDiskInfo(vhd_path)
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job_path)
        else:
            success = (ret_val == 0)
        if not success:
                raise Exception(_("Failed to get info for disk %s") %
                    (vhd_path))

        base_disk_path = None
        et = ElementTree.fromstring(vhd_info)
        for item in et.findall("PROPERTY"):
            if item.attrib["NAME"] == "ParentPath":
                base_disk_path = item.find("VALUE").text
                break

        return base_disk_path

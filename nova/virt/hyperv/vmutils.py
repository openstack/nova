# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Cloud.com, Inc
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
Utility class for VM related operations on Hyper-V.
"""

import sys
import time
import uuid

if sys.platform == 'win32':
    import wmi

from oslo.config import cfg

from nova import exception
from nova.openstack.common import log as logging
from nova.virt.hyperv import constants

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


# TODO(alexpilotti): Move the exceptions to a separate module
# TODO(alexpilotti): Add more domain exceptions
class HyperVException(exception.NovaException):
    def __init__(self, message=None):
        super(HyperVException, self).__init__(message)


# TODO(alexpilotti): Add a storage exception base class
class VHDResizeException(HyperVException):
    def __init__(self, message=None):
        super(HyperVException, self).__init__(message)


class VMUtils(object):

    def __init__(self, host='.'):
        if sys.platform == 'win32':
            self._conn = wmi.WMI(moniker='//%s/root/virtualization' % host)
            self._conn_cimv2 = wmi.WMI(moniker='//%s/root/cimv2' % host)

    def list_instances(self):
        """Return the names of all the instances known to Hyper-V."""
        vm_names = [v.ElementName
                    for v in self._conn.Msvm_ComputerSystem(['ElementName'],
                    Caption="Virtual Machine")]
        return vm_names

    def get_vm_summary_info(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(
            wmi_association_class='Msvm_SettingsDefineState',
            wmi_result_class='Msvm_VirtualSystemSettingData')
        settings_paths = [v.path_() for v in vmsettings]
        #See http://msdn.microsoft.com/en-us/library/cc160706%28VS.85%29.aspx
        (ret_val, summary_info) = vs_man_svc.GetSummaryInformation(
            [constants.VM_SUMMARY_NUM_PROCS,
             constants.VM_SUMMARY_ENABLED_STATE,
             constants.VM_SUMMARY_MEMORY_USAGE,
             constants.VM_SUMMARY_UPTIME],
            settings_paths)
        if ret_val:
            raise HyperVException(_('Cannot get VM summary data for: %s')
                                  % vm_name)

        si = summary_info[0]
        memory_usage = None
        if si.MemoryUsage is not None:
            memory_usage = long(si.MemoryUsage)
        up_time = None
        if si.UpTime is not None:
            up_time = long(si.UpTime)

        summary_info_dict = {'NumberOfProcessors': si.NumberOfProcessors,
                             'EnabledState': si.EnabledState,
                             'MemoryUsage': memory_usage,
                             'UpTime': up_time}
        return summary_info_dict

    def _lookup_vm_check(self, vm_name):
        vm = self._lookup_vm(vm_name)
        if not vm:
            raise exception.NotFound(_('VM not found: %s') % vm_name)
        return vm

    def _lookup_vm(self, vm_name):
        vms = self._conn.Msvm_ComputerSystem(ElementName=vm_name)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise HyperVException(_('Duplicate VM name found: %s') % vm_name)
        else:
            return vms[0]

    def vm_exists(self, vm_name):
        return self._lookup_vm(vm_name) is not None

    def _get_vm_setting_data(self, vm):
        vmsettings = vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        # Avoid snapshots
        return [s for s in vmsettings if s.SettingType == 3][0]

    def _set_vm_memory(self, vm, vmsetting, memory_mb):
        memsetting = vmsetting.associators(
            wmi_result_class='Msvm_MemorySettingData')[0]
        #No Dynamic Memory, so reservation, limit and quantity are identical.
        mem = long(memory_mb)
        memsetting.VirtualQuantity = mem
        memsetting.Reservation = mem
        memsetting.Limit = mem

        self._modify_virt_resource(memsetting, vm.path_())

    def _set_vm_vcpus(self, vm, vmsetting, vcpus_num, limit_cpu_features):
        procsetting = vmsetting.associators(
            wmi_result_class='Msvm_ProcessorSettingData')[0]
        vcpus = long(vcpus_num)
        procsetting.VirtualQuantity = vcpus
        procsetting.Reservation = vcpus
        procsetting.Limit = 100000  # static assignment to 100%
        procsetting.LimitProcessorFeatures = limit_cpu_features

        self._modify_virt_resource(procsetting, vm.path_())

    def update_vm(self, vm_name, memory_mb, vcpus_num, limit_cpu_features):
        vm = self._lookup_vm_check(vm_name)
        vmsetting = self._get_vm_setting_data(vm)
        self._set_vm_memory(vm, vmsetting, memory_mb)
        self._set_vm_vcpus(vm, vmsetting, vcpus_num, limit_cpu_features)

    def create_vm(self, vm_name, memory_mb, vcpus_num, limit_cpu_features):
        """Creates a VM."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        vs_gs_data = self._conn.Msvm_VirtualSystemGlobalSettingData.new()
        vs_gs_data.ElementName = vm_name

        LOG.debug(_('Creating VM %s'), vm_name)
        (job_path,
         ret_val) = vs_man_svc.DefineVirtualSystem([], None,
                                                   vs_gs_data.GetText_(1))[1:]
        self.check_ret_val(ret_val, job_path)

        vm = self._lookup_vm_check(vm_name)
        vmsetting = self._get_vm_setting_data(vm)

        LOG.debug(_('Setting memory for vm %s'), vm_name)
        self._set_vm_memory(vm, vmsetting, memory_mb)

        LOG.debug(_('Set vCPUs for vm %s'), vm_name)
        self._set_vm_vcpus(vm, vmsetting, vcpus_num, limit_cpu_features)

    def get_vm_scsi_controller(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vmsettings = vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
            wmi_result_class='MSVM_ResourceAllocationSettingData')
        res = [r for r in rasds
               if r.ResourceSubType ==
               'Microsoft Synthetic SCSI Controller'][0]
        return res.path_()

    def _get_vm_ide_controller(self, vm, ctrller_addr):
        vmsettings = vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
            wmi_result_class='MSVM_ResourceAllocationSettingData')
        return [r for r in rasds
                if r.ResourceSubType == 'Microsoft Emulated IDE Controller'
                and r.Address == str(ctrller_addr)][0].path_()

    def get_vm_ide_controller(self, vm_name, ctrller_addr):
        vm = self._lookup_vm_check(vm_name)
        return self._get_vm_ide_controller(vm, ctrller_addr)

    def get_attached_disks_count(self, scsi_controller_path):
        volumes = self._conn.query("SELECT * FROM "
                                   "Msvm_ResourceAllocationSettingData "
                                   "WHERE ResourceSubType LIKE "
                                   "'Microsoft Physical Disk Drive' "
                                   "AND Parent = '%s'" %
                                   scsi_controller_path.replace("'", "''"))
        return len(volumes)

    def attach_ide_drive(self, vm_name, path, ctrller_addr, drive_addr,
                         drive_type=constants.IDE_DISK):
        """Create an IDE drive and attach it to the vm."""

        vm = self._lookup_vm_check(vm_name)

        ctrller_path = self._get_vm_ide_controller(vm, ctrller_addr)

        if drive_type == constants.IDE_DISK:
            res_sub_type = 'Microsoft Synthetic Disk Drive'
        elif drive_type == constants.IDE_DVD:
            res_sub_type = 'Microsoft Synthetic DVD Drive'

        #Find the default disk drive object for the vm and clone it.
        drivedflt = self._conn.query("SELECT * FROM "
                                     "Msvm_ResourceAllocationSettingData "
                                     "WHERE ResourceSubType LIKE "
                                     "'%s' AND InstanceID LIKE "
                                     "'%%Default%%'" % res_sub_type)[0]
        drive = self._clone_wmi_obj('Msvm_ResourceAllocationSettingData',
                                    drivedflt)
        #Set the IDE ctrller as parent.
        drive.Parent = ctrller_path
        drive.Address = drive_addr
        #Add the cloned disk drive object to the vm.
        new_resources = self._add_virt_resource(drive, vm.path_())
        drive_path = new_resources[0]

        if drive_type == constants.IDE_DISK:
            res_sub_type = 'Microsoft Virtual Hard Disk'
        elif drive_type == constants.IDE_DVD:
            res_sub_type = 'Microsoft Virtual CD/DVD Disk'

        #Find the default VHD disk object.
        drivedefault = self._conn.query("SELECT * FROM "
                                        "Msvm_ResourceAllocationSettingData "
                                        "WHERE ResourceSubType LIKE "
                                        "'%s' AND "
                                        "InstanceID LIKE '%%Default%%'"
                                        % res_sub_type)[0]

        #Clone the default and point it to the image file.
        res = self._clone_wmi_obj('Msvm_ResourceAllocationSettingData',
                                  drivedefault)
        #Set the new drive as the parent.
        res.Parent = drive_path
        res.Connection = [path]

        #Add the new vhd object as a virtual hard disk to the vm.
        self._add_virt_resource(res, vm.path_())

    def create_scsi_controller(self, vm_name):
        """Create an iscsi controller ready to mount volumes."""

        vm = self._lookup_vm_check(vm_name)
        scsicontrldflt = self._conn.query("SELECT * FROM "
                                          "Msvm_ResourceAllocationSettingData "
                                          "WHERE ResourceSubType = 'Microsoft "
                                          "Synthetic SCSI Controller' AND "
                                          "InstanceID LIKE '%Default%'")[0]
        if scsicontrldflt is None:
            raise HyperVException(_('Controller not found'))
        scsicontrl = self._clone_wmi_obj('Msvm_ResourceAllocationSettingData',
                                         scsicontrldflt)
        scsicontrl.VirtualSystemIdentifiers = ['{' + str(uuid.uuid4()) + '}']
        self._add_virt_resource(scsicontrl, vm.path_())

    def attach_volume_to_controller(self, vm_name, controller_path, address,
                                    mounted_disk_path):
        """Attach a volume to a controller."""

        vm = self._lookup_vm_check(vm_name)

        diskdflt = self._conn.query("SELECT * FROM "
                                    "Msvm_ResourceAllocationSettingData "
                                    "WHERE ResourceSubType LIKE "
                                    "'Microsoft Physical Disk Drive' "
                                    "AND InstanceID LIKE '%Default%'")[0]
        diskdrive = self._clone_wmi_obj('Msvm_ResourceAllocationSettingData',
                                        diskdflt)
        diskdrive.Address = address
        diskdrive.Parent = controller_path
        diskdrive.HostResource = [mounted_disk_path]
        self._add_virt_resource(diskdrive, vm.path_())

    def set_nic_connection(self, vm_name, nic_name, vswitch_port):
        nic_data = self._get_nic_data_by_name(nic_name)
        nic_data.Connection = [vswitch_port]

        vm = self._lookup_vm_check(vm_name)
        self._modify_virt_resource(nic_data, vm.path_())

    def _get_nic_data_by_name(self, name):
        return self._conn.Msvm_SyntheticEthernetPortSettingData(
            ElementName=name)[0]

    def create_nic(self, vm_name, nic_name, mac_address):
        """Create a (synthetic) nic and attach it to the vm."""
        #Create a new nic
        syntheticnics_data = self._conn.Msvm_SyntheticEthernetPortSettingData()
        default_nic_data = [n for n in syntheticnics_data
                            if n.InstanceID.rfind('Default') > 0]
        new_nic_data = self._clone_wmi_obj(
            'Msvm_SyntheticEthernetPortSettingData', default_nic_data[0])

        #Configure the nic
        new_nic_data.ElementName = nic_name
        new_nic_data.Address = mac_address.replace(':', '')
        new_nic_data.StaticMacAddress = 'True'
        new_nic_data.VirtualSystemIdentifiers = ['{' + str(uuid.uuid4()) + '}']

        #Add the new nic to the vm
        vm = self._lookup_vm_check(vm_name)

        self._add_virt_resource(new_nic_data, vm.path_())

    def set_vm_state(self, vm_name, req_state):
        """Set the desired state of the VM."""
        vm = self._lookup_vm_check(vm_name)
        (job_path, ret_val) = vm.RequestStateChange(req_state)
        #Invalid state for current operation (32775) typically means that
        #the VM is already in the state requested
        self.check_ret_val(ret_val, job_path, [0, 32775])
        LOG.debug(_("Successfully changed vm state of %(vm_name)s "
                    "to %(req_state)s"),
                  {'vm_name': vm_name, 'req_state': req_state})

    def get_vm_storage_paths(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        self._conn.Msvm_VirtualSystemManagementService()
        vmsettings = vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
            wmi_result_class='MSVM_ResourceAllocationSettingData')
        disk_resources = [r for r in rasds
                          if r.ResourceSubType ==
                          'Microsoft Virtual Hard Disk']
        volume_resources = [r for r in rasds
                            if r.ResourceSubType ==
                            'Microsoft Physical Disk Drive']

        volume_drives = []
        for volume_resource in volume_resources:
            drive_path = volume_resource.HostResource[0]
            volume_drives.append(drive_path)

        disk_files = []
        for disk_resource in disk_resources:
            disk_files.extend([c for c in disk_resource.Connection])

        return (disk_files, volume_drives)

    def destroy_vm(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        #Remove the VM. Does not destroy disks.
        (job_path, ret_val) = vs_man_svc.DestroyVirtualSystem(vm.path_())
        self.check_ret_val(ret_val, job_path)

    def check_ret_val(self, ret_val, job_path, success_values=[0]):
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            self._wait_for_job(job_path)
        elif ret_val not in success_values:
            raise HyperVException(_('Operation failed with return value: %s')
                                  % ret_val)

    def _wait_for_job(self, job_path):
        """Poll WMI job state and wait for completion."""

        job_wmi_path = job_path.replace('\\', '/')
        job = wmi.WMI(moniker=job_wmi_path)

        while job.JobState == constants.WMI_JOB_STATE_RUNNING:
            time.sleep(0.1)
            job = wmi.WMI(moniker=job_wmi_path)
        if job.JobState != constants.WMI_JOB_STATE_COMPLETED:
            job_state = job.JobState
            if job.path().Class == "Msvm_ConcreteJob":
                err_sum_desc = job.ErrorSummaryDescription
                err_desc = job.ErrorDescription
                err_code = job.ErrorCode
                raise HyperVException(_("WMI job failed with status "
                                        "%(job_state)d. Error details: "
                                        "%(err_sum_desc)s - %(err_desc)s - "
                                        "Error code: %(err_code)d") %
                                      {'job_state': job_state,
                                       'err_sum_desc': err_sum_desc,
                                       'err_desc': err_desc,
                                       'err_code': err_code})
            else:
                (error, ret_val) = job.GetError()
                if not ret_val and error:
                    raise HyperVException(_("WMI job failed with status "
                                            "%(job_state)d. Error details: "
                                            "%(error)s") %
                                          {'job_state': job_state,
                                           'error': error})
                else:
                    raise HyperVException(_("WMI job failed with status "
                                            "%d. No error "
                                            "description available") %
                                          job_state)
        desc = job.Description
        elap = job.ElapsedTime
        LOG.debug(_("WMI job succeeded: %(desc)s, Elapsed=%(elap)s"),
                  {'desc': desc, 'elap': elap})

    def _clone_wmi_obj(self, wmi_class, wmi_obj):
        """Clone a WMI object."""
        cl = getattr(self._conn, wmi_class)  # get the class
        newinst = cl.new()
        #Copy the properties from the original.
        for prop in wmi_obj._properties:
            if prop == "VirtualSystemIdentifiers":
                strguid = []
                strguid.append(str(uuid.uuid4()))
                newinst.Properties_.Item(prop).Value = strguid
            else:
                prop_value = wmi_obj.Properties_.Item(prop).Value
                newinst.Properties_.Item(prop).Value = prop_value

        return newinst

    def _add_virt_resource(self, res_setting_data, vm_path):
        """Adds a new resource to the VM."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        res_xml = [res_setting_data.GetText_(1)]
        (job_path,
         new_resources,
         ret_val) = vs_man_svc.AddVirtualSystemResources(res_xml, vm_path)
        self.check_ret_val(ret_val, job_path)
        return new_resources

    def _modify_virt_resource(self, res_setting_data, vm_path):
        """Updates a VM resource."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        (job_path, ret_val) = vs_man_svc.ModifyVirtualSystemResources(
            ResourceSettingData=[res_setting_data.GetText_(1)],
            ComputerSystem=vm_path)
        self.check_ret_val(ret_val, job_path)

    def _remove_virt_resource(self, res_setting_data, vm_path):
        """Removes a VM resource."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        res_path = [res_setting_data.path_()]
        (job_path, ret_val) = vs_man_svc.RemoveVirtualSystemResources(res_path,
                                                                      vm_path)
        self.check_ret_val(ret_val, job_path)

    def take_vm_snapshot(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        (job_path, ret_val,
         snp_setting_data) = vs_man_svc.CreateVirtualSystemSnapshot(vm.path_())
        self.check_ret_val(ret_val, job_path)

        job_wmi_path = job_path.replace('\\', '/')
        job = wmi.WMI(moniker=job_wmi_path)
        snp_setting_data = job.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')[0]
        return snp_setting_data.path_()

    def remove_vm_snapshot(self, snapshot_path):
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        (job_path, ret_val) = vs_man_svc.RemoveVirtualSystemSnapshot(
            snapshot_path)
        self.check_ret_val(ret_val, job_path)

    def detach_vm_disk(self, vm_name, disk_path):
        vm = self._lookup_vm_check(vm_name)
        physical_disk = self._get_mounted_disk_resource_from_path(
            disk_path)
        if physical_disk:
            self._remove_virt_resource(physical_disk, vm.path_())

    def _get_mounted_disk_resource_from_path(self, disk_path):
        physical_disks = self._conn.query("SELECT * FROM "
                                          "Msvm_ResourceAllocationSettingData"
                                          " WHERE ResourceSubType = "
                                          "'Microsoft Physical Disk Drive'")
        for physical_disk in physical_disks:
            if physical_disk.HostResource:
                if physical_disk.HostResource[0].lower() == disk_path.lower():
                    return physical_disk

    def get_mounted_disk_by_drive_number(self, device_number):
        mounted_disks = self._conn.query("SELECT * FROM Msvm_DiskDrive "
                                         "WHERE DriveNumber=" +
                                         str(device_number))
        if len(mounted_disks):
            return mounted_disks[0].path_()

    def get_controller_volume_paths(self, controller_path):
        disks = self._conn.query("SELECT * FROM "
                                 "Msvm_ResourceAllocationSettingData "
                                 "WHERE ResourceSubType="
                                 "'Microsoft Physical Disk Drive' AND "
                                 "Parent='%s'" % controller_path)
        disk_data = {}
        for disk in disks:
            if disk.HostResource:
                disk_data[disk.path().RelPath] = disk.HostResource[0]
        return disk_data

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
from nova.openstack.common.gettextutils import _
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


class HyperVAuthorizationException(HyperVException):
    def __init__(self, message=None):
        super(HyperVException, self).__init__(message)


class UnsupportedConfigDriveFormatException(HyperVException):
    def __init__(self, message=None):
        super(HyperVException, self).__init__(message)


class VMUtils(object):

    # These constants can be overridden by inherited classes
    _PHYS_DISK_RES_SUB_TYPE = 'Microsoft Physical Disk Drive'
    _DISK_RES_SUB_TYPE = 'Microsoft Synthetic Disk Drive'
    _DVD_RES_SUB_TYPE = 'Microsoft Synthetic DVD Drive'
    _IDE_DISK_RES_SUB_TYPE = 'Microsoft Virtual Hard Disk'
    _IDE_DVD_RES_SUB_TYPE = 'Microsoft Virtual CD/DVD Disk'
    _IDE_CTRL_RES_SUB_TYPE = 'Microsoft Emulated IDE Controller'
    _SCSI_CTRL_RES_SUB_TYPE = 'Microsoft Synthetic SCSI Controller'

    _SETTINGS_DEFINE_STATE_CLASS = 'Msvm_SettingsDefineState'
    _VIRTUAL_SYSTEM_SETTING_DATA_CLASS = 'Msvm_VirtualSystemSettingData'
    _RESOURCE_ALLOC_SETTING_DATA_CLASS = 'Msvm_ResourceAllocationSettingData'
    _PROCESSOR_SETTING_DATA_CLASS = 'Msvm_ProcessorSettingData'
    _MEMORY_SETTING_DATA_CLASS = 'Msvm_MemorySettingData'
    _STORAGE_ALLOC_SETTING_DATA_CLASS = _RESOURCE_ALLOC_SETTING_DATA_CLASS
    _SYNTHETIC_ETHERNET_PORT_SETTING_DATA_CLASS = \
    'Msvm_SyntheticEthernetPortSettingData'
    _AFFECTED_JOB_ELEMENT_CLASS = "Msvm_AffectedJobElement"

    _vm_power_states_map = {constants.HYPERV_VM_STATE_ENABLED: 2,
                            constants.HYPERV_VM_STATE_DISABLED: 3,
                            constants.HYPERV_VM_STATE_REBOOT: 10,
                            constants.HYPERV_VM_STATE_PAUSED: 32768,
                            constants.HYPERV_VM_STATE_SUSPENDED: 32769}

    def __init__(self, host='.'):
        self._enabled_states_map = dict((v, k) for k, v in
                                        self._vm_power_states_map.iteritems())
        if sys.platform == 'win32':
            self._init_hyperv_wmi_conn(host)
            self._conn_cimv2 = wmi.WMI(moniker='//%s/root/cimv2' % host)

    def _init_hyperv_wmi_conn(self, host):
        self._conn = wmi.WMI(moniker='//%s/root/virtualization' % host)

    def list_instances(self):
        """Return the names of all the instances known to Hyper-V."""
        vm_names = [v.ElementName for v in
                    self._conn.Msvm_ComputerSystem(['ElementName'],
                                                   Caption="Virtual Machine")]
        return vm_names

    def get_vm_summary_info(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(
            wmi_association_class=self._SETTINGS_DEFINE_STATE_CLASS,
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
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

        enabled_state = self._enabled_states_map[si.EnabledState]

        summary_info_dict = {'NumberOfProcessors': si.NumberOfProcessors,
                             'EnabledState': enabled_state,
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

    def get_vm_id(self, vm_name):
        vm = self._lookup_vm_check(vm_name)
        return vm.Name

    def _get_vm_setting_data(self, vm):
        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        # Avoid snapshots
        return [s for s in vmsettings if s.SettingType == 3][0]

    def _set_vm_memory(self, vm, vmsetting, memory_mb, dynamic_memory_ratio):
        mem_settings = vmsetting.associators(
            wmi_result_class=self._MEMORY_SETTING_DATA_CLASS)[0]

        max_mem = long(memory_mb)
        mem_settings.Limit = max_mem

        if dynamic_memory_ratio > 1:
            mem_settings.DynamicMemoryEnabled = True
            # Must be a multiple of 2
            reserved_mem = min(
                long(max_mem / dynamic_memory_ratio) >> 1 << 1,
                max_mem)
        else:
            mem_settings.DynamicMemoryEnabled = False
            reserved_mem = max_mem

        mem_settings.Reservation = reserved_mem
        # Start with the minimum memory
        mem_settings.VirtualQuantity = reserved_mem

        self._modify_virt_resource(mem_settings, vm.path_())

    def _set_vm_vcpus(self, vm, vmsetting, vcpus_num, limit_cpu_features):
        procsetting = vmsetting.associators(
            wmi_result_class=self._PROCESSOR_SETTING_DATA_CLASS)[0]
        vcpus = long(vcpus_num)
        procsetting.VirtualQuantity = vcpus
        procsetting.Reservation = vcpus
        procsetting.Limit = 100000  # static assignment to 100%
        procsetting.LimitProcessorFeatures = limit_cpu_features

        self._modify_virt_resource(procsetting, vm.path_())

    def update_vm(self, vm_name, memory_mb, vcpus_num, limit_cpu_features,
                  dynamic_memory_ratio):
        vm = self._lookup_vm_check(vm_name)
        vmsetting = self._get_vm_setting_data(vm)
        self._set_vm_memory(vm, vmsetting, memory_mb, dynamic_memory_ratio)
        self._set_vm_vcpus(vm, vmsetting, vcpus_num, limit_cpu_features)

    def check_admin_permissions(self):
        if not self._conn.Msvm_VirtualSystemManagementService():
            msg = _("The Windows account running nova-compute on this Hyper-V"
                    " host doesn't have the required permissions to create or"
                    " operate the virtual machine.")
            raise HyperVAuthorizationException(msg)

    def create_vm(self, vm_name, memory_mb, vcpus_num, limit_cpu_features,
                  dynamic_memory_ratio):
        """Creates a VM."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        LOG.debug(_('Creating VM %s'), vm_name)
        vm = self._create_vm_obj(vs_man_svc, vm_name)

        vmsetting = self._get_vm_setting_data(vm)

        LOG.debug(_('Setting memory for vm %s'), vm_name)
        self._set_vm_memory(vm, vmsetting, memory_mb, dynamic_memory_ratio)

        LOG.debug(_('Set vCPUs for vm %s'), vm_name)
        self._set_vm_vcpus(vm, vmsetting, vcpus_num, limit_cpu_features)

    def _create_vm_obj(self, vs_man_svc, vm_name):
        vs_gs_data = self._conn.Msvm_VirtualSystemGlobalSettingData.new()
        vs_gs_data.ElementName = vm_name

        (job_path,
         ret_val) = vs_man_svc.DefineVirtualSystem([], None,
                                                   vs_gs_data.GetText_(1))[1:]
        self.check_ret_val(ret_val, job_path)

        return self._lookup_vm_check(vm_name)

    def get_vm_scsi_controller(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        rasds = vmsettings[0].associators(
            wmi_result_class=self._RESOURCE_ALLOC_SETTING_DATA_CLASS)
        res = [r for r in rasds
               if r.ResourceSubType == self._SCSI_CTRL_RES_SUB_TYPE][0]
        return res.path_()

    def _get_vm_ide_controller(self, vm, ctrller_addr):
        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        rasds = vmsettings[0].associators(
            wmi_result_class=self._RESOURCE_ALLOC_SETTING_DATA_CLASS)
        return [r for r in rasds
                if r.ResourceSubType == self._IDE_CTRL_RES_SUB_TYPE
                and r.Address == str(ctrller_addr)][0].path_()

    def get_vm_ide_controller(self, vm_name, ctrller_addr):
        vm = self._lookup_vm_check(vm_name)
        return self._get_vm_ide_controller(vm, ctrller_addr)

    def get_attached_disks(self, scsi_controller_path):
        volumes = self._conn.query("SELECT * FROM %(class_name)s "
                                   "WHERE ResourceSubType = "
                                   "'%(res_sub_type)s' AND "
                                   "Parent = '%(parent)s'" %
                                   {"class_name":
                                    self._RESOURCE_ALLOC_SETTING_DATA_CLASS,
                                    'res_sub_type':
                                    self._PHYS_DISK_RES_SUB_TYPE,
                                    'parent':
                                    scsi_controller_path.replace("'", "''")})
        return volumes

    def _get_new_setting_data(self, class_name):
        return self._conn.query("SELECT * FROM %s WHERE InstanceID "
                                "LIKE '%%\\Default'" % class_name)[0]

    def _get_new_resource_setting_data(self, resource_sub_type,
                                       class_name=None):
        if class_name is None:
            class_name = self._RESOURCE_ALLOC_SETTING_DATA_CLASS
        return self._conn.query("SELECT * FROM %(class_name)s "
                                "WHERE ResourceSubType = "
                                "'%(res_sub_type)s' AND "
                                "InstanceID LIKE '%%\\Default'" %
                                {"class_name": class_name,
                                 "res_sub_type": resource_sub_type})[0]

    def attach_ide_drive(self, vm_name, path, ctrller_addr, drive_addr,
                         drive_type=constants.IDE_DISK):
        """Create an IDE drive and attach it to the vm."""

        vm = self._lookup_vm_check(vm_name)

        ctrller_path = self._get_vm_ide_controller(vm, ctrller_addr)

        if drive_type == constants.IDE_DISK:
            res_sub_type = self._DISK_RES_SUB_TYPE
        elif drive_type == constants.IDE_DVD:
            res_sub_type = self._DVD_RES_SUB_TYPE

        drive = self._get_new_resource_setting_data(res_sub_type)

        #Set the IDE ctrller as parent.
        drive.Parent = ctrller_path
        drive.Address = drive_addr
        #Add the cloned disk drive object to the vm.
        new_resources = self._add_virt_resource(drive, vm.path_())
        drive_path = new_resources[0]

        if drive_type == constants.IDE_DISK:
            res_sub_type = self._IDE_DISK_RES_SUB_TYPE
        elif drive_type == constants.IDE_DVD:
            res_sub_type = self._IDE_DVD_RES_SUB_TYPE

        res = self._get_new_resource_setting_data(res_sub_type)
        #Set the new drive as the parent.
        res.Parent = drive_path
        res.Connection = [path]

        #Add the new vhd object as a virtual hard disk to the vm.
        self._add_virt_resource(res, vm.path_())

    def create_scsi_controller(self, vm_name):
        """Create an iscsi controller ready to mount volumes."""

        vm = self._lookup_vm_check(vm_name)
        scsicontrl = self._get_new_resource_setting_data(
            self._SCSI_CTRL_RES_SUB_TYPE)

        scsicontrl.VirtualSystemIdentifiers = ['{' + str(uuid.uuid4()) + '}']
        self._add_virt_resource(scsicontrl, vm.path_())

    def attach_volume_to_controller(self, vm_name, controller_path, address,
                                    mounted_disk_path):
        """Attach a volume to a controller."""

        vm = self._lookup_vm_check(vm_name)

        diskdrive = self._get_new_resource_setting_data(
            self._PHYS_DISK_RES_SUB_TYPE)

        diskdrive.Address = address
        diskdrive.Parent = controller_path
        diskdrive.HostResource = [mounted_disk_path]
        self._add_virt_resource(diskdrive, vm.path_())

    def set_nic_connection(self, vm_name, nic_name, vswitch_conn_data):
        nic_data = self._get_nic_data_by_name(nic_name)
        nic_data.Connection = [vswitch_conn_data]

        vm = self._lookup_vm_check(vm_name)
        self._modify_virt_resource(nic_data, vm.path_())

    def _get_nic_data_by_name(self, name):
        return self._conn.Msvm_SyntheticEthernetPortSettingData(
            ElementName=name)[0]

    def create_nic(self, vm_name, nic_name, mac_address):
        """Create a (synthetic) nic and attach it to the vm."""
        #Create a new nic
        new_nic_data = self._get_new_setting_data(
            self._SYNTHETIC_ETHERNET_PORT_SETTING_DATA_CLASS)

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
        (job_path,
         ret_val) = vm.RequestStateChange(self._vm_power_states_map[req_state])
        #Invalid state for current operation (32775) typically means that
        #the VM is already in the state requested
        self.check_ret_val(ret_val, job_path, [0, 32775])
        LOG.debug(_("Successfully changed vm state of %(vm_name)s "
                    "to %(req_state)s"),
                  {'vm_name': vm_name, 'req_state': req_state})

    def _get_disk_resource_disk_path(self, disk_resource):
        return disk_resource.Connection

    def get_vm_storage_paths(self, vm_name):
        vm = self._lookup_vm_check(vm_name)
        (disk_resources, volume_resources) = self._get_vm_disks(vm)

        volume_drives = []
        for volume_resource in volume_resources:
            drive_path = volume_resource.HostResource[0]
            volume_drives.append(drive_path)

        disk_files = []
        for disk_resource in disk_resources:
            disk_files.extend(
                [c for c in self._get_disk_resource_disk_path(disk_resource)])

        return (disk_files, volume_drives)

    def _get_vm_disks(self, vm):
        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        rasds = vmsettings[0].associators(
            wmi_result_class=self._STORAGE_ALLOC_SETTING_DATA_CLASS)
        disk_resources = [r for r in rasds if
                          r.ResourceSubType in
                          [self._IDE_DISK_RES_SUB_TYPE,
                           self._IDE_DVD_RES_SUB_TYPE]]
        volume_resources = [r for r in rasds if
                            r.ResourceSubType == self._PHYS_DISK_RES_SUB_TYPE]

        return (disk_resources, volume_resources)

    def destroy_vm(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        #Remove the VM. Does not destroy disks.
        (job_path, ret_val) = vs_man_svc.DestroyVirtualSystem(vm.path_())
        self.check_ret_val(ret_val, job_path)

    def check_ret_val(self, ret_val, job_path, success_values=[0]):
        if ret_val == constants.WMI_JOB_STATUS_STARTED:
            return self._wait_for_job(job_path)
        elif ret_val not in success_values:
            raise HyperVException(_('Operation failed with return value: %s')
                                  % ret_val)

    def _wait_for_job(self, job_path):
        """Poll WMI job state and wait for completion."""
        job = self._get_wmi_obj(job_path)

        while job.JobState == constants.WMI_JOB_STATE_RUNNING:
            time.sleep(0.1)
            job = self._get_wmi_obj(job_path)
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
        return job

    def _get_wmi_obj(self, path):
        return wmi.WMI(moniker=path.replace('\\', '/'))

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
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)[0]
        return snp_setting_data.path_()

    def remove_vm_snapshot(self, snapshot_path):
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        (job_path, ret_val) = vs_man_svc.RemoveVirtualSystemSnapshot(
            snapshot_path)
        self.check_ret_val(ret_val, job_path)

    def detach_vm_disk(self, vm_name, disk_path):
        vm = self._lookup_vm_check(vm_name)
        physical_disk = self._get_mounted_disk_resource_from_path(disk_path)
        if physical_disk:
            self._remove_virt_resource(physical_disk, vm.path_())

    def _get_mounted_disk_resource_from_path(self, disk_path):
        physical_disks = self._conn.query("SELECT * FROM %(class_name)s "
                             "WHERE ResourceSubType = '%(res_sub_type)s'" %
                             {"class_name":
                              self._RESOURCE_ALLOC_SETTING_DATA_CLASS,
                              'res_sub_type':
                              self._PHYS_DISK_RES_SUB_TYPE})
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
        disks = self._conn.query("SELECT * FROM %(class_name)s "
                                 "WHERE ResourceSubType = '%(res_sub_type)s' "
                                 "AND Parent='%(parent)s'" %
                                 {"class_name":
                                  self._RESOURCE_ALLOC_SETTING_DATA_CLASS,
                                  "res_sub_type":
                                  self._PHYS_DISK_RES_SUB_TYPE,
                                  "parent":
                                  controller_path})
        disk_data = {}
        for disk in disks:
            if disk.HostResource:
                disk_data[disk.path().RelPath] = disk.HostResource[0]
        return disk_data

    def enable_vm_metrics_collection(self, vm_name):
        raise NotImplementedError(_("Metrics collection is not supported on "
                                    "this version of Hyper-V"))

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

from oslo_config import cfg

from nova import exception
from nova.i18n import _, _LW
from nova.openstack.common import log as logging
from nova.virt.hyperv import constants
from nova.virt.hyperv import hostutils

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
    _DISK_DRIVE_RES_SUB_TYPE = 'Microsoft Synthetic Disk Drive'
    _DVD_DRIVE_RES_SUB_TYPE = 'Microsoft Synthetic DVD Drive'
    _HARD_DISK_RES_SUB_TYPE = 'Microsoft Virtual Hard Disk'
    _DVD_DISK_RES_SUB_TYPE = 'Microsoft Virtual CD/DVD Disk'
    _IDE_CTRL_RES_SUB_TYPE = 'Microsoft Emulated IDE Controller'
    _SCSI_CTRL_RES_SUB_TYPE = 'Microsoft Synthetic SCSI Controller'
    _SERIAL_PORT_RES_SUB_TYPE = 'Microsoft Serial Port'

    _SETTINGS_DEFINE_STATE_CLASS = 'Msvm_SettingsDefineState'
    _VIRTUAL_SYSTEM_SETTING_DATA_CLASS = 'Msvm_VirtualSystemSettingData'
    _RESOURCE_ALLOC_SETTING_DATA_CLASS = 'Msvm_ResourceAllocationSettingData'
    _PROCESSOR_SETTING_DATA_CLASS = 'Msvm_ProcessorSettingData'
    _MEMORY_SETTING_DATA_CLASS = 'Msvm_MemorySettingData'
    _STORAGE_ALLOC_SETTING_DATA_CLASS = _RESOURCE_ALLOC_SETTING_DATA_CLASS
    _SYNTHETIC_ETHERNET_PORT_SETTING_DATA_CLASS = \
    'Msvm_SyntheticEthernetPortSettingData'
    _AFFECTED_JOB_ELEMENT_CLASS = "Msvm_AffectedJobElement"

    _SHUTDOWN_COMPONENT = "Msvm_ShutdownComponent"
    _VIRTUAL_SYSTEM_CURRENT_SETTINGS = 3
    _AUTOMATIC_STARTUP_ACTION_NONE = 0

    _vm_power_states_map = {constants.HYPERV_VM_STATE_ENABLED: 2,
                            constants.HYPERV_VM_STATE_DISABLED: 3,
                            constants.HYPERV_VM_STATE_SHUTTING_DOWN: 4,
                            constants.HYPERV_VM_STATE_REBOOT: 10,
                            constants.HYPERV_VM_STATE_PAUSED: 32768,
                            constants.HYPERV_VM_STATE_SUSPENDED: 32769}

    def __init__(self, host='.'):
        self._enabled_states_map = {v: k for k, v in
                                    self._vm_power_states_map.iteritems()}
        if sys.platform == 'win32':
            self._init_hyperv_wmi_conn(host)
            self._conn_cimv2 = wmi.WMI(moniker='//%s/root/cimv2' % host)

        # On version of Hyper-V prior to 2012 trying to directly set properties
        # in default setting data WMI objects results in an exception
        self._clone_wmi_objs = False
        if sys.platform == 'win32':
            hostutls = hostutils.HostUtils()
            self._clone_wmi_objs = not hostutls.check_min_windows_version(6, 2)

    def _init_hyperv_wmi_conn(self, host):
        self._conn = wmi.WMI(moniker='//%s/root/virtualization' % host)

    def list_instance_notes(self):
        instance_notes = []

        for vs in self._conn.Msvm_VirtualSystemSettingData(
                ['ElementName', 'Notes'],
                SettingType=self._VIRTUAL_SYSTEM_CURRENT_SETTINGS):
            instance_notes.append((vs.ElementName,
                                  [v for v in vs.Notes.split('\n') if v]))

        return instance_notes

    def list_instances(self):
        """Return the names of all the instances known to Hyper-V."""
        return [v.ElementName for v in
                self._conn.Msvm_VirtualSystemSettingData(
                    ['ElementName'],
                    SettingType=self._VIRTUAL_SYSTEM_CURRENT_SETTINGS)]

    def get_vm_summary_info(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(
            wmi_association_class=self._SETTINGS_DEFINE_STATE_CLASS,
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        settings_paths = [v.path_() for v in vmsettings]
        # See http://msdn.microsoft.com/en-us/library/cc160706%28VS.85%29.aspx
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

        # Nova requires a valid state to be returned. Hyper-V has more
        # states than Nova, typically intermediate ones and since there is
        # no direct mapping for those, ENABLED is the only reasonable option
        # considering that in all the non mappable states the instance
        # is running.
        enabled_state = self._enabled_states_map.get(si.EnabledState,
            constants.HYPERV_VM_STATE_ENABLED)

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
                  dynamic_memory_ratio, vm_gen, notes=None):
        """Creates a VM."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        LOG.debug('Creating VM %s', vm_name)
        vm = self._create_vm_obj(vs_man_svc, vm_name, vm_gen, notes,
                                 dynamic_memory_ratio)

        vmsetting = self._get_vm_setting_data(vm)

        LOG.debug('Setting memory for vm %s', vm_name)
        self._set_vm_memory(vm, vmsetting, memory_mb, dynamic_memory_ratio)

        LOG.debug('Set vCPUs for vm %s', vm_name)
        self._set_vm_vcpus(vm, vmsetting, vcpus_num, limit_cpu_features)

    def _create_vm_obj(self, vs_man_svc, vm_name, vm_gen, notes,
                       dynamic_memory_ratio):
        vs_gs_data = self._conn.Msvm_VirtualSystemGlobalSettingData.new()
        vs_gs_data.ElementName = vm_name
        # Don't start automatically on host boot
        vs_gs_data.AutomaticStartupAction = self._AUTOMATIC_STARTUP_ACTION_NONE

        (vm_path,
         job_path,
         ret_val) = vs_man_svc.DefineVirtualSystem([], None,
                                                   vs_gs_data.GetText_(1))
        self.check_ret_val(ret_val, job_path)

        vm = self._get_wmi_obj(vm_path)

        if notes:
            vmsetting = self._get_vm_setting_data(vm)
            vmsetting.Notes = '\n'.join(notes)
            self._modify_virtual_system(vs_man_svc, vm_path, vmsetting)

        return self._get_wmi_obj(vm_path)

    def _modify_virtual_system(self, vs_man_svc, vm_path, vmsetting):
        (job_path, ret_val) = vs_man_svc.ModifyVirtualSystem(
            ComputerSystem=vm_path,
            SystemSettingData=vmsetting.GetText_(1))[1:]
        self.check_ret_val(ret_val, job_path)

    def get_vm_scsi_controller(self, vm_name):
        vm = self._lookup_vm_check(vm_name)
        return self._get_vm_scsi_controller(vm)

    def _get_vm_scsi_controller(self, vm):
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
        ide_ctrls = [r for r in rasds
                     if r.ResourceSubType == self._IDE_CTRL_RES_SUB_TYPE
                     and r.Address == str(ctrller_addr)]

        return ide_ctrls[0].path_() if ide_ctrls else None

    def get_vm_ide_controller(self, vm_name, ctrller_addr):
        vm = self._lookup_vm_check(vm_name)
        return self._get_vm_ide_controller(vm, ctrller_addr)

    def get_attached_disks(self, scsi_controller_path):
        volumes = self._conn.query(
            self._get_attached_disks_query_string(scsi_controller_path))
        return volumes

    def _get_attached_disks_query_string(self, scsi_controller_path):
        return ("SELECT * FROM %(class_name)s WHERE ("
                "ResourceSubType='%(res_sub_type)s' OR "
                "ResourceSubType='%(res_sub_type_virt)s') AND "
                "Parent='%(parent)s'" % {
                    'class_name': self._RESOURCE_ALLOC_SETTING_DATA_CLASS,
                    'res_sub_type': self._PHYS_DISK_RES_SUB_TYPE,
                    'res_sub_type_virt': self._DISK_DRIVE_RES_SUB_TYPE,
                    'parent': scsi_controller_path.replace("'", "''")})

    def _get_new_setting_data(self, class_name):
        obj = self._conn.query("SELECT * FROM %s WHERE InstanceID "
                                "LIKE '%%\\Default'" % class_name)[0]
        return self._check_clone_wmi_obj(class_name, obj)

    def _get_new_resource_setting_data(self, resource_sub_type,
                                       class_name=None):
        if class_name is None:
            class_name = self._RESOURCE_ALLOC_SETTING_DATA_CLASS
        obj = self._conn.query("SELECT * FROM %(class_name)s "
                                "WHERE ResourceSubType = "
                                "'%(res_sub_type)s' AND "
                                "InstanceID LIKE '%%\\Default'" %
                                {"class_name": class_name,
                                 "res_sub_type": resource_sub_type})[0]
        return self._check_clone_wmi_obj(class_name, obj)

    def _check_clone_wmi_obj(self, class_name, obj):
        if self._clone_wmi_objs:
            return self._clone_wmi_obj(class_name, obj)
        else:
            return obj

    def _clone_wmi_obj(self, class_name, obj):
        wmi_class = getattr(self._conn, class_name)
        new_obj = wmi_class.new()
        # Copy the properties from the original.
        for prop in obj._properties:
                value = obj.Properties_.Item(prop).Value
                new_obj.Properties_.Item(prop).Value = value
        return new_obj

    def attach_scsi_drive(self, vm_name, path, drive_type=constants.DISK):
        vm = self._lookup_vm_check(vm_name)
        ctrller_path = self._get_vm_scsi_controller(vm)
        drive_addr = self.get_free_controller_slot(ctrller_path)
        self.attach_drive(vm_name, path, ctrller_path, drive_addr, drive_type)

    def attach_ide_drive(self, vm_name, path, ctrller_addr, drive_addr,
                         drive_type=constants.DISK):
        vm = self._lookup_vm_check(vm_name)
        ctrller_path = self._get_vm_ide_controller(vm, ctrller_addr)
        self.attach_drive(vm_name, path, ctrller_path, drive_addr, drive_type)

    def attach_drive(self, vm_name, path, ctrller_path, drive_addr,
                     drive_type=constants.DISK):
        """Create a drive and attach it to the vm."""

        vm = self._lookup_vm_check(vm_name)

        if drive_type == constants.DISK:
            res_sub_type = self._DISK_DRIVE_RES_SUB_TYPE
        elif drive_type == constants.DVD:
            res_sub_type = self._DVD_DRIVE_RES_SUB_TYPE

        drive = self._get_new_resource_setting_data(res_sub_type)

        # Set the ctrller as parent.
        drive.Parent = ctrller_path
        drive.Address = drive_addr
        # Add the cloned disk drive object to the vm.
        new_resources = self._add_virt_resource(drive, vm.path_())
        drive_path = new_resources[0]

        if drive_type == constants.DISK:
            res_sub_type = self._HARD_DISK_RES_SUB_TYPE
        elif drive_type == constants.DVD:
            res_sub_type = self._DVD_DISK_RES_SUB_TYPE

        res = self._get_new_resource_setting_data(res_sub_type)
        # Set the new drive as the parent.
        res.Parent = drive_path
        res.Connection = [path]

        # Add the new vhd object as a virtual hard disk to the vm.
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

    def _get_disk_resource_address(self, disk_resource):
        return disk_resource.Address

    def set_disk_host_resource(self, vm_name, controller_path, address,
                               mounted_disk_path):
        disk_found = False
        vm = self._lookup_vm_check(vm_name)
        (disk_resources, volume_resources) = self._get_vm_disks(vm)
        for disk_resource in disk_resources + volume_resources:
            if (disk_resource.Parent == controller_path and
                    self._get_disk_resource_address(disk_resource) ==
                    str(address)):
                if (disk_resource.HostResource and
                        disk_resource.HostResource[0] != mounted_disk_path):
                    LOG.debug('Updating disk host resource "%(old)s" to '
                                '"%(new)s"' %
                              {'old': disk_resource.HostResource[0],
                               'new': mounted_disk_path})
                    disk_resource.HostResource = [mounted_disk_path]
                    self._modify_virt_resource(disk_resource, vm.path_())
                disk_found = True
                break
        if not disk_found:
            LOG.warning(_LW('Disk not found on controller '
                            '"%(controller_path)s" with '
                            'address "%(address)s"'),
                        {'controller_path': controller_path,
                         'address': address})

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
        # Create a new nic
        new_nic_data = self._get_new_setting_data(
            self._SYNTHETIC_ETHERNET_PORT_SETTING_DATA_CLASS)

        # Configure the nic
        new_nic_data.ElementName = nic_name
        new_nic_data.Address = mac_address.replace(':', '')
        new_nic_data.StaticMacAddress = 'True'
        new_nic_data.VirtualSystemIdentifiers = ['{' + str(uuid.uuid4()) + '}']

        # Add the new nic to the vm
        vm = self._lookup_vm_check(vm_name)

        self._add_virt_resource(new_nic_data, vm.path_())

    def soft_shutdown_vm(self, vm_name):
        vm = self._lookup_vm_check(vm_name)
        shutdown_component = vm.associators(
            wmi_result_class=self._SHUTDOWN_COMPONENT)

        if not shutdown_component:
            # If no shutdown_component is found, it means the VM is already
            # in a shutdown state.
            return

        reason = 'Soft shutdown requested by OpenStack Nova.'
        (ret_val, ) = shutdown_component[0].InitiateShutdown(Force=False,
                                                             Reason=reason)
        self.check_ret_val(ret_val, None)

    def set_vm_state(self, vm_name, req_state):
        """Set the desired state of the VM."""
        vm = self._lookup_vm_check(vm_name)
        (job_path,
         ret_val) = vm.RequestStateChange(self._vm_power_states_map[req_state])
        # Invalid state for current operation (32775) typically means that
        # the VM is already in the state requested
        self.check_ret_val(ret_val, job_path, [0, 32775])
        LOG.debug("Successfully changed vm state of %(vm_name)s "
                  "to %(req_state)s",
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
                          [self._HARD_DISK_RES_SUB_TYPE,
                           self._DVD_DISK_RES_SUB_TYPE]]

        if (self._RESOURCE_ALLOC_SETTING_DATA_CLASS !=
                self._STORAGE_ALLOC_SETTING_DATA_CLASS):
            rasds = vmsettings[0].associators(
                wmi_result_class=self._RESOURCE_ALLOC_SETTING_DATA_CLASS)

        volume_resources = [r for r in rasds if
                            r.ResourceSubType == self._PHYS_DISK_RES_SUB_TYPE]

        return (disk_resources, volume_resources)

    def destroy_vm(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        # Remove the VM. Does not destroy disks.
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
        LOG.debug("WMI job succeeded: %(desc)s, Elapsed=%(elap)s",
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

    def detach_vm_disk(self, vm_name, disk_path, is_physical=True):
        vm = self._lookup_vm_check(vm_name)
        disk_resource = self._get_mounted_disk_resource_from_path(disk_path,
                                                                  is_physical)

        if disk_resource:
            parent = self._conn.query("SELECT * FROM "
                                      "Msvm_ResourceAllocationSettingData "
                                      "WHERE __PATH = '%s'" %
                                      disk_resource.Parent)[0]

            self._remove_virt_resource(disk_resource, vm.path_())
            if not is_physical:
                self._remove_virt_resource(parent, vm.path_())

    def _get_mounted_disk_resource_from_path(self, disk_path, is_physical):
        if is_physical:
            class_name = self._RESOURCE_ALLOC_SETTING_DATA_CLASS
            res_sub_type = self._PHYS_DISK_RES_SUB_TYPE
        else:
            class_name = self._STORAGE_ALLOC_SETTING_DATA_CLASS
            res_sub_type = self._HARD_DISK_RES_SUB_TYPE

        disk_resources = self._conn.query("SELECT * FROM %(class_name)s "
                                          "WHERE ResourceSubType = "
                                          "'%(res_sub_type)s'" %
                                          {"class_name": class_name,
                                           "res_sub_type": res_sub_type})

        for disk_resource in disk_resources:
            if disk_resource.HostResource:
                if disk_resource.HostResource[0].lower() == disk_path.lower():
                    return disk_resource

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

    def get_free_controller_slot(self, scsi_controller_path):
        attached_disks = self.get_attached_disks(scsi_controller_path)
        used_slots = [int(disk.AddressOnParent) for disk in attached_disks]

        for slot in xrange(constants.SCSI_CONTROLLER_SLOTS_NUMBER):
            if slot not in used_slots:
                return slot
        raise HyperVException(_("Exceeded the maximum number of slots"))

    def enable_vm_metrics_collection(self, vm_name):
        raise NotImplementedError(_("Metrics collection is not supported on "
                                    "this version of Hyper-V"))

    def get_vm_serial_port_connection(self, vm_name, update_connection=None):
        vm = self._lookup_vm_check(vm_name)

        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        rasds = vmsettings[0].associators(
            wmi_result_class=self._RESOURCE_ALLOC_SETTING_DATA_CLASS)
        serial_port = (
            [r for r in rasds if
             r.ResourceSubType == self._SERIAL_PORT_RES_SUB_TYPE][0])

        if update_connection:
            serial_port.Connection = [update_connection]
            self._modify_virt_resource(serial_port, vm.path_())

        if len(serial_port.Connection) > 0:
            return serial_port.Connection[0]

    def get_active_instances(self):
        """Return the names of all the active instances known to Hyper-V."""
        vm_names = self.list_instances()
        vms = [self._lookup_vm(vm_name) for vm_name in vm_names]
        active_vm_names = [v.ElementName for v in vms
            if v.EnabledState == constants.HYPERV_VM_STATE_ENABLED]

        return active_vm_names

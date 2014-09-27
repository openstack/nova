# Copyright 2013 Cloudbase Solutions Srl
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
Based on the "root/virtualization/v2" namespace available starting with
Hyper-V Server / Windows Server 2012.
"""

import sys
import uuid

if sys.platform == 'win32':
    import wmi

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmutils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VMUtilsV2(vmutils.VMUtils):

    _PHYS_DISK_RES_SUB_TYPE = 'Microsoft:Hyper-V:Physical Disk Drive'
    _DISK_RES_SUB_TYPE = 'Microsoft:Hyper-V:Synthetic Disk Drive'
    _DVD_RES_SUB_TYPE = 'Microsoft:Hyper-V:Synthetic DVD Drive'
    _SCSI_RES_SUBTYPE = 'Microsoft:Hyper-V:Synthetic SCSI Controller'
    _IDE_DISK_RES_SUB_TYPE = 'Microsoft:Hyper-V:Virtual Hard Disk'
    _IDE_DVD_RES_SUB_TYPE = 'Microsoft:Hyper-V:Virtual CD/DVD Disk'
    _IDE_CTRL_RES_SUB_TYPE = 'Microsoft:Hyper-V:Emulated IDE Controller'
    _SCSI_CTRL_RES_SUB_TYPE = 'Microsoft:Hyper-V:Synthetic SCSI Controller'

    _VIRTUAL_SYSTEM_TYPE_REALIZED = 'Microsoft:Hyper-V:System:Realized'

    _SNAPSHOT_FULL = 2

    _METRIC_AGGR_CPU_AVG = 'Aggregated Average CPU Utilization'
    _METRIC_ENABLED = 2

    _STORAGE_ALLOC_SETTING_DATA_CLASS = 'Msvm_StorageAllocationSettingData'
    _ETHERNET_PORT_ALLOCATION_SETTING_DATA_CLASS = \
    'Msvm_EthernetPortAllocationSettingData'

    _vm_power_states_map = {constants.HYPERV_VM_STATE_ENABLED: 2,
                            constants.HYPERV_VM_STATE_DISABLED: 3,
                            constants.HYPERV_VM_STATE_REBOOT: 11,
                            constants.HYPERV_VM_STATE_PAUSED: 9,
                            constants.HYPERV_VM_STATE_SUSPENDED: 6}

    def __init__(self, host='.'):
        super(VMUtilsV2, self).__init__(host)

    def _init_hyperv_wmi_conn(self, host):
        self._conn = wmi.WMI(moniker='//%s/root/virtualization/v2' % host)

    def list_instance_notes(self):
        instance_notes = []

        for vs in self._conn.Msvm_VirtualSystemSettingData(
                ['ElementName', 'Notes'],
                VirtualSystemType=self._VIRTUAL_SYSTEM_TYPE_REALIZED):
            instance_notes.append((vs.ElementName, [v for v in vs.Notes if v]))

        return instance_notes

    def list_instances(self):
        """Return the names of all the instances known to Hyper-V."""
        return [v.ElementName for v in
                self._conn.Msvm_VirtualSystemSettingData(
                    ['ElementName'],
                    VirtualSystemType=self._VIRTUAL_SYSTEM_TYPE_REALIZED)]

    def _create_vm_obj(self, vs_man_svc, vm_name, notes):
        vs_data = self._conn.Msvm_VirtualSystemSettingData.new()
        vs_data.ElementName = vm_name
        vs_data.Notes = notes

        (job_path,
         vm_path,
         ret_val) = vs_man_svc.DefineSystem(ResourceSettings=[],
                                            ReferenceConfiguration=None,
                                            SystemSettings=vs_data.GetText_(1))
        job = self.check_ret_val(ret_val, job_path)
        if not vm_path and job:
            vm_path = job.associators(self._AFFECTED_JOB_ELEMENT_CLASS)[0]
        return self._get_wmi_obj(vm_path)

    def _get_vm_setting_data(self, vm):
        vmsettings = vm.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)
        # Avoid snapshots
        return [s for s in vmsettings if
                s.VirtualSystemType == self._VIRTUAL_SYSTEM_TYPE_REALIZED][0]

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
        drive.AddressOnParent = drive_addr
        #Add the cloned disk drive object to the vm.
        new_resources = self._add_virt_resource(drive, vm.path_())
        drive_path = new_resources[0]

        if drive_type == constants.IDE_DISK:
            res_sub_type = self._IDE_DISK_RES_SUB_TYPE
        elif drive_type == constants.IDE_DVD:
            res_sub_type = self._IDE_DVD_RES_SUB_TYPE

        res = self._get_new_resource_setting_data(
            res_sub_type, self._STORAGE_ALLOC_SETTING_DATA_CLASS)

        res.Parent = drive_path
        res.HostResource = [path]

        self._add_virt_resource(res, vm.path_())

    def attach_volume_to_controller(self, vm_name, controller_path, address,
                                    mounted_disk_path):
        """Attach a volume to a controller."""

        vm = self._lookup_vm_check(vm_name)

        diskdrive = self._get_new_resource_setting_data(
            self._PHYS_DISK_RES_SUB_TYPE)

        diskdrive.AddressOnParent = address
        diskdrive.Parent = controller_path
        diskdrive.HostResource = [mounted_disk_path]

        self._add_virt_resource(diskdrive, vm.path_())

    def create_scsi_controller(self, vm_name):
        """Create an iscsi controller ready to mount volumes."""
        scsicontrl = self._get_new_resource_setting_data(
            self._SCSI_RES_SUBTYPE)

        scsicontrl.VirtualSystemIdentifiers = ['{' + str(uuid.uuid4()) + '}']

        vm = self._lookup_vm_check(vm_name)
        self._add_virt_resource(scsicontrl, vm.path_())

    def _get_disk_resource_disk_path(self, disk_resource):
        return disk_resource.HostResource

    def destroy_vm(self, vm_name):
        vm = self._lookup_vm_check(vm_name)

        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        #Remove the VM. It does not destroy any associated virtual disk.
        (job_path, ret_val) = vs_man_svc.DestroySystem(vm.path_())
        self.check_ret_val(ret_val, job_path)

    def _add_virt_resource(self, res_setting_data, vm_path):
        """Adds a new resource to the VM."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        res_xml = [res_setting_data.GetText_(1)]
        (job_path,
         new_resources,
         ret_val) = vs_man_svc.AddResourceSettings(vm_path, res_xml)
        self.check_ret_val(ret_val, job_path)
        return new_resources

    def _modify_virt_resource(self, res_setting_data, vm_path):
        """Updates a VM resource."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        (job_path,
         out_res_setting_data,
         ret_val) = vs_man_svc.ModifyResourceSettings(
            ResourceSettings=[res_setting_data.GetText_(1)])
        self.check_ret_val(ret_val, job_path)

    def _remove_virt_resource(self, res_setting_data, vm_path):
        """Removes a VM resource."""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        res_path = [res_setting_data.path_()]
        (job_path, ret_val) = vs_man_svc.RemoveResourceSettings(res_path)
        self.check_ret_val(ret_val, job_path)

    def get_vm_state(self, vm_name):
        settings = self.get_vm_summary_info(vm_name)
        return settings['EnabledState']

    def take_vm_snapshot(self, vm_name):
        vm = self._lookup_vm_check(vm_name)
        vs_snap_svc = self._conn.Msvm_VirtualSystemSnapshotService()[0]

        (job_path, snp_setting_data, ret_val) = vs_snap_svc.CreateSnapshot(
            AffectedSystem=vm.path_(),
            SnapshotType=self._SNAPSHOT_FULL)
        self.check_ret_val(ret_val, job_path)

        job_wmi_path = job_path.replace('\\', '/')
        job = wmi.WMI(moniker=job_wmi_path)
        snp_setting_data = job.associators(
            wmi_result_class=self._VIRTUAL_SYSTEM_SETTING_DATA_CLASS)[0]

        return snp_setting_data.path_()

    def remove_vm_snapshot(self, snapshot_path):
        vs_snap_svc = self._conn.Msvm_VirtualSystemSnapshotService()[0]
        (job_path, ret_val) = vs_snap_svc.DestroySnapshot(snapshot_path)
        self.check_ret_val(ret_val, job_path)

    def set_nic_connection(self, vm_name, nic_name, vswitch_conn_data):
        nic_data = self._get_nic_data_by_name(nic_name)

        eth_port_data = self._get_new_setting_data(
            self._ETHERNET_PORT_ALLOCATION_SETTING_DATA_CLASS)

        eth_port_data.HostResource = [vswitch_conn_data]
        eth_port_data.Parent = nic_data.path_()

        vm = self._lookup_vm_check(vm_name)
        self._add_virt_resource(eth_port_data, vm.path_())

    def enable_vm_metrics_collection(self, vm_name):
        metric_names = [self._METRIC_AGGR_CPU_AVG]

        vm = self._lookup_vm_check(vm_name)
        metric_svc = self._conn.Msvm_MetricService()[0]
        (disks, volumes) = self._get_vm_disks(vm)
        filtered_disks = [d for d in disks if
                          d.ResourceSubType is not self._IDE_DVD_RES_SUB_TYPE]

        # enable metrics for disk.
        for disk in filtered_disks:
            self._enable_metrics(metric_svc, disk)

        for metric_name in metric_names:
            metric_def = self._conn.CIM_BaseMetricDefinition(Name=metric_name)
            if not metric_def:
                LOG.debug(_("Metric not found: %s") % metric_name)
            else:
                self._enable_metrics(metric_svc, vm, metric_def[0].path_())

    def _enable_metrics(self, metric_svc, element, definition_path=None):
        metric_svc.ControlMetrics(
            Subject=element.path_(),
            Definition=definition_path,
            MetricCollectionEnabled=self._METRIC_ENABLED)

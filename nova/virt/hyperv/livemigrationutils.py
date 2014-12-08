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

import sys

if sys.platform == 'win32':
    import wmi

from nova import exception
from nova.i18n import _
from nova.openstack.common import log as logging
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import vmutilsv2
from nova.virt.hyperv import volumeutilsv2

LOG = logging.getLogger(__name__)


class LiveMigrationUtils(object):

    def __init__(self):
        self._vmutils = vmutilsv2.VMUtilsV2()
        self._volutils = volumeutilsv2.VolumeUtilsV2()

    def _get_conn_v2(self, host='localhost'):
        try:
            return wmi.WMI(moniker='//%s/root/virtualization/v2' % host)
        except wmi.x_wmi as ex:
            LOG.exception(ex)
            if ex.com_error.hresult == -2147217394:
                msg = (_('Live migration is not supported on target host "%s"')
                       % host)
            elif ex.com_error.hresult == -2147023174:
                msg = (_('Target live migration host "%s" is unreachable')
                       % host)
            else:
                msg = _('Live migration failed: %s') % ex.message
            raise vmutils.HyperVException(msg)

    def check_live_migration_config(self):
        conn_v2 = self._get_conn_v2()
        migration_svc = conn_v2.Msvm_VirtualSystemMigrationService()[0]
        vsmssds = migration_svc.associators(
            wmi_association_class='Msvm_ElementSettingData',
            wmi_result_class='Msvm_VirtualSystemMigrationServiceSettingData')
        vsmssd = vsmssds[0]
        if not vsmssd.EnableVirtualSystemMigration:
            raise vmutils.HyperVException(
                _('Live migration is not enabled on this host'))
        if not migration_svc.MigrationServiceListenerIPAddressList:
            raise vmutils.HyperVException(
                _('Live migration networks are not configured on this host'))

    def _get_vm(self, conn_v2, vm_name):
        vms = conn_v2.Msvm_ComputerSystem(ElementName=vm_name)
        n = len(vms)
        if not n:
            raise exception.NotFound(_('VM not found: %s') % vm_name)
        elif n > 1:
            raise vmutils.HyperVException(_('Duplicate VM name found: %s')
                                          % vm_name)
        return vms[0]

    def _destroy_planned_vm(self, conn_v2_remote, planned_vm):
        LOG.debug("Destroying existing remote planned VM: %s",
                  planned_vm.ElementName)
        vs_man_svc = conn_v2_remote.Msvm_VirtualSystemManagementService()[0]
        (job_path, ret_val) = vs_man_svc.DestroySystem(planned_vm.path_())
        self._vmutils.check_ret_val(ret_val, job_path)

    def _check_existing_planned_vm(self, conn_v2_remote, vm):
        # Make sure that there's not yet a remote planned VM on the target
        # host for this VM
        planned_vms = conn_v2_remote.Msvm_PlannedComputerSystem(Name=vm.Name)
        if planned_vms:
            self._destroy_planned_vm(conn_v2_remote, planned_vms[0])

    def _create_remote_planned_vm(self, conn_v2_local, conn_v2_remote,
                                  vm, rmt_ip_addr_list, dest_host):
        # Staged
        vsmsd = conn_v2_local.query("select * from "
                                    "Msvm_VirtualSystemMigrationSettingData "
                                    "where MigrationType = 32770")[0]
        vsmsd.DestinationIPAddressList = rmt_ip_addr_list
        migration_setting_data = vsmsd.GetText_(1)

        LOG.debug("Creating remote planned VM for VM: %s",
                  vm.ElementName)
        migr_svc = conn_v2_local.Msvm_VirtualSystemMigrationService()[0]
        (job_path, ret_val) = migr_svc.MigrateVirtualSystemToHost(
            ComputerSystem=vm.path_(),
            DestinationHost=dest_host,
            MigrationSettingData=migration_setting_data)
        self._vmutils.check_ret_val(ret_val, job_path)

        return conn_v2_remote.Msvm_PlannedComputerSystem(Name=vm.Name)[0]

    def _get_physical_disk_paths(self, vm_name):
        ide_ctrl_path = self._vmutils.get_vm_ide_controller(vm_name, 0)
        ide_paths = self._vmutils.get_controller_volume_paths(ide_ctrl_path)

        scsi_ctrl_path = self._vmutils.get_vm_scsi_controller(vm_name)
        scsi_paths = self._vmutils.get_controller_volume_paths(scsi_ctrl_path)

        return dict(ide_paths.items() + scsi_paths.items())

    def _get_remote_disk_data(self, vmutils_remote, disk_paths, dest_host):
        volutils_remote = volumeutilsv2.VolumeUtilsV2(dest_host)

        disk_paths_remote = {}
        for (rasd_rel_path, disk_path) in disk_paths.items():
            target = self._volutils.get_target_from_disk_path(disk_path)
            if target:
                (target_iqn, target_lun) = target

                dev_num = volutils_remote.get_device_number_for_target(
                    target_iqn, target_lun)
                disk_path_remote = (
                    vmutils_remote.get_mounted_disk_by_drive_number(dev_num))

                disk_paths_remote[rasd_rel_path] = disk_path_remote
            else:
                LOG.debug("Could not retrieve iSCSI target "
                          "from disk path: %s", disk_path)

        return disk_paths_remote

    def _update_planned_vm_disk_resources(self, vmutils_remote, conn_v2_remote,
                                          planned_vm, vm_name,
                                          disk_paths_remote):
        vm_settings = planned_vm.associators(
            wmi_association_class='Msvm_SettingsDefineState',
            wmi_result_class='Msvm_VirtualSystemSettingData')[0]

        updated_resource_setting_data = []
        sasds = vm_settings.associators(
            wmi_association_class='Msvm_VirtualSystemSettingDataComponent')
        for sasd in sasds:
            if (sasd.ResourceType == 17 and sasd.ResourceSubType ==
                    "Microsoft:Hyper-V:Physical Disk Drive" and
                    sasd.HostResource):
                # Replace the local disk target with the correct remote one
                old_disk_path = sasd.HostResource[0]
                new_disk_path = disk_paths_remote.pop(sasd.path().RelPath)

                LOG.debug("Replacing host resource "
                          "%(old_disk_path)s with "
                          "%(new_disk_path)s on planned VM %(vm_name)s",
                          {'old_disk_path': old_disk_path,
                           'new_disk_path': new_disk_path,
                           'vm_name': vm_name})
                sasd.HostResource = [new_disk_path]
                updated_resource_setting_data.append(sasd.GetText_(1))

        LOG.debug("Updating remote planned VM disk paths for VM: %s",
                  vm_name)
        vsmsvc = conn_v2_remote.Msvm_VirtualSystemManagementService()[0]
        (res_settings, job_path, ret_val) = vsmsvc.ModifyResourceSettings(
            ResourceSettings=updated_resource_setting_data)
        vmutils_remote.check_ret_val(ret_val, job_path)

    def _get_vhd_setting_data(self, vm):
        vm_settings = vm.associators(
            wmi_association_class='Msvm_SettingsDefineState',
            wmi_result_class='Msvm_VirtualSystemSettingData')[0]

        new_resource_setting_data = []
        sasds = vm_settings.associators(
            wmi_association_class='Msvm_VirtualSystemSettingDataComponent',
            wmi_result_class='Msvm_StorageAllocationSettingData')
        for sasd in sasds:
            if (sasd.ResourceType == 31 and sasd.ResourceSubType ==
                    "Microsoft:Hyper-V:Virtual Hard Disk"):
                new_resource_setting_data.append(sasd.GetText_(1))
        return new_resource_setting_data

    def _live_migrate_vm(self, conn_v2_local, vm, planned_vm, rmt_ip_addr_list,
                         new_resource_setting_data, dest_host):
        # VirtualSystemAndStorage
        vsmsd = conn_v2_local.query("select * from "
                                    "Msvm_VirtualSystemMigrationSettingData "
                                    "where MigrationType = 32771")[0]
        vsmsd.DestinationIPAddressList = rmt_ip_addr_list
        if planned_vm:
            vsmsd.DestinationPlannedVirtualSystemId = planned_vm.Name
        migration_setting_data = vsmsd.GetText_(1)

        migr_svc = conn_v2_local.Msvm_VirtualSystemMigrationService()[0]

        LOG.debug("Starting live migration for VM: %s", vm.ElementName)
        (job_path, ret_val) = migr_svc.MigrateVirtualSystemToHost(
            ComputerSystem=vm.path_(),
            DestinationHost=dest_host,
            MigrationSettingData=migration_setting_data,
            NewResourceSettingData=new_resource_setting_data)
        self._vmutils.check_ret_val(ret_val, job_path)

    def _get_remote_ip_address_list(self, conn_v2_remote, dest_host):
        LOG.debug("Getting live migration networks for remote host: %s",
                  dest_host)
        migr_svc_rmt = conn_v2_remote.Msvm_VirtualSystemMigrationService()[0]
        return migr_svc_rmt.MigrationServiceListenerIPAddressList

    def live_migrate_vm(self, vm_name, dest_host):
        self.check_live_migration_config()

        conn_v2_local = self._get_conn_v2()
        conn_v2_remote = self._get_conn_v2(dest_host)

        vm = self._get_vm(conn_v2_local, vm_name)
        self._check_existing_planned_vm(conn_v2_remote, vm)

        rmt_ip_addr_list = self._get_remote_ip_address_list(conn_v2_remote,
                                                            dest_host)

        planned_vm = None
        disk_paths = self._get_physical_disk_paths(vm_name)
        if disk_paths:
            vmutils_remote = vmutilsv2.VMUtilsV2(dest_host)
            disk_paths_remote = self._get_remote_disk_data(vmutils_remote,
                                                           disk_paths,
                                                           dest_host)

            planned_vm = self._create_remote_planned_vm(conn_v2_local,
                                                        conn_v2_remote,
                                                        vm, rmt_ip_addr_list,
                                                        dest_host)

            self._update_planned_vm_disk_resources(vmutils_remote,
                                                   conn_v2_remote, planned_vm,
                                                   vm_name, disk_paths_remote)

        new_resource_setting_data = self._get_vhd_setting_data(vm)
        self._live_migrate_vm(conn_v2_local, vm, planned_vm, rmt_ip_addr_list,
                              new_resource_setting_data, dest_host)

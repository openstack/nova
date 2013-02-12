# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.openstack.common import log as logging
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)


class LiveMigrationUtils(object):

    def __init__(self):
        self._vmutils = vmutils.VMUtils()

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
            raise vmutils.HyperVException(_('VM not found: %s') % vm_name)
        elif n > 1:
            raise vmutils.HyperVException(_('Duplicate VM name found: %s')
                                          % vm_name)
        return vms[0]

    def live_migrate_vm(self, vm_name, dest_host):
        self.check_live_migration_config()

        # We need a v2 namespace VM object
        conn_v2_local = self._get_conn_v2()

        vm = self._get_vm(conn_v2_local, vm_name)
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
                #sasd.PoolId = ""
                new_resource_setting_data.append(sasd.GetText_(1))

        LOG.debug(_("Getting live migration networks for remote host: %s"),
                  dest_host)
        conn_v2_remote = self._get_conn_v2(dest_host)
        migr_svc_rmt = conn_v2_remote.Msvm_VirtualSystemMigrationService()[0]
        rmt_ip_addr_list = migr_svc_rmt.MigrationServiceListenerIPAddressList

        # VirtualSystemAndStorage
        vsmsd = conn_v2_local.query("select * from "
                                    "Msvm_VirtualSystemMigrationSettingData "
                                    "where MigrationType = 32771")[0]
        vsmsd.DestinationIPAddressList = rmt_ip_addr_list
        migration_setting_data = vsmsd.GetText_(1)

        migr_svc = conn_v2_local.Msvm_VirtualSystemMigrationService()[0]

        LOG.debug(_("Starting live migration for VM: %s"), vm_name)
        (job_path, ret_val) = migr_svc.MigrateVirtualSystemToHost(
            ComputerSystem=vm.path_(),
            DestinationHost=dest_host,
            MigrationSettingData=migration_setting_data,
            NewResourceSettingData=new_resource_setting_data)
        self._vmutils.check_ret_val(ret_val, job_path)

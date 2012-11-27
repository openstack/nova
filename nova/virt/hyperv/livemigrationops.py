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
Management class for live migration VM operations.
"""
import os
import sys

from nova import exception
from nova import flags
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova.virt.hyperv import baseops
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmutils

# Check needed for unit testing on Unix
if sys.platform == 'win32':
    import wmi

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class LiveMigrationOps(baseops.BaseOps):
    def __init__(self, volumeops):
        super(LiveMigrationOps, self).__init__()

        self._vmutils = vmutils.VMUtils()
        self._volumeops = volumeops

    def _check_live_migration_config(self):
        try:
            self._conn_v2
        except Exception:
            raise vmutils.HyperVException(
                _('Live migration is not supported " \
                    "by this version of Hyper-V'))

        migration_svc = self._conn_v2.Msvm_VirtualSystemMigrationService()[0]
        vsmssd = migration_svc.associators(
          wmi_association_class='Msvm_ElementSettingData',
          wmi_result_class='Msvm_VirtualSystemMigrationServiceSettingData')[0]
        if not vsmssd.EnableVirtualSystemMigration:
            raise vmutils.HyperVException(
                _('Live migration is not enabled on this host'))
        if not migration_svc.MigrationServiceListenerIPAddressList:
            raise vmutils.HyperVException(
                _('Live migration networks are not configured on this host'))

    def live_migration(self, context, instance_ref, dest, post_method,
        recover_method, block_migration=False, migrate_data=None):
        LOG.debug(_("live_migration called"), instance=instance_ref)
        instance_name = instance_ref["name"]

        try:
            self._check_live_migration_config()

            vm_name = self._vmutils.lookup(self._conn, instance_name)
            if vm_name is None:
                raise exception.InstanceNotFound(instance=instance_name)
            vm = self._conn_v2.Msvm_ComputerSystem(
                ElementName=instance_name)[0]
            vm_settings = vm.associators(
                wmi_association_class='Msvm_SettingsDefineState',
                wmi_result_class='Msvm_VirtualSystemSettingData')[0]

            new_resource_setting_data = []
            sasds = vm_settings.associators(
                wmi_association_class='Msvm_VirtualSystemSettingDataComponent',
                wmi_result_class='Msvm_StorageAllocationSettingData')
            for sasd in sasds:
                if sasd.ResourceType == 31 and \
                    sasd.ResourceSubType == \
                    "Microsoft:Hyper-V:Virtual Hard Disk":
                    #sasd.PoolId = ""
                    new_resource_setting_data.append(sasd.GetText_(1))

            LOG.debug(_("Getting live migration networks for remote "
                "host: %s"), dest)
            _conn_v2_remote = wmi.WMI(
                moniker='//' + dest + '/root/virtualization/v2')
            migration_svc_remote = \
                _conn_v2_remote.Msvm_VirtualSystemMigrationService()[0]
            remote_ip_address_list = \
                migration_svc_remote.MigrationServiceListenerIPAddressList

            # VirtualSystemAndStorage
            vsmsd = self._conn_v2.query("select * from "
                "Msvm_VirtualSystemMigrationSettingData "
                "where MigrationType = 32771")[0]
            vsmsd.DestinationIPAddressList = remote_ip_address_list
            migration_setting_data = vsmsd.GetText_(1)

            migration_svc =\
                self._conn_v2.Msvm_VirtualSystemMigrationService()[0]

            LOG.debug(_("Starting live migration for instance: %s"),
                instance_name)
            (job_path, ret_val) = migration_svc.MigrateVirtualSystemToHost(
                ComputerSystem=vm.path_(),
                DestinationHost=dest,
                MigrationSettingData=migration_setting_data,
                NewResourceSettingData=new_resource_setting_data)
            if ret_val == constants.WMI_JOB_STATUS_STARTED:
                success = self._vmutils.check_job_status(job_path)
            else:
                success = (ret_val == 0)
            if not success:
                raise vmutils.HyperVException(
                    _('Failed to live migrate VM %s') % instance_name)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug(_("Calling live migration recover_method "
                    "for instance: %s"), instance_name)
                recover_method(context, instance_ref, dest, block_migration)

        LOG.debug(_("Calling live migration post_method for instance: %s"),
            instance_name)
        post_method(context, instance_ref, dest, block_migration)

    def pre_live_migration(self, context, instance, block_device_info,
        network_info):
        LOG.debug(_("pre_live_migration called"), instance=instance)
        self._check_live_migration_config()

        if FLAGS.use_cow_images:
            ebs_root = self._volumeops.volume_in_mapping(
                self._volumeops.get_default_root_device(),
                block_device_info)
            if not ebs_root:
                base_vhd_path = self._vmutils.get_base_vhd_path(
                    instance["image_ref"])
                if not os.path.exists(base_vhd_path):
                    self._vmutils.fetch_image(base_vhd_path, context,
                        instance["image_ref"],
                        instance["user_id"],
                        instance["project_id"])

    def post_live_migration_at_destination(self, ctxt, instance_ref,
        network_info, block_migration):
        LOG.debug(_("post_live_migration_at_destination called"),
            instance=instance_ref)

    def compare_cpu(self, cpu_info):
        LOG.debug(_("compare_cpu called %s"), cpu_info)
        return True

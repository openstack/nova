# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Pedro Navarro Perez
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
Management class for Storage-related functions (attach, detach, etc).
"""
import time

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeutils
from nova.virt.hyperv import volumeutilsv2

LOG = logging.getLogger(__name__)

hyper_volumeops_opts = [
    cfg.IntOpt('hyperv_attaching_volume_retry_count',
               default=10,
               help='The number of times we retry on attaching volume '),
    cfg.IntOpt('hyperv_wait_between_attach_retry',
               default=5,
               help='The seconds to wait between an volume '
               'attachment attempt'),
    cfg.BoolOpt('force_volumeutils_v1',
                default=False,
                help='Force volumeutils v1'),
]

CONF = cfg.CONF
CONF.register_opts(hyper_volumeops_opts)
CONF.import_opt('my_ip', 'nova.netconf')


class VolumeOps(object):
    """
    Management class for Volume-related tasks
    """

    def __init__(self):
        self._hostutils = hostutils.HostUtils()
        self._vmutils = vmutils.VMUtils()
        self._volutils = self._get_volume_utils()
        self._initiator = None
        self._default_root_device = 'vda'

    def _get_volume_utils(self):
        if(not CONF.force_volumeutils_v1 and
           self._hostutils.get_windows_version() >= 6.2):
            return volumeutilsv2.VolumeUtilsV2()
        else:
            return volumeutils.VolumeUtils()

    def ebs_root_in_block_devices(self, block_device_info):
        return self._volutils.volume_in_mapping(self._default_root_device,
                                                block_device_info)

    def attach_volumes(self, block_device_info, instance_name, ebs_root):
        mapping = driver.block_device_info_get_mapping(block_device_info)

        if ebs_root:
            self.attach_volume(mapping[0]['connection_info'],
                               instance_name, True)
            mapping = mapping[1:]
        for vol in mapping:
            self.attach_volume(vol['connection_info'], instance_name)

    def attach_volume(self, connection_info, instance_name, ebs_root=False):
        """
        Attach a volume to the SCSI controller or to the IDE controller if
        ebs_root is True
        """
        LOG.debug(_("Attach_volume: %(connection_info)s to %(instance_name)s")
                  % locals())
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        self._volutils.login_storage_target(target_lun, target_iqn,
                                            target_portal)
        try:
            #Getting the mounted disk
            mounted_disk_path = self._get_mounted_disk_from_lun(target_iqn,
                                                                target_lun)

            if ebs_root:
                #Find the IDE controller for the vm.
                ctrller_path = self._vmutils.get_vm_ide_controller(
                    instance_name, 0)
                #Attaching to the first slot
                slot = 0
            else:
                #Find the SCSI controller for the vm
                ctrller_path = self._vmutils.get_vm_iscsi_controller(
                    instance_name)
                slot = self._get_free_controller_slot(ctrller_path)

            self._vmutils.attach_volume_to_controller(instance_name,
                                                      ctrller_path,
                                                      slot,
                                                      mounted_disk_path)
        except Exception as exn:
            LOG.exception(_('Attach volume failed: %s'), exn)
            self._volutils.logout_storage_target(target_iqn)
            raise vmutils.HyperVException(_('Unable to attach volume '
                                            'to instance %s') % instance_name)

    def _get_free_controller_slot(self, scsi_controller_path):
        #Slots starts from 0, so the lenght of the disks gives us the free slot
        return self._vmutils.get_attached_disks_count(scsi_controller_path)

    def detach_volumes(self, block_device_info, instance_name):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            self.detach_volume(vol['connection_info'], instance_name)

    def detach_volume(self, connection_info, instance_name):
        """Dettach a volume to the SCSI controller."""
        LOG.debug(_("Detach_volume: %(connection_info)s "
                    "from %(instance_name)s") % locals())
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        #Getting the mounted disk
        mounted_disk_path = self._get_mounted_disk_from_lun(target_iqn,
                                                            target_lun)

        LOG.debug(_("Detaching physical disk from instance: %s"),
                  mounted_disk_path)
        self._vmutils.detach_vm_disk(instance_name, mounted_disk_path)

        #Sending logout
        self._volutils.logout_storage_target(target_iqn)

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = self._volutils.get_iscsi_initiator()
            if not self._initiator:
                LOG.warn(_('Could not determine iscsi initiator name'),
                         instance=instance)
        return {
            'ip': CONF.my_ip,
            'initiator': self._initiator,
        }

    def _get_mounted_disk_from_lun(self, target_iqn, target_lun):
        device_number = self._volutils.get_device_number_for_target(target_iqn,
                                                                    target_lun)
        if device_number is None:
            raise vmutils.HyperVException(_('Unable to find a mounted '
                                            'disk for target_iqn: %s')
                                          % target_iqn)
        LOG.debug(_('Device number: %(device_number)s, '
                    'target lun: %(target_lun)s') % locals())
        #Finding Mounted disk drive
        for i in range(1, CONF.hyperv_attaching_volume_retry_count):
            mounted_disk_path = self._vmutils.get_mounted_disk_by_drive_number(
                device_number)
            if mounted_disk_path:
                break
            time.sleep(CONF.hyperv_wait_between_attach_retry)

        if not mounted_disk_path:
            raise vmutils.HyperVException(_('Unable to find a mounted disk '
                                            'for target_iqn: %s')
                                          % target_iqn)
        return mounted_disk_path

    def disconnect_volume(self, physical_drive_path):
        #Get the session_id of the ISCSI connection
        session_id = self._volutils.get_session_id_from_mounted_disk(
            physical_drive_path)
        #Logging out the target
        self._volutils.execute_log_out(session_id)

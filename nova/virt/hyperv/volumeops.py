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

from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import constants
from nova.virt.hyperv import utilsfactory
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)

hyper_volumeops_opts = [
    cfg.IntOpt('volume_attach_retry_count',
               default=10,
               help='The number of times to retry to attach a volume'),
    cfg.IntOpt('volume_attach_retry_interval',
               default=5,
               help='Interval between volume attachment attempts, in seconds'),
    cfg.IntOpt('mounted_disk_query_retry_count',
               default=10,
               help='The number of times to retry checking for a disk mounted '
                    'via iSCSI.'),
    cfg.IntOpt('mounted_disk_query_retry_interval',
               default=5,
               help='Interval between checks for a mounted iSCSI '
                    'disk, in seconds.'),
]

CONF = cfg.CONF
CONF.register_opts(hyper_volumeops_opts, 'hyperv')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')


class VolumeOps(object):
    """Management class for Volume-related tasks
    """

    def __init__(self):
        self._hostutils = utilsfactory.get_hostutils()
        self._vmutils = utilsfactory.get_vmutils()
        self._volutils = utilsfactory.get_volumeutils()
        self._initiator = None
        self._default_root_device = 'vda'

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

    def login_storage_targets(self, block_device_info):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            self._login_storage_target(vol['connection_info'])

    def _login_storage_target(self, connection_info):
        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']
        target_portal = data['target_portal']
        # Check if we already logged in
        if self._volutils.get_device_number_for_target(target_iqn, target_lun):
            LOG.debug(_("Already logged in on storage target. No need to "
                        "login. Portal: %(target_portal)s, "
                        "IQN: %(target_iqn)s, LUN: %(target_lun)s"),
                      {'target_portal': target_portal,
                       'target_iqn': target_iqn, 'target_lun': target_lun})
        else:
            LOG.debug(_("Logging in on storage target. Portal: "
                        "%(target_portal)s, IQN: %(target_iqn)s, "
                        "LUN: %(target_lun)s"),
                      {'target_portal': target_portal,
                       'target_iqn': target_iqn, 'target_lun': target_lun})
            self._volutils.login_storage_target(target_lun, target_iqn,
                                                target_portal)
            # Wait for the target to be mounted
            self._get_mounted_disk_from_lun(target_iqn, target_lun, True)

    def attach_volume(self, connection_info, instance_name, ebs_root=False):
        """Attach a volume to the SCSI controller or to the IDE controller if
        ebs_root is True
        """
        target_iqn = None
        LOG.debug(_("Attach_volume: %(connection_info)s to %(instance_name)s"),
                  {'connection_info': connection_info,
                   'instance_name': instance_name})
        try:
            self._login_storage_target(connection_info)

            data = connection_info['data']
            target_lun = data['target_lun']
            target_iqn = data['target_iqn']

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
                ctrller_path = self._vmutils.get_vm_scsi_controller(
                    instance_name)
                slot = self._get_free_controller_slot(ctrller_path)

            self._vmutils.attach_volume_to_controller(instance_name,
                                                      ctrller_path,
                                                      slot,
                                                      mounted_disk_path)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_('Unable to attach volume to instance %s'),
                          instance_name)
                if target_iqn:
                    self._volutils.logout_storage_target(target_iqn)

    def _get_free_controller_slot(self, scsi_controller_path):
        attached_disks = self._vmutils.get_attached_disks(scsi_controller_path)
        used_slots = [int(disk.AddressOnParent) for disk in attached_disks]

        for slot in xrange(constants.SCSI_CONTROLLER_SLOTS_NUMBER):
            if slot not in used_slots:
                return slot
        raise vmutils.HyperVException("Exceeded the maximum number of slots")

    def detach_volumes(self, block_device_info, instance_name):
        mapping = driver.block_device_info_get_mapping(block_device_info)
        for vol in mapping:
            self.detach_volume(vol['connection_info'], instance_name)

    def logout_storage_target(self, target_iqn):
        LOG.debug(_("Logging off storage target %s"), target_iqn)
        self._volutils.logout_storage_target(target_iqn)

    def detach_volume(self, connection_info, instance_name):
        """Detach a volume to the SCSI controller."""
        LOG.debug(_("Detach_volume: %(connection_info)s "
                    "from %(instance_name)s"),
                  {'connection_info': connection_info,
                   'instance_name': instance_name})

        data = connection_info['data']
        target_lun = data['target_lun']
        target_iqn = data['target_iqn']

        #Getting the mounted disk
        mounted_disk_path = self._get_mounted_disk_from_lun(target_iqn,
                                                            target_lun)

        LOG.debug(_("Detaching physical disk from instance: %s"),
                  mounted_disk_path)
        self._vmutils.detach_vm_disk(instance_name, mounted_disk_path)

        self.logout_storage_target(target_iqn)

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = self._volutils.get_iscsi_initiator()
            if not self._initiator:
                LOG.warn(_('Could not determine iscsi initiator name'),
                         instance=instance)
        return {
            'ip': CONF.my_ip,
            'host': CONF.host,
            'initiator': self._initiator,
        }

    def _get_mounted_disk_from_lun(self, target_iqn, target_lun,
                                   wait_for_device=False):
        # The WMI query in get_device_number_for_target can incorrectly
        # return no data when the system is under load.  This issue can
        # be avoided by adding a retry.
        for i in xrange(CONF.hyperv.mounted_disk_query_retry_count):
            device_number = self._volutils.get_device_number_for_target(
                target_iqn, target_lun)
            if device_number in (None, -1):
                attempt = i + 1
                LOG.debug(_('Attempt %d to get device_number '
                          'from get_device_number_for_target failed. '
                          'Retrying...') % attempt)
                time.sleep(CONF.hyperv.mounted_disk_query_retry_interval)
            else:
                break

        if device_number in (None, -1):
            raise exception.NotFound(_('Unable to find a mounted disk for '
                                       'target_iqn: %s') % target_iqn)
        LOG.debug(_('Device number: %(device_number)s, '
                    'target lun: %(target_lun)s'),
                  {'device_number': device_number, 'target_lun': target_lun})
        #Finding Mounted disk drive
        for i in range(0, CONF.hyperv.volume_attach_retry_count):
            mounted_disk_path = self._vmutils.get_mounted_disk_by_drive_number(
                device_number)
            if mounted_disk_path or not wait_for_device:
                break
            time.sleep(CONF.hyperv.volume_attach_retry_interval)

        if not mounted_disk_path:
            raise exception.NotFound(_('Unable to find a mounted disk '
                                       'for target_iqn: %s') % target_iqn)
        return mounted_disk_path

    def disconnect_volume(self, physical_drive_path):
        #Get the session_id of the ISCSI connection
        session_id = self._volutils.get_session_id_from_mounted_disk(
            physical_drive_path)
        #Logging out the target
        self._volutils.execute_log_out(session_id)

    def get_target_from_disk_path(self, physical_drive_path):
        return self._volutils.get_target_from_disk_path(physical_drive_path)

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

from nova import exception
from nova import log as logging
from nova.virt.xenapi.vm_utils import VMHelper
from nova.virt.xenapi.volume_utils import VolumeHelper
from nova.virt.xenapi.volume_utils import StorageError


LOG = logging.getLogger("nova.virt.xenapi.volumeops")


class VolumeOps(object):
    """
    Management class for Volume-related tasks
    """

    def __init__(self, session):
        self.XenAPI = session.get_imported_xenapi()
        self._session = session
        # Load XenAPI module in the helper classes respectively
        VolumeHelper.XenAPI = self.XenAPI
        VMHelper.XenAPI = self.XenAPI

    def attach_volume(self, instance_name, device_path, mountpoint):
        """Attach volume storage to VM instance"""
        # Before we start, check that the VM exists
        vm_ref = VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        # NOTE: No Resource Pool concept so far
        LOG.debug(_("Attach_volume: %(instance_name)s, %(device_path)s,"
                " %(mountpoint)s") % locals())
        # Create the iSCSI SR, and the PDB through which hosts access SRs.
        # But first, retrieve target info, like Host, IQN, LUN and SCSIID
        vol_rec = VolumeHelper.parse_volume_info(device_path, mountpoint)
        label = 'SR-%s' % vol_rec['volumeId']
        description = 'Disk-for:%s' % instance_name
        # Create SR
        sr_ref = VolumeHelper.create_iscsi_storage(self._session,
                                                         vol_rec,
                                                         label,
                                                         description)
        # Introduce VDI  and attach VBD to VM
        try:
            vdi_ref = VolumeHelper.introduce_vdi(self._session, sr_ref)
        except StorageError, exc:
            LOG.exception(exc)
            VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
            raise Exception(_('Unable to create VDI on SR %(sr_ref)s for'
                    ' instance %(instance_name)s') % locals())
        else:
            try:
                vbd_ref = VMHelper.create_vbd(self._session,
                                                    vm_ref, vdi_ref,
                                                    vol_rec['deviceNumber'],
                                                    False)
            except self.XenAPI.Failure, exc:
                LOG.exception(exc)
                VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
                raise Exception(_('Unable to use SR %(sr_ref)s for'
                        ' instance %(instance_name)s') % locals())
            else:
                try:
                    task = self._session.call_xenapi('Async.VBD.plug',
                                                           vbd_ref)
                    self._session.wait_for_task(task, vol_rec['deviceNumber'])
                except self.XenAPI.Failure, exc:
                    LOG.exception(exc)
                    VolumeHelper.destroy_iscsi_storage(self._session,
                                                             sr_ref)
                    raise Exception(_('Unable to attach volume to instance %s')
                                    % instance_name)
        LOG.info(_('Mountpoint %(mountpoint)s attached to'
                ' instance %(instance_name)s') % locals())

    def detach_volume(self, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        # Before we start, check that the VM exists
        vm_ref = VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        # Detach VBD from VM
        LOG.debug(_("Detach_volume: %(instance_name)s, %(mountpoint)s")
                % locals())
        device_number = VolumeHelper.mountpoint_to_number(mountpoint)
        try:
            vbd_ref = VMHelper.find_vbd_by_number(self._session,
                                                        vm_ref, device_number)
        except StorageError, exc:
            LOG.exception(exc)
            raise Exception(_('Unable to locate volume %s') % mountpoint)
        else:
            try:
                sr_ref = VolumeHelper.find_sr_from_vbd(self._session,
                                                             vbd_ref)
                VMHelper.unplug_vbd(self._session, vbd_ref)
            except StorageError, exc:
                LOG.exception(exc)
                raise Exception(_('Unable to detach volume %s') % mountpoint)
            try:
                VMHelper.destroy_vbd(self._session, vbd_ref)
            except StorageError, exc:
                LOG.exception(exc)
        # Forget SR
        VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
        LOG.info(_('Mountpoint %(mountpoint)s detached from'
                ' instance %(instance_name)s') % locals())

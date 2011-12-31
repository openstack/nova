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

    def create_volume_for_sm(self, volume, sr_uuid):
        LOG.debug("Creating volume for Storage Manager")

        sm_vol_rec = {}
        try:
            sr_ref = self._session.call_xenapi("SR.get_by_uuid", sr_uuid)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
            raise StorageError(_('Unable to get SR using uuid'))
        #Create VDI
        label = 'vol-' + hex(volume['id'])[:-1]
        # size presented to xenapi is in bytes, while euca api is in GB
        vdi_size = volume['size'] * 1024 * 1024 * 1024
        vdi_ref = VMHelper.create_vdi(self._session, sr_ref, label, vdi_size,
                                      False)
        vdi_rec = self._session.call_xenapi("VDI.get_record", vdi_ref)
        sm_vol_rec['vdi_uuid'] = vdi_rec['uuid']
        return sm_vol_rec

    def delete_volume_for_sm(self, vdi_uuid):
        vdi_ref = self._session.call_xenapi("VDI.get_by_uuid", vdi_uuid)
        if vdi_ref is None:
            raise exception.Error(_('Could not find VDI ref'))

        try:
            self._session.call_xenapi("VDI.destroy", vdi_ref)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
            raise StorageError(_('Error destroying VDI'))

    def create_sr(self, label, params):
        LOG.debug(_("Creating SR %s") % label)
        sr_ref = VolumeHelper.create_sr(self._session, label, params)
        if sr_ref is None:
            raise exception.Error(_('Could not create SR'))
        sr_rec = self._session.call_xenapi("SR.get_record", sr_ref)
        if sr_rec is None:
            raise exception.Error(_('Could not retrieve SR record'))
        return sr_rec['uuid']

    # Checks if sr has already been introduced to this host
    def introduce_sr(self, sr_uuid, label, params):
        LOG.debug(_("Introducing SR %s") % label)
        sr_ref = VolumeHelper.find_sr_by_uuid(self._session, sr_uuid)
        if sr_ref:
            LOG.debug(_('SR found in xapi database. No need to introduce'))
            return sr_ref
        sr_ref = VolumeHelper.introduce_sr(self._session, sr_uuid, label,
                                           params)
        if sr_ref is None:
            raise exception.Error(_('Could not introduce SR'))
        return sr_ref

    def is_sr_on_host(self, sr_uuid):
        LOG.debug(_('Checking for SR %s') % sr_uuid)
        sr_ref = VolumeHelper.find_sr_by_uuid(self._session, sr_uuid)
        if sr_ref:
            return True
        return False

    # Checks if sr has been introduced
    def forget_sr(self, sr_uuid):
        sr_ref = VolumeHelper.find_sr_by_uuid(self._session, sr_uuid)
        if sr_ref is None:
            LOG.INFO(_('SR %s not found in the xapi database') % sr_uuid)
            return
        try:
            VolumeHelper.forget_sr(self._session, sr_uuid)
        except StorageError, exc:
            LOG.exception(exc)
            raise exception.Error(_('Could not forget SR'))

    def attach_volume(self, connection_info, instance_name, mountpoint):
        """Attach volume storage to VM instance"""
        # Before we start, check that the VM exists
        vm_ref = VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise exception.InstanceNotFound(instance_id=instance_name)
        # NOTE: No Resource Pool concept so far
        LOG.debug(_("Attach_volume: %(connection_info)s, %(instance_name)s,"
                " %(mountpoint)s") % locals())
        driver_type = connection_info['driver_volume_type']
        if driver_type not in ['iscsi', 'xensm']:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

        data = connection_info['data']
        if 'name_label' not in data:
            label = 'tempSR-%s' % data['volume_id']
        else:
            label = data['name_label']
            del data['name_label']

        if 'name_description' not in data:
            desc = 'Disk-for:%s' % instance_name
        else:
            desc = data['name_description']

        LOG.debug(connection_info)
        sr_params = {}
        if u'sr_uuid' not in data:
            sr_params = VolumeHelper.parse_volume_info(connection_info,
                                                       mountpoint)
            uuid = "FA15E-D15C-" + str(sr_params['id'])
            sr_params['sr_type'] = 'iscsi'
        else:
            uuid = data['sr_uuid']
            for k in data['introduce_sr_keys']:
                sr_params[k] = data[k]

        sr_params['name_description'] = desc

        # Introduce SR
        try:
            sr_ref = self.introduce_sr(uuid, label, sr_params)
            LOG.debug(_('Introduced %(label)s as %(sr_ref)s.') % locals())
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
            raise StorageError(_('Unable to introduce Storage Repository'))

        if 'vdi_uuid' in data:
            vdi_uuid = data['vdi_uuid']
        else:
            vdi_uuid = None

        # Introduce VDI  and attach VBD to VM
        try:
            vdi_ref = VolumeHelper.introduce_vdi(self._session, sr_ref,
                                                 vdi_uuid)
        except StorageError, exc:
            LOG.exception(exc)
            self.forget_sr(uuid)
            raise Exception(_('Unable to create VDI on SR %(sr_ref)s for'
                    ' instance %(instance_name)s') % locals())

        dev_number = VolumeHelper.mountpoint_to_number(mountpoint)
        try:
            vbd_ref = VolumeHelper.create_vbd(self._session,
                                              vm_ref,
                                              vdi_ref,
                                              dev_number,
                                              False)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
            self.forget_sr(uuid)
            raise Exception(_('Unable to use SR %(sr_ref)s for'
                              ' instance %(instance_name)s') % locals())

        try:
            self._session.call_xenapi("VBD.plug", vbd_ref)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
            self.forget_sr(uuid)
            raise Exception(_('Unable to attach volume to instance %s')
                            % instance_name)

        LOG.info(_('Mountpoint %(mountpoint)s attached to'
                ' instance %(instance_name)s') % locals())

    def detach_volume(self, connection_info, instance_name, mountpoint):
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
            raise Exception(_('Unable to destroy vbd %s') % mountpoint)

        # Forget SR only if no other volumes on this host are using it
        try:
            VolumeHelper.purge_sr(self._session, sr_ref)
        except StorageError, exc:
            LOG.exception(exc)
            raise Exception(_('Error purging SR %s') % sr_ref)

        LOG.info(_('Mountpoint %(mountpoint)s detached from'
                ' instance %(instance_name)s') % locals())

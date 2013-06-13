# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2013 OpenStack Foundation
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
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils


LOG = logging.getLogger(__name__)


class VolumeOps(object):
    """
    Management class for Volume-related tasks
    """

    def __init__(self, session):
        self._session = session

    def attach_volume(self, connection_info, instance_name, mountpoint,
                      hotplug=True):
        """
        Attach volume storage to VM instance.
        """

        # NOTE: No Resource Pool concept so far
        LOG.debug(_('Attach_volume: %(connection_info)s, %(instance_name)s,'
                    '" %(mountpoint)s'),
                  {'connection_info': connection_info,
                   'instance_name': instance_name,
                   'mountpoint': mountpoint})

        dev_number = volume_utils.get_device_number(mountpoint)
        vm_ref = vm_utils.vm_ref_or_raise(self._session, instance_name)

        sr_uuid, vdi_uuid = self._connect_volume(connection_info, dev_number,
                                                 instance_name, vm_ref,
                                                 hotplug=hotplug)

        LOG.info(_('Mountpoint %(mountpoint)s attached to'
                   ' instance %(instance_name)s'),
                 {'instance_name': instance_name, 'mountpoint': mountpoint})

        return (sr_uuid, vdi_uuid)

    def connect_volume(self, connection_info):
        """
        Attach volume storage to the hypervisor without attaching to a VM

        Used to attach the just the SR - e.g. for during live migration
        """

        # NOTE: No Resource Pool concept so far
        LOG.debug(_("Connect_volume: %s"), connection_info)

        sr_uuid, vdi_uuid = self._connect_volume(connection_info,
                                                 None, None, None, False)

        return (sr_uuid, vdi_uuid)

    def _connect_volume(self, connection_info, dev_number=None,
                        instance_name=None, vm_ref=None, hotplug=True):
        driver_type = connection_info['driver_volume_type']
        if driver_type not in ['iscsi', 'xensm']:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

        connection_data = connection_info['data']

        sr_uuid, sr_label, sr_params = volume_utils.parse_sr_info(
                connection_data, 'Disk-for:%s' % instance_name)

        # Introduce SR if not already present
        sr_ref = volume_utils.find_sr_by_uuid(self._session, sr_uuid)
        if not sr_ref:
            sr_ref = volume_utils.introduce_sr(
                    self._session, sr_uuid, sr_label, sr_params)

        try:
            # Introduce VDI
            if 'vdi_uuid' in connection_data:
                vdi_ref = volume_utils.introduce_vdi(
                        self._session, sr_ref,
                        vdi_uuid=connection_data['vdi_uuid'])
            elif 'target_lun' in connection_data:
                vdi_ref = volume_utils.introduce_vdi(
                        self._session, sr_ref,
                        target_lun=connection_data['target_lun'])
            else:
                # NOTE(sirp): This will introduce the first VDI in the SR
                vdi_ref = volume_utils.introduce_vdi(self._session, sr_ref)

            # Attach
            if vm_ref:
                vbd_ref = vm_utils.create_vbd(self._session, vm_ref, vdi_ref,
                                              dev_number, bootable=False,
                                              osvol=True)

                running = not vm_utils.is_vm_shutdown(self._session, vm_ref)
                if hotplug and running:
                    self._session.call_xenapi("VBD.plug", vbd_ref)

            vdi_uuid = self._session.call_xenapi("VDI.get_uuid", vdi_ref)
            return (sr_uuid, vdi_uuid)
        except Exception:
            with excutils.save_and_reraise_exception():
                # NOTE(sirp): Forgetting the SR will have the effect of
                # cleaning up the VDI and VBD records, so no need to handle
                # that explicitly.
                volume_utils.forget_sr(self._session, sr_ref)

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Detach volume storage to VM instance."""
        LOG.debug(_("Detach_volume: %(instance_name)s, %(mountpoint)s"),
                  {'instance_name': instance_name, 'mountpoint': mountpoint})

        device_number = volume_utils.get_device_number(mountpoint)
        vm_ref = vm_utils.vm_ref_or_raise(self._session, instance_name)
        try:
            vbd_ref = vm_utils.find_vbd_by_number(
                    self._session, vm_ref, device_number)
        except volume_utils.StorageError:
            # NOTE(sirp): If we don't find the VBD then it must have been
            # detached previously.
            LOG.warn(_('Skipping detach because VBD for %s was'
                       ' not found'), instance_name)
            return

        # Unplug VBD if we're NOT shutdown
        unplug = not vm_utils.is_vm_shutdown(self._session, vm_ref)
        self._detach_vbd(vbd_ref, unplug=unplug)

        LOG.info(_('Mountpoint %(mountpoint)s detached from instance'
                   ' %(instance_name)s'),
                 {'instance_name': instance_name, 'mountpoint': mountpoint})

    def _get_all_volume_vbd_refs(self, vm_ref):
        """Return VBD refs for all Nova/Cinder volumes."""
        vbd_refs = self._session.call_xenapi("VM.get_VBDs", vm_ref)
        for vbd_ref in vbd_refs:
            other_config = self._session.call_xenapi(
                    "VBD.get_other_config", vbd_ref)
            if other_config.get('osvol'):
                yield vbd_ref

    def _detach_vbd(self, vbd_ref, unplug=False):
        if unplug:
            vm_utils.unplug_vbd(self._session, vbd_ref)

        sr_ref = volume_utils.find_sr_from_vbd(self._session, vbd_ref)
        vm_utils.destroy_vbd(self._session, vbd_ref)

        # Forget SR only if not in use
        volume_utils.purge_sr(self._session, sr_ref)

    def detach_all(self, vm_ref):
        """Detach any external nova/cinder volumes and purge the SRs."""
        # Generally speaking, detach_all will be called with VM already
        # shutdown; however if it's still running, we can still perform the
        # operation by unplugging the VBD first.
        unplug = not vm_utils.is_vm_shutdown(self._session, vm_ref)

        vbd_refs = self._get_all_volume_vbd_refs(vm_ref)
        for vbd_ref in vbd_refs:
            self._detach_vbd(vbd_ref, unplug=unplug)

    def find_bad_volumes(self, vm_ref):
        """Find any volumes with their connection severed.

        Certain VM operations (e.g. `VM.start`, `VM.reboot`, etc.) will not
        work when a VBD is present that points to a non-working volume. To work
        around this, we scan for non-working volumes and detach them before
        retrying a failed operation.
        """
        bad_devices = []
        vbd_refs = self._get_all_volume_vbd_refs(vm_ref)
        for vbd_ref in vbd_refs:
            sr_ref = volume_utils.find_sr_from_vbd(self._session, vbd_ref)

            try:
                # TODO(sirp): bug1152401 This relies on a 120 sec timeout
                # within XenServer, update this to fail-fast when this is fixed
                # upstream
                self._session.call_xenapi("SR.scan", sr_ref)
            except self._session.XenAPI.Failure as exc:
                if exc.details[0] == 'SR_BACKEND_FAILURE_40':
                    vbd_rec = vbd_rec = self._session.call_xenapi(
                            "VBD.get_record", vbd_ref)
                    bad_devices.append('/dev/%s' % vbd_rec['device'])
                else:
                    raise

        return bad_devices

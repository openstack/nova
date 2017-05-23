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

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

from nova import exception
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils


LOG = logging.getLogger(__name__)


class VolumeOps(object):
    """Management class for Volume-related tasks."""

    def __init__(self, session):
        self._session = session

    def attach_volume(self, connection_info, instance_name, mountpoint,
                      hotplug=True):
        """Attach volume to VM instance."""
        vm_ref = vm_utils.vm_ref_or_raise(self._session, instance_name)
        return self._attach_volume(connection_info, vm_ref,
                                   instance_name, mountpoint, hotplug)

    def connect_volume(self, connection_info):
        """Attach volume to hypervisor, but not the VM."""
        return self._attach_volume(connection_info)

    def _attach_volume(self, connection_info, vm_ref=None, instance_name=None,
                       dev_number=None, hotplug=False):

        self._check_is_supported_driver_type(connection_info)

        connection_data = connection_info['data']
        sr_ref, sr_uuid = self._connect_to_volume_provider(connection_data,
                                                           instance_name)
        try:
            vdi_ref = self._connect_hypervisor_to_volume(sr_ref,
                                                         connection_data)
            vdi_uuid = self._session.VDI.get_uuid(vdi_ref)
            LOG.info('Connected volume (vdi_uuid): %s', vdi_uuid)

            if vm_ref:
                self._attach_volume_to_vm(vdi_ref, vm_ref, instance_name,
                                          dev_number, hotplug)

            return (sr_uuid, vdi_uuid)
        except Exception:
            with excutils.save_and_reraise_exception():
                # NOTE(sirp): Forgetting the SR will have the effect of
                # cleaning up the VDI and VBD records, so no need to handle
                # that explicitly.
                volume_utils.forget_sr(self._session, sr_ref)

    def _check_is_supported_driver_type(self, connection_info):
        driver_type = connection_info['driver_volume_type']
        if driver_type not in ['iscsi', 'xensm']:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

    def _connect_to_volume_provider(self, connection_data, instance_name):
        sr_uuid, sr_label, sr_params = volume_utils.parse_sr_info(
                connection_data, 'Disk-for:%s' % instance_name)
        sr_ref = volume_utils.find_sr_by_uuid(self._session, sr_uuid)
        if not sr_ref:
            # introduce SR because not already present
            sr_ref = volume_utils.introduce_sr(
                    self._session, sr_uuid, sr_label, sr_params)
        return (sr_ref, sr_uuid)

    def _connect_hypervisor_to_volume(self, sr_ref, connection_data):
        # connection_data can have credentials in it so make sure to scrub
        # those before logging.
        LOG.debug("Connect volume to hypervisor: %s",
                  strutils.mask_password(connection_data))
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

        return vdi_ref

    def _attach_volume_to_vm(self, vdi_ref, vm_ref, instance_name, mountpoint,
                             hotplug):
        LOG.debug('Attach_volume vdi: %(vdi_ref)s vm: %(vm_ref)s',
                  {'vdi_ref': vdi_ref, 'vm_ref': vm_ref})

        dev_number = volume_utils.get_device_number(mountpoint)

        # osvol is added to the vbd so we can spot which vbds are volumes
        vbd_ref = vm_utils.create_vbd(self._session, vm_ref, vdi_ref,
                                      dev_number, bootable=False,
                                      osvol=True)
        if hotplug:
            # NOTE(johngarbutt) can only call VBD.plug on a running vm
            running = not vm_utils.is_vm_shutdown(self._session, vm_ref)
            if running:
                LOG.debug("Plugging VBD: %s", vbd_ref)
                self._session.VBD.plug(vbd_ref, vm_ref)

        LOG.info('Dev %(dev_number)s attached to'
                 ' instance %(instance_name)s',
                 {'instance_name': instance_name, 'dev_number': dev_number})

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Detach volume storage to VM instance."""
        LOG.debug("Detach_volume: %(instance_name)s, %(mountpoint)s",
                  {'instance_name': instance_name, 'mountpoint': mountpoint})

        vm_ref = vm_utils.vm_ref_or_raise(self._session, instance_name)

        device_number = volume_utils.get_device_number(mountpoint)
        vbd_ref = volume_utils.find_vbd_by_number(self._session, vm_ref,
                                                  device_number)

        if vbd_ref is None:
            # NOTE(sirp): If we don't find the VBD then it must have been
            # detached previously.
            LOG.warning('Skipping detach because VBD for %s was not found',
                        instance_name)
        else:
            self._detach_vbds_and_srs(vm_ref, [vbd_ref])
            LOG.info('Mountpoint %(mountpoint)s detached from instance'
                     ' %(instance_name)s',
                     {'instance_name': instance_name,
                      'mountpoint': mountpoint})

    def _detach_vbds_and_srs(self, vm_ref, vbd_refs):
        is_vm_shutdown = vm_utils.is_vm_shutdown(self._session, vm_ref)

        for vbd_ref in vbd_refs:
            # find sr before we destroy the vbd
            sr_ref = volume_utils.find_sr_from_vbd(self._session, vbd_ref)

            if not is_vm_shutdown:
                vm_utils.unplug_vbd(self._session, vbd_ref, vm_ref)

            vm_utils.destroy_vbd(self._session, vbd_ref)
            # Forget (i.e. disconnect) SR only if not in use
            volume_utils.purge_sr(self._session, sr_ref)

    def detach_all(self, vm_ref):
        """Detach all cinder volumes."""
        vbd_refs = self._get_all_volume_vbd_refs(vm_ref)
        if vbd_refs:
            self._detach_vbds_and_srs(vm_ref, vbd_refs)

    def _get_all_volume_vbd_refs(self, vm_ref):
        """Return VBD refs for all Nova/Cinder volumes."""
        vbd_refs = self._session.VM.get_VBDs(vm_ref)
        for vbd_ref in vbd_refs:
            other_config = self._session.VBD.get_other_config(vbd_ref)
            if other_config.get('osvol'):
                yield vbd_ref

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
                self._session.SR.scan(sr_ref)
            except self._session.XenAPI.Failure as exc:
                if exc.details[0] == 'SR_BACKEND_FAILURE_40':
                    device = self._session.VBD.get_device(vbd_ref)
                    bad_devices.append('/dev/%s' % device)
                else:
                    raise

        return bad_devices

    def safe_cleanup_from_vdis(self, vdi_refs):
        # A helper method to detach volumes that are not associated with an
        # instance

        for vdi_ref in vdi_refs:
            try:
                sr_ref = volume_utils.find_sr_from_vdi(self._session, vdi_ref)
            except exception.StorageError as exc:
                LOG.debug(exc.format_message())
                continue
            try:
                # Forget (i.e. disconnect) SR only if not in use
                volume_utils.purge_sr(self._session, sr_ref)
            except Exception:
                LOG.debug('Ignoring error while purging sr: %s', sr_ref,
                          exc_info=True)

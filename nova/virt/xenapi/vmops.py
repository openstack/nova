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
Management class for VM-related functions (spawn, reboot, etc).
"""

import logging

from nova import db
from nova import context
from nova import exception
from nova import utils

from nova.auth.manager import AuthManager
from nova.compute import power_state
from nova.virt.xenapi.network_utils import NetworkHelper
from nova.virt.xenapi.vm_utils import VMHelper
from nova.virt.xenapi.vm_utils import ImageType


class VMOps(object):
    """
    Management class for VM-related tasks
    """

    def __init__(self, session):
        self.XenAPI = session.get_imported_xenapi()
        self._session = session
        VMHelper.XenAPI = self.XenAPI

    def list_instances(self):
        """List VM instances"""
        vms = []
        for vm in self._session.get_xenapi().VM.get_all():
            rec = self._session.get_xenapi().VM.get_record(vm)
            if not rec["is_a_template"] and not rec["is_control_domain"]:
                vms.append(rec["name_label"])
        return vms

    def spawn(self, instance):
        """Create VM instance"""
        vm = VMHelper.lookup(self._session, instance.name)
        if vm is not None:
            raise exception.Duplicate(_('Attempted to create'
            ' non-unique name %s') % instance.name)

        bridge = db.network_get_by_instance(context.get_admin_context(),
                                            instance['id'])['bridge']
        network_ref = \
            NetworkHelper.find_network_with_bridge(self._session, bridge)

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        #if kernel is not present we must download a raw disk
        if instance.kernel_id:
            disk_image_type = ImageType.DISK
        else:
            disk_image_type = ImageType.DISK_RAW
        vdi_uuid = VMHelper.fetch_image(self._session, instance.id,
            instance.image_id, user, project, disk_image_type)
        vdi_ref = self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
        #Have a look at the VDI and see if it has a PV kernel
        pv_kernel = False
        if not instance.kernel_id:
            pv_kernel = VMHelper.lookup_image(self._session, vdi_ref)
        kernel = None
        if instance.kernel_id:
            kernel = VMHelper.fetch_image(self._session, instance.id,
                instance.kernel_id, user, project, ImageType.KERNEL_RAMDISK)
        ramdisk = None
        if instance.ramdisk_id:
            ramdisk = VMHelper.fetch_image(self._session, instance.id,
                instance.ramdisk_id, user, project, ImageType.KERNEL_RAMDISK)
        vm_ref = VMHelper.create_vm(self._session,
                                          instance, kernel, ramdisk, pv_kernel)
        VMHelper.create_vbd(self._session, vm_ref, vdi_ref, 0, True)

        if network_ref:
            VMHelper.create_vif(self._session, vm_ref,
                                network_ref, instance.mac_address)
        logging.debug(_('Starting VM %s...'), vm_ref)
        self._session.call_xenapi('VM.start', vm_ref, False, False)
        logging.info(_('Spawning VM %s created %s.'), instance.name,
                     vm_ref)

        # NOTE(armando): Do we really need to do this in virt?
        timer = utils.LoopingCall(f=None)

        def _wait_for_boot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug(_('Instance %s: booted'), instance['name'])
                    timer.stop()
            except Exception, exc:
                logging.warn(exc)
                logging.exception(_('instance %s: failed to boot'),
                                  instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_boot
        return timer.start(interval=0.5, now=True)

    def snapshot(self, instance, name):
        """ Create snapshot from a running VM instance
      
        :param instance: instance to be snapshotted
        :param name: name/label to be given to the snapshot

        Steps involved in a XenServer snapshot:

        1. XAPI-Snapshot: Snapshotting the instance using XenAPI. This
            creates: Snapshot (Template) VM, Snapshot VBD, Snapshot VDI,
            Snapshot VHD
    
        2. Wait-for-coalesce: The Snapshot VDI and Instance VDI both point to
            a 'base-copy' VDI.  The base_copy is immutable and may be chained
            with other base_copies.  If chained, the base_copies
            coalesce together, so, we must wait for this coalescing to occur to
            get a stable representation of the data on disk.

        3. Push-to-glance: Once coalesced, we call a plugin on the XenServer
            that will bundle the VHDs together and then push the bundle into
            Glance.
        """

        #TODO(sirp): Add quiesce and VSS locking support when Windows support
        # is added

        logging.debug(_("Starting snapshot for VM %s"), instance)
        vm_ref = VMHelper.lookup(self._session, instance.name)

        label = "%s-snapshot" % instance.name
        try:
            template_vm_ref, template_vdi_uuids = VMHelper.create_snapshot(
                self._session, instance.id, vm_ref, label)
        except XenAPI.Failure, exc:
            logging.error(_("Unable to Snapshot %s: %s"), vm_ref, exc)
            return
       
        try:
            # call plugin to ship snapshot off to glance
            VMHelper.upload_image(
                self._session, instance.id, template_vdi_uuids, name) 
        finally:
            self._destroy(instance, template_vm_ref, shutdown=False)

        logging.debug(_("Finished snapshot and upload for VM %s"), instance)

    def reboot(self, instance):
        """Reboot VM instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise exception.NotFound(_('instance not'
                                       ' found %s') % instance_name)
        task = self._session.call_xenapi('Async.VM.clean_reboot', vm)
        self._session.wait_for_task(instance.id, task)

    def destroy(self, instance):
        """Destroy VM instance"""
        vm = VMHelper.lookup(self._session, instance.name)
        return self._destroy(instance, vm, shutdown=True)

    def _destroy(self, instance, vm, shutdown=True):
        """ Destroy VM instance """
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            return
        # Get the VDIs related to the VM
        vdis = VMHelper.lookup_vm_vdis(self._session, vm)
        if shutdown:
            try:
                task = self._session.call_xenapi('Async.VM.hard_shutdown', vm)
                self._session.wait_for_task(instance.id, task)
            except XenAPI.Failure, exc:
                logging.warn(exc)

        # Disk clean-up
        if vdis:
            for vdi in vdis:
                try:
                    task = self._session.call_xenapi('Async.VDI.destroy', vdi)
                    self._session.wait_for_task(instance.id, task)
                except XenAPI.Failure, exc:
                    logging.warn(exc)
        # VM Destroy
        try:
            task = self._session.call_xenapi('Async.VM.destroy', vm)
            self._session.wait_for_task(instance.id, task)
        except XenAPI.Failure, exc:
            logging.warn(exc)

    def _wait_with_callback(self, instance_id, task, callback):
        ret = None
        try:
            ret = self._session.wait_for_task(instance_id, task)
        except XenAPI.Failure, exc:
            logging.warn(exc)
        callback(ret)

    def pause(self, instance, callback):
        """Pause VM instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise exception.NotFound(_('Instance not'
                                       ' found %s') % instance_name)
        task = self._session.call_xenapi('Async.VM.pause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def unpause(self, instance, callback):
        """Unpause VM instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise exception.NotFound(_('Instance not'
                                       ' found %s') % instance_name)
        task = self._session.call_xenapi('Async.VM.unpause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def get_info(self, instance_id):
        """Return data about VM instance"""
        vm = VMHelper.lookup(self._session, instance_id)
        if vm is None:
            raise exception.NotFound(_('Instance not'
                                       ' found %s') % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_info(rec)

    def get_diagnostics(self, instance_id):
        """Return data about VM diagnostics"""
        vm = VMHelper.lookup(self._session, instance_id)
        if vm is None:
            raise exception.NotFound(_("Instance not found %s") % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_diagnostics(self._session, rec)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

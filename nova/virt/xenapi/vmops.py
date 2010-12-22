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

from nova.auth.manager import AuthManager
from nova.virt.xenapi.network_utils import NetworkHelper
from nova.virt.xenapi.vm_utils import VMHelper

XenAPI = None


class VMOps(object):
    """
    Management class for VM-related tasks
    """

    def __init__(self, session):
        global XenAPI
        if XenAPI is None:
            XenAPI = __import__('XenAPI')
        self._session = session
        # Load XenAPI module in the helper class
        VMHelper.late_import()

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
            raise Exception('Attempted to create non-unique name %s' %
                            instance.name)

        bridge = db.project_get_network(context.get_admin_context(),
                                      instance.project_id).bridge
        network_ref = \
            NetworkHelper.find_network_with_bridge(self._session, bridge)

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        vdi_uuid = VMHelper.fetch_image(
                self._session, instance.id, instance.image_id, user, project,
                True)
        kernel = VMHelper.fetch_image(
                self._session, instance.id, instance.kernel_id, user, project,
                False)
        ramdisk = VMHelper.fetch_image(
                self._session, instance.id, instance.ramdisk_id, user, project,
                False)
        vdi_ref = self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
        vm_ref = VMHelper.create_vm(
                self._session, instance, kernel, ramdisk)
        VMHelper.create_vbd(self._session, vm_ref, vdi_ref, 0, True)
        if network_ref:
            VMHelper.create_vif(self._session, vm_ref,
                                network_ref, instance.mac_address)
        logging.debug('Starting VM %s...', vm_ref)
        self._session.call_xenapi('VM.start', vm_ref, False, False)
        logging.info('Spawning VM %s created %s.', instance.name,
                     vm_ref)
    
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
            raise Exception('instance not present %s' % instance_name)
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
            raise Exception('instance not present %s' % instance_name)
        task = self._session.call_xenapi('Async.VM.pause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def unpause(self, instance, callback):
        """Unpause VM instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception('instance not present %s' % instance_name)
        task = self._session.call_xenapi('Async.VM.unpause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def get_info(self, instance_id):
        """Return data about VM instance"""
        vm = VMHelper.lookup_blocking(self._session, instance_id)
        if vm is None:
            raise Exception('instance not present %s' % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_info(rec)

    def get_diagnostics(self, instance_id):
        """Return data about VM diagnostics"""
        vm = VMHelper.lookup(self._session, instance_id)
        if vm is None:
            raise Exception("instance not present %s" % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_diagnostics(self._session, rec)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

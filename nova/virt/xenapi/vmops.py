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
                self._session, instance.image_id, user, project, True)
        kernel = VMHelper.fetch_image(
                self._session, instance.kernel_id, user, project, False)
        ramdisk = VMHelper.fetch_image(
                self._session, instance.ramdisk_id, user, project, False)
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

    def reboot(self, instance):
        """Reboot VM instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception('instance not present %s' % instance_name)
        task = self._session.call_xenapi('Async.VM.clean_reboot', vm)
        self._session.wait_for_task(instance.id, task)

    def _get_vm_opaque_ref(self, instance_or_vm):
        try:
            instance_name = instance_or_vm.name
            vm = VMHelper.lookup(self._session, instance_name)
        except AttributeError:
            # A vm opaque ref was passed
            vm = instance_or_vm
        if vm is None:
            raise Exception('instance not present %s' % instance_name)
        return vm

    def remove_from_xenstore(self, instance_or_vm, keys):
        vm = self._get_vm_opaque_ref(instance_or_vm)
        for key in keys:
            self._session._session.xenapi_request('VM.remove_from_xenstore_data',
                    (vm, key))

    def read_from_xenstore(self, instance_or_vm, keys=None):
        """Returns the xenstore data for the specified VM instance as
        a dict. Accepts an optional list of keys; if the list of keys is 
        passed, the returned dict is filtered to only return the values
        for those keys.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        ret = self._session._session.xenapi_request('VM.get_xenstore_data', (vm, ))
        if keys:
            allkeys = set(ret.keys())
            badkeys = allkeys.difference(keys)
            for k in badkeys:
                ret.pop(k)
        return ret

    def add_to_xenstore(self, instance_or_vm, mapping):
        """Takes a dict and adds it to the xenstore record for
        the given vm instance. Existing data is preserved, but any
        existing values for the mapping's keys are overwritten.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        current_data = self.read_from_xenstore(vm)
        current_data.update(mapping)
        self.write_to_xenstore(vm, current_data)

    def write_to_xenstore(self, instance_or_vm, mapping):
        """Takes a dict and writes it to the xenstore record for
        the given vm instance. Any existing data is overwritten.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        self._session._session.xenapi_request('VM.set_xenstore_data',
                (vm, mapping))

    def reset_root_password(self, instance):
        """Reset the root/admin password on the VM instance"""
        self.add_to_xenstore(instance, {"reset_root_password": "requested"})
        self.add_to_xenstore(instance, {"TEST": "OMG!"})
        import time
        self.add_to_xenstore(instance, {"timestamp": time.ctime()})


    def destroy(self, instance):
        """Destroy VM instance"""
        vm = VMHelper.lookup(self._session, instance.name)
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            return
        # Get the VDIs related to the VM
        vdis = VMHelper.lookup_vm_vdis(self._session, vm)
        try:
            task = self._session.call_xenapi('Async.VM.hard_shutdown',
                                                   vm)
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

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

import json
import logging
import random
import uuid

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
            raise exception.Duplicate(_('Attempted to create non-unique name %s')
            		% instance.name)

        bridge = db.network_get_by_instance(context.get_admin_context(),
                                            instance['id'])['bridge']
        network_ref = NetworkHelper.find_network_with_bridge(self._session, bridge)

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        #if kernel is not present we must download a raw disk
        if instance.kernel_id:
            disk_image_type = ImageType.DISK
        else:
            disk_image_type = ImageType.DISK_RAW
        vdi_uuid = VMHelper.fetch_image(self._session,
            instance.image_id, user, project, disk_image_type)
        vdi_ref = self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
        #Have a look at the VDI and see if it has a PV kernel
        pv_kernel = False
        if not instance.kernel_id:
            pv_kernel = VMHelper.lookup_image(self._session, vdi_ref)
        kernel = None
        if instance.kernel_id:
            kernel = VMHelper.fetch_image(self._session,
                instance.kernel_id, user, project, ImageType.KERNEL_RAMDISK)
        ramdisk = None
        if instance.ramdisk_id:
            ramdisk = VMHelper.fetch_image(self._session,
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

    def _get_vm_opaque_ref(self, instance_or_vm):
        try:
            instance_name = instance_or_vm.name
            vm = VMHelper.lookup(self._session, instance_name)
        except AttributeError:
            # A vm opaque ref was passed
            vm = instance_or_vm
        if vm is None:
            raise Exception(_('Instance not present %s') % instance_name)
        return vm

    def reboot(self, instance):
        """Reboot VM instance"""
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.clean_reboot', vm)
        self._session.wait_for_task(instance.id, task)

    def reset_root_password(self, instance):
        """Reset the root/admin password on the VM instance"""
        self.add_to_param_xenstore(instance, "reset_root_password", "requested")
        self.add_to_param_xenstore(instance, "TEST", "OMG!")
        import time
        self.add_to_param_xenstore(instance, "timestamp", time.ctime())


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
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.pause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def unpause(self, instance, callback):
        """Unpause VM instance"""
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.unpause', vm)
        self._wait_with_callback(instance.id, task, callback)

    def suspend(self, instance, callback):
        """suspend the specified instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception(_("suspend: instance not present %s") %
                                                     instance_name)
        task = self._session.call_xenapi('Async.VM.suspend', vm)
        self._wait_with_callback(task, callback)

    def resume(self, instance, callback):
        """resume the specified instance"""
        instance_name = instance.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception(_("resume: instance not present %s") %
                                                    instance_name)
        task = self._session.call_xenapi('Async.VM.resume', vm, False, True)
        self._wait_with_callback(task, callback)

    def get_info(self, instance_id):
        """Return data about VM instance"""
        vm = VMHelper.lookup_blocking(self._session, instance_id)
        if vm is None:
            raise Exception(_('Instance not present %s') % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_info(rec)

    def get_diagnostics(self, instance_id):
        """Return data about VM diagnostics"""
        vm = self._get_vm_opaque_ref(instance)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_diagnostics(self._session, rec)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

    def dh_keyinit(self, instance):
        """Initiates a Diffie-Hellman (or, more precisely, a
        Diffie-Hellman-Merkle) key exchange with the agent. It will
        compute one side of the exchange and write it to xenstore.
        When a response is received, it will then compute the shared
        secret key, which is returned.
        NOTE: the base and prime are pre-set; this may change in
        the future.
        """
        base = 5
        prime = 162259276829213363391578010288127
        secret_int = random.randint(100,1000)
        val = (base ** secret_int) % prime
        msgname = str(uuid.uuid4())
        key = "/data/host/%s" % msgname
        self.add_to_param_xenstore(instance, key=key,
                value={"name": "keyinit", "value": val})

    def read_partial_from_param_xenstore(self, instance_or_vm, key_prefix):
        """Returns a dict of all the keys in the xenstore for the given instance
        that begin with the key_prefix.
        """
        data = self.read_from_param_xenstore(instance_or_vm)
        badkeys = [k for k in data.keys()
                if not k.startswith(key_prefix)]
        for badkey in badkeys:
            del data[badkey]
        return data

    def read_from_param_xenstore(self, instance_or_vm, keys=None):
        """Returns the xenstore data for the specified VM instance as
        a dict. Accepts an optional key or list of keys; if a value for 'keys' 
        is passed, the returned dict is filtered to only return the values
        for those keys.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        data = self._session.call_xenapi_request('VM.get_xenstore_data', (vm, ))
        ret = {}
        if keys is None:
            keys = data.keys()
        elif isinstance(keys, basestring):
            keys = [keys]
        for key in keys:
            raw = data.get(key)
            if raw:
                ret[key] = json.loads(raw)
            else:
                ret[key] = raw
        return ret

    def add_to_param_xenstore(self, instance_or_vm, key, val):
        """Takes a key/value pair and adds it to the xenstore record
        for the given vm instance. If the key exists in xenstore, it is
        overwritten"""
        vm = self._get_vm_opaque_ref(instance_or_vm)
        self.remove_from_param_xenstore(instance_or_vm, key)
        jsonval = json.dumps(val)
        self._session.call_xenapi_request('VM.add_to_xenstore_data',
                (vm, key, jsonval))

    def write_to_param_xenstore(self, instance_or_vm, mapping):
        """Takes a dict and writes each key/value pair to the xenstore
        record for the given vm instance. Any existing data for those
        keys is overwritten.
        """
        for k, v in mapping.iteritems():
            self.add_to_param_xenstore(instance_or_vm, k, v)

    def remove_from_param_xenstore(self, instance_or_vm, key_or_keys):
        """Takes either a single key or a list of keys and removes
        them from the xenstore data for the given VM. If the key
        doesn't exist, the request is ignored.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        if isinstance(key_or_keys, basestring):
            keys = [key_or_keys]
        else:
            keys = key_or_keys
        for key in keys:
            self._session.call_xenapi_request('VM.remove_from_xenstore_data', (vm, key))
        """Takes either a single key or a list of keys and removes
        them from the xenstore data for the given VM. If the key
        doesn't exist, the request is ignored.
        """
        vm = self._get_vm_opaque_ref(instance_or_vm)
        if isinstance(key_or_keys, basestring):
            keys = [key_or_keys]
        else:
            keys = key_or_keys
        for key in keys:
            self._session.call_xenapi_request('VM.remove_from_xenstore_data', (vm, key))

    def clear_param_xenstore(self, instance_or_vm):
        """Removes all data from the xenstore record for this VM."""
        self.write_to_param_xenstore(instance_or_vm, {})

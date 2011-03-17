# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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

import base64
import json
import M2Crypto
import os
import pickle
import subprocess
import tempfile
import uuid
import sys

from nova import db
from nova import context
from nova import log as logging
from nova import exception
from nova import utils

from nova.auth.manager import AuthManager
from nova.compute import power_state
from nova.virt.xenapi.network_utils import NetworkHelper
from nova.virt.xenapi.vm_utils import VMHelper
from nova.virt.xenapi.vm_utils import ImageType

XenAPI = None
LOG = logging.getLogger("nova.virt.xenapi.vmops")


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
        vm_refs = []
        for vm_ref in self._session.get_xenapi().VM.get_all():
            vm_rec = self._session.get_xenapi().VM.get_record(vm_ref)
            if not vm_rec["is_a_template"] and not vm_rec["is_control_domain"]:
                vm_refs.append(vm_rec["name_label"])
        return vm_refs

    def _start(self, instance, vm_ref=None):
        """Power on a VM instance"""
        if not vm_ref:
            vm_ref = VMHelper.lookup(self._session, instance.name)
        if vm_ref is None:
            raise exception(_('Attempted to power on non-existent instance'
            ' bad instance id %s') % instance.id)
        LOG.debug(_("Starting instance %s"), instance.name)
        self._session.call_xenapi('VM.start', vm_ref, False, False)

    def create_disk(self, instance):
        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        disk_image_type = VMHelper.determine_disk_image_type(instance)
        #if fetch image fails the exception will be handled in spawn
        vdi_uuid = VMHelper.fetch_image(self._session, instance.id,
                instance.image_id, user, project, disk_image_type)
        return (vdi_uuid, disk_image_type)

    def spawn(self, instance):
        try:
            vdi_uuid = disk_image_type = None
            (vdi_uuid, disk_image_type) = self.create_disk(instance)
            self._spawn_with_disk(instance, vdi_uuid=vdi_uuid)
        except (self.XenAPI.Failure, OSError, IOError) as spawn_error:

            LOG.exception(_("instance %s: Failed to spawn"),
                          instance.id, exc_info=sys.exc_info())
            LOG.debug(_('Instance %s failed to spawn - performing clean-up'),
                      instance.id)
            self._handle_spawn_error(vdi_uuid, disk_image_type, spawn_error)
            #re-throw the error
            raise spawn_error

    def _spawn_with_disk(self, instance, vdi_uuid):
        """Create VM instance"""
        instance_name = instance.name
        vm_ref = VMHelper.lookup(self._session, instance_name)
        if vm_ref is not None:
            raise exception.Duplicate(_('Attempted to create'
                    ' non-unique name %s') % instance_name)

        #ensure enough free memory is available
        if not VMHelper.ensure_free_mem(self._session, instance):
            LOG.exception(_('instance %(instance_name)s: not enough free '
                          'memory') % locals())
            db.instance_set_state(context.get_admin_context(),
                                  instance['id'],
                                  power_state.SHUTDOWN)
            return

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)

        # Are we building from a pre-existing disk?
        vdi_ref = self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)

        disk_image_type = VMHelper.determine_disk_image_type(instance)

        try:
            kernel = None
            ramdisk = None

            if instance.kernel_id:
                kernel = VMHelper.fetch_image(self._session,
                    instance.id, instance.kernel_id, user, project,
                    ImageType.KERNEL)

            if instance.ramdisk_id:
                ramdisk = VMHelper.fetch_image(self._session,
                    instance.id, instance.ramdisk_id, user, project,
                    ImageType.RAMDISK)

            use_pv_kernel = VMHelper.determine_is_pv(self._session,
                instance.id, vdi_ref, disk_image_type, instance.os_type)

            vm_ref = VMHelper.create_vm(self._session, instance,
                                        kernel, ramdisk, use_pv_kernel)
        except self.XenAPI.Failure as vm_create_error:
            # if the spawn process fails here it will be necessary to
            # clean up kernel and ramdisk (only files in dom0)
            LOG.exception(_("instance %s: Failed to spawn - " +
                            "Unable to create VM"),
                          instance.id, exc_info=sys.exc_info())

            last_arg = None
            resources = {}
            if len(vm_create_error.args) > 0:
                last_arg = vm_create_error.args[len(vm_create_error.args) - 1]
            if isinstance(last_arg, dict):
                resources = last_arg
            if ImageType.KERNEL not in resources and kernel:
                resources[ImageType.KERNEL] = (None, kernel)
            if ImageType.RAMDISK not in resources and ramdisk:
                resources[ImageType.RAMDISK] = (None, ramdisk)
            vm_create_error.args = vm_create_error.args + (resources,)
            raise vm_create_error

        VMHelper.create_vbd(session=self._session, vm_ref=vm_ref,
                vdi_ref=vdi_ref, userdevice=0, bootable=True)

        # inject_network_info and create vifs
        networks = self.inject_network_info(instance)
        self.create_vifs(instance, networks)

        LOG.debug(_('Starting VM %s...'), vm_ref)
        self._start(instance, vm_ref)
        LOG.info(_('Spawning VM %(instance_name)s created %(vm_ref)s.')
                 % locals())

        def _inject_files():
            injected_files = instance.injected_files
            if injected_files:
                # Check if this is a JSON-encoded string and convert if needed.
                if isinstance(injected_files, basestring):
                    try:
                        injected_files = json.loads(injected_files)
                    except ValueError:
                        LOG.exception(
                            _("Invalid value for injected_files: '%s'")
                                % injected_files)
                        injected_files = []
                # Inject any files, if specified
                for path, contents in instance.injected_files:
                    LOG.debug(_("Injecting file path: '%s'") % path)
                    self.inject_file(instance, path, contents)
        # NOTE(armando): Do we really need to do this in virt?
        # NOTE(tr3buchet): not sure but wherever we do it, we need to call
        #                  reset_network afterwards
        timer = utils.LoopingCall(f=None)

        def _wait_for_boot():
            try:
                state = self.get_info(instance_name)['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    LOG.debug(_('Instance %s: booted'), instance_name)
                    timer.stop()
                    _inject_files()
                    return True
            except Exception, exc:
                LOG.warn(exc)
                LOG.exception(_('instance %s: failed to boot'),
                              instance_name)
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()
                return False

        timer.f = _wait_for_boot

        # call to reset network to configure network from xenstore
        self.reset_network(instance)

        return timer.start(interval=0.5, now=True)

    def _handle_spawn_error(self, vdi_uuid, disk_image_type, spawn_error):
        resources = {}
        if vdi_uuid:
            resources[disk_image_type] = (vdi_uuid,)
        #extract resource dictionary from spawn error
        if len(spawn_error.args) > 0:
            last_arg = spawn_error.args[len(spawn_error.args) - 1]
            if isinstance(last_arg, dict):
                for item in last_arg:
                    resources[item] = last_arg[item]
        LOG.debug(_("resources to remove:%s"), resources)
        files_to_remove = {}
        for vdi_type in resources:
            items_to_remove = resources[vdi_type]
            vdi_to_remove = items_to_remove[0]
            if vdi_to_remove != None:
                try:
                    vdi_ref = self._session.call_xenapi('VDI.get_by_uuid',
                            vdi_to_remove)
                    LOG.debug(_('Removing VDI %(vdi_ref)s' +
                                '(uuid:%(vdi_to_remove)s)'), locals())
                except self.XenAPI.Failure:
                    #vdi already deleted
                    LOG.debug(_("Skipping VDI destroy for %s"), vdi_to_remove)
                    continue
                VMHelper.destroy_vdi(self._session, vdi_ref)
            if len(items_to_remove) > 1:
                # there is also a file to remove
                files_to_remove[vdi_type] = items_to_remove[1]
        if len(files_to_remove) > 0:
            LOG.debug(_("Removing kernel/ramdisk files from dom0"))
            self._destroy_kernel_ramdisk_plugin_call(
                    files_to_remove.get(ImageType.KERNEL, None),
                    files_to_remove.get(ImageType.RAMDISK, None))

    def _get_vm_opaque_ref(self, instance_or_vm):
        """Refactored out the common code of many methods that receive either
        a vm name or a vm instance, and want a vm instance in return.
        """
        # if instance_or_vm is a string it must be opaque ref or instance name
        if isinstance(instance_or_vm, basestring):
            obj = None
            try:
                # check for opaque ref
                obj = self._session.get_xenapi().VM.get_record(instance_or_vm)
                return instance_or_vm
            except self.XenAPI.Failure:
                # wasn't an opaque ref, must be an instance name
                instance_name = instance_or_vm

        # if instance_or_vm is an int/long it must be instance id
        elif isinstance(instance_or_vm, (int, long)):
            ctx = context.get_admin_context()
            try:
                instance_obj = db.instance_get(ctx, instance_or_vm)
                instance_name = instance_obj.name
            except exception.NotFound:
                # The unit tests screw this up, as they use an integer for
                # the vm name. I'd fix that up, but that's a matter for
                # another bug report. So for now, just try with the passed
                # value
                instance_name = instance_or_vm

        # otherwise instance_or_vm is an instance object
        else:
            instance_name = instance_or_vm.name
        vm_ref = VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise exception.NotFound(
                            _('Instance not present %s') % instance_name)
        return vm_ref

    def _acquire_bootlock(self, vm):
        """Prevent an instance from booting"""
        self._session.call_xenapi(
            "VM.set_blocked_operations",
            vm,
            {"start": ""})

    def _release_bootlock(self, vm):
        """Allow an instance to boot"""
        self._session.call_xenapi(
            "VM.remove_from_blocked_operations",
            vm,
            "start")

    def snapshot(self, instance, image_id):
        """Create snapshot from a running VM instance

        :param instance: instance to be snapshotted
        :param image_id: id of image to upload to

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
        template_vm_ref = None
        try:
            template_vm_ref, template_vdi_uuids = self._get_snapshot(instance)
            # call plugin to ship snapshot off to glance
            VMHelper.upload_image(
                    self._session, instance, template_vdi_uuids, image_id)
        finally:
            if template_vm_ref:
                self._destroy(instance, template_vm_ref,
                        shutdown=False, destroy_kernel_ramdisk=False)

        logging.debug(_("Finished snapshot and upload for VM %s"), instance)

    def _get_snapshot(self, instance):
        #TODO(sirp): Add quiesce and VSS locking support when Windows support
        # is added

        logging.debug(_("Starting snapshot for VM %s"), instance)
        vm_ref = VMHelper.lookup(self._session, instance.name)

        label = "%s-snapshot" % instance.name
        try:
            template_vm_ref, template_vdi_uuids = VMHelper.create_snapshot(
                self._session, instance.id, vm_ref, label)
            return template_vm_ref, template_vdi_uuids
        except self.XenAPI.Failure, exc:
            logging.error(_("Unable to Snapshot %(vm_ref)s: %(exc)s")
                    % locals())
            return

    def migrate_disk_and_power_off(self, instance, dest):
        """Copies a VHD from one host machine to another

        :param instance: the instance that owns the VHD in question
        :param dest: the destination host machine
        :param disk_type: values are 'primary' or 'cow'
        """
        vm_ref = VMHelper.lookup(self._session, instance.name)

        # The primary VDI becomes the COW after the snapshot, and we can
        # identify it via the VBD. The base copy is the parent_uuid returned
        # from the snapshot creation

        base_copy_uuid = cow_uuid = None
        template_vdi_uuids = template_vm_ref = None
        try:
            # transfer the base copy
            template_vm_ref, template_vdi_uuids = self._get_snapshot(instance)
            base_copy_uuid = template_vdi_uuids[1]
            vdi_ref, vm_vdi_rec = \
                    VMHelper.get_vdi_for_vm_safely(self._session, vm_ref)
            cow_uuid = vm_vdi_rec['uuid']

            params = {'host': dest,
                      'vdi_uuid': base_copy_uuid,
                      'instance_id': instance.id,
                      'sr_path': VMHelper.get_sr_path(self._session)}

            task = self._session.async_call_plugin('migration', 'transfer_vhd',
                    {'params': pickle.dumps(params)})
            self._session.wait_for_task(task, instance.id)

            # Now power down the instance and transfer the COW VHD
            self._shutdown(instance, vm_ref, method='clean')

            params = {'host': dest,
                      'vdi_uuid': cow_uuid,
                      'instance_id': instance.id,
                      'sr_path': VMHelper.get_sr_path(self._session), }

            task = self._session.async_call_plugin('migration', 'transfer_vhd',
                    {'params': pickle.dumps(params)})
            self._session.wait_for_task(task, instance.id)

        finally:
            if template_vm_ref:
                self._destroy(instance, template_vm_ref,
                        shutdown=False, destroy_kernel_ramdisk=False)

        # TODO(mdietz): we could also consider renaming these to something
        # sensible so we don't need to blindly pass around dictionaries
        return {'base_copy': base_copy_uuid, 'cow': cow_uuid}

    def attach_disk(self, instance, base_copy_uuid, cow_uuid):
        """Links the base copy VHD to the COW via the XAPI plugin"""
        vm_ref = VMHelper.lookup(self._session, instance.name)
        new_base_copy_uuid = str(uuid.uuid4())
        new_cow_uuid = str(uuid.uuid4())
        params = {'instance_id': instance.id,
                  'old_base_copy_uuid': base_copy_uuid,
                  'old_cow_uuid': cow_uuid,
                  'new_base_copy_uuid': new_base_copy_uuid,
                  'new_cow_uuid': new_cow_uuid,
                  'sr_path': VMHelper.get_sr_path(self._session), }

        task = self._session.async_call_plugin('migration',
                'move_vhds_into_sr', {'params': pickle.dumps(params)})
        self._session.wait_for_task(task, instance.id)

        # Now we rescan the SR so we find the VHDs
        VMHelper.scan_default_sr(self._session)

        return new_cow_uuid

    def resize(self, instance, flavor):
        """Resize a running instance by changing it's RAM and disk size """
        raise NotImplementedError()

    def reboot(self, instance):
        """Reboot VM instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.clean_reboot', vm_ref)
        self._session.wait_for_task(task, instance.id)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance. This is done via
        an agent running on the VM. Communication between nova and the agent
        is done via writing xenstore records. Since communication is done over
        the XenAPI RPC calls, we need to encrypt the password. We're using a
        simple Diffie-Hellman class instead of the more advanced one in
        M2Crypto for compatibility with the agent code.
        """
        # Need to uniquely identify this request.
        transaction_id = str(uuid.uuid4())
        # The simple Diffie-Hellman class is used to manage key exchange.
        dh = SimpleDH()
        args = {'id': transaction_id, 'pub': str(dh.get_public())}
        resp = self._make_agent_call('key_init', instance, '', args)
        if resp is None:
            # No response from the agent
            return
        resp_dict = json.loads(resp)
        # Successful return code from key_init is 'D0'
        if resp_dict['returncode'] != 'D0':
            # There was some sort of error; the message will contain
            # a description of the error.
            raise RuntimeError(resp_dict['message'])
        agent_pub = int(resp_dict['message'])
        dh.compute_shared(agent_pub)
        enc_pass = dh.encrypt(new_pass)
        # Send the encrypted password
        args['enc_pass'] = enc_pass
        resp = self._make_agent_call('password', instance, '', args)
        if resp is None:
            # No response from the agent
            return
        resp_dict = json.loads(resp)
        # Successful return code from password is '0'
        if resp_dict['returncode'] != '0':
            raise RuntimeError(resp_dict['message'])
        return resp_dict['message']

    def inject_file(self, instance, path, contents):
        """Write a file to the VM instance. The path to which it is to be
        written and the contents of the file need to be supplied; both will
        be base64-encoded to prevent errors with non-ASCII characters being
        transmitted. If the agent does not support file injection, or the user
        has disabled it, a NotImplementedError will be raised.
        """
        # Files/paths must be base64-encoded for transmission to agent
        b64_path = base64.b64encode(path)
        b64_contents = base64.b64encode(contents)

        # Need to uniquely identify this request.
        transaction_id = str(uuid.uuid4())
        args = {'id': transaction_id, 'b64_path': b64_path,
                'b64_contents': b64_contents}
        # If the agent doesn't support file injection, a NotImplementedError
        # will be raised with the appropriate message.
        resp = self._make_agent_call('inject_file', instance, '', args)
        resp_dict = json.loads(resp)
        if resp_dict['returncode'] != '0':
            # There was some other sort of error; the message will contain
            # a description of the error.
            raise RuntimeError(resp_dict['message'])
        return resp_dict['message']

    def _shutdown(self, instance, vm_ref, hard=True):
        """Shutdown an instance"""
        state = self.get_info(instance['name'])['state']
        if state == power_state.SHUTDOWN:
            LOG.warn(_("VM %(vm)s already halted, skipping shutdown...") %
                     locals())
            return

        instance_id = instance.id
        LOG.debug(_("Shutting down VM for Instance %(instance_id)s")
                  % locals())
        try:
            task = None
            if hard:
                task = self._session.call_xenapi("Async.VM.hard_shutdown",
                                                 vm_ref)
            else:
                task = self._session.call_xenapi("Async.VM.clean_shutdown",
                                                 vm_ref)
            self._session.wait_for_task(task, instance.id)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)

    def _destroy_vdis(self, instance, vm_ref):
        """Destroys all VDIs associated with a VM"""
        instance_id = instance.id
        LOG.debug(_("Destroying VDIs for Instance %(instance_id)s")
                  % locals())
        vdi_refs = VMHelper.lookup_vm_vdis(self._session, vm_ref)

        if not vdi_refs:
            return

        for vdi_ref in vdi_refs:
            try:
                task = self._session.call_xenapi('Async.VDI.destroy', vdi_ref)
                self._session.wait_for_task(task, instance.id)
            except self.XenAPI.Failure, exc:
                LOG.exception(exc)

    def _destroy_kernel_ramdisk_plugin_call(self, kernel, ramdisk):
        args = {}
        if kernel:
            args['kernel-file'] = kernel
        if ramdisk:
            args['ramdisk-file'] = ramdisk
        task = self._session.async_call_plugin(
            'glance', 'remove_kernel_ramdisk', args)
        self._session.wait_for_task(task)

    def _destroy_kernel_ramdisk(self, instance, vm_ref):
        """
        Three situations can occur:

            1. We have neither a ramdisk nor a kernel, in which case we are a
               RAW image and can omit this step

            2. We have one or the other, in which case, we should flag as an
               error

            3. We have both, in which case we safely remove both the kernel
               and the ramdisk.
        """
        instance_id = instance.id
        if not instance.kernel_id and not instance.ramdisk_id:
            # 1. No kernel or ramdisk
            LOG.debug(_("Instance %(instance_id)s using RAW or VHD, "
                        "skipping kernel and ramdisk deletion") % locals())
            return

        if not (instance.kernel_id and instance.ramdisk_id):
            # 2. We only have kernel xor ramdisk
            raise exception.NotFound(
                _("Instance %(instance_id)s has a kernel or ramdisk but not "
                  "both" % locals()))

        # 3. We have both kernel and ramdisk
        (kernel, ramdisk) = VMHelper.lookup_kernel_ramdisk(self._session,
                                                           vm_ref)

        self._destroy_kernel_ramdisk_plugin_call(kernel, ramdisk)
        LOG.debug(_("kernel/ramdisk files removed"))

    def _destroy_vm(self, instance, vm_ref):
        """Destroys a VM record"""
        instance_id = instance.id
        try:
            task = self._session.call_xenapi('Async.VM.destroy', vm_ref)
            self._session.wait_for_task(task, instance_id)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)

        LOG.debug(_("Instance %(instance_id)s VM destroyed") % locals())

    def destroy(self, instance):
        """
        Destroy VM instance

        This is the method exposed by xenapi_conn.destroy(). The rest of the
        destroy_* methods are internal.
        """
        instance_id = instance.id
        LOG.info(_("Destroying VM for Instance %(instance_id)s") % locals())
        vm_ref = VMHelper.lookup(self._session, instance.name)
        return self._destroy(instance, vm_ref, shutdown=True)

    def _destroy(self, instance, vm_ref, shutdown=True,
                 destroy_kernel_ramdisk=True):
        """
        Destroys VM instance by performing:

            1. A shutdown if requested
            2. Destroying associated VDIs
            3. Destroying kernel and ramdisk files (if necessary)
            4. Destroying that actual VM record
        """
        if vm_ref is None:
            LOG.warning(_("VM is not present, skipping destroy..."))
            return

        if shutdown:
            self._shutdown(instance, vm_ref)

        self._destroy_vdis(instance, vm_ref)
        if destroy_kernel_ramdisk:
            self._destroy_kernel_ramdisk(instance, vm_ref)
        self._destroy_vm(instance, vm_ref)

    def _wait_with_callback(self, instance_id, task, callback):
        ret = None
        try:
            ret = self._session.wait_for_task(task, instance_id)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
        callback(ret)

    def pause(self, instance, callback):
        """Pause VM instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.pause', vm_ref)
        self._wait_with_callback(instance.id, task, callback)

    def unpause(self, instance, callback):
        """Unpause VM instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.unpause', vm_ref)
        self._wait_with_callback(instance.id, task, callback)

    def suspend(self, instance, callback):
        """suspend the specified instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.suspend', vm_ref)
        self._wait_with_callback(instance.id, task, callback)

    def resume(self, instance, callback):
        """resume the specified instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.resume', vm_ref, False,
                                         True)
        self._wait_with_callback(instance.id, task, callback)

    def rescue(self, instance, callback):
        """Rescue the specified instance
            - shutdown the instance VM
            - set 'bootlock' to prevent the instance from starting in rescue
            - spawn a rescue VM (the vm name-label will be instance-N-rescue)

        """
        rescue_vm_ref = VMHelper.lookup(self._session,
                                        instance.name + "-rescue")
        if rescue_vm_ref:
            raise RuntimeError(_(
                "Instance is already in Rescue Mode: %s" % instance.name))

        vm_ref = self._get_vm_opaque_ref(instance)
        self._shutdown(instance, vm_ref)
        self._acquire_bootlock(vm_ref)

        instance._rescue = True
        self.spawn(instance)
        rescue_vm_ref = self._get_vm_opaque_ref(instance)

        vbd_ref = self._session.get_xenapi().VM.get_VBDs(vm_ref)[0]
        vdi_ref = self._session.get_xenapi().VBD.get_record(vbd_ref)["VDI"]
        rescue_vbd_ref = VMHelper.create_vbd(self._session, rescue_vm_ref,
                                             vdi_ref, 1, False)

        self._session.call_xenapi("Async.VBD.plug", rescue_vbd_ref)

    def unrescue(self, instance, callback):
        """Unrescue the specified instance
            - unplug the instance VM's disk from the rescue VM
            - teardown the rescue VM
            - release the bootlock to allow the instance VM to start

        """
        rescue_vm_ref = VMHelper.lookup(self._session,
                                    instance.name + "-rescue")

        if not rescue_vm_ref:
            raise exception.NotFound(_(
                "Instance is not in Rescue Mode: %s" % instance.name))

        original_vm_ref = self._get_vm_opaque_ref(instance)
        vbd_refs = self._session.get_xenapi().VM.get_VBDs(rescue_vm_ref)

        instance._rescue = False

        for vbd_ref in vbd_refs:
            _vbd_ref = self._session.get_xenapi().VBD.get_record(vbd_ref)
            if _vbd_ref["userdevice"] == "1":
                VMHelper.unplug_vbd(self._session, vbd_ref)
                VMHelper.destroy_vbd(self._session, vbd_ref)

        task1 = self._session.call_xenapi("Async.VM.hard_shutdown",
                                          rescue_vm_ref)
        self._session.wait_for_task(task1, instance.id)

        vdi_refs = VMHelper.lookup_vm_vdis(self._session, rescue_vm_ref)
        for vdi_ref in vdi_refs:
            try:
                task = self._session.call_xenapi('Async.VDI.destroy', vdi_ref)
                self._session.wait_for_task(task, instance.id)
            except self.XenAPI.Failure:
                continue

        task2 = self._session.call_xenapi('Async.VM.destroy', rescue_vm_ref)
        self._session.wait_for_task(task2, instance.id)

        self._release_bootlock(original_vm_ref)
        self._start(instance, original_vm_ref)

    def get_info(self, instance):
        """Return data about VM instance"""
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_rec = self._session.get_xenapi().VM.get_record(vm_ref)
        return VMHelper.compile_info(vm_rec)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        vm_ref = self._get_vm_opaque_ref(instance)
        vm_rec = self._session.get_xenapi().VM.get_record(vm_ref)
        return VMHelper.compile_diagnostics(self._session, vm_rec)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console"""
        # TODO: implement this!
        return 'http://fakeajaxconsole/fake_url'

    def inject_network_info(self, instance):
        """
        Generate the network info and make calls to place it into the
        xenstore and the xenstore param list

        """
        # TODO(tr3buchet) - remove comment in multi-nic
        # I've decided to go ahead and consider multiple IPs and networks
        # at this stage even though they aren't implemented because these will
        # be needed for multi-nic and there was no sense writing it for single
        # network/single IP and then having to turn around and re-write it
        vm_ref = self._get_vm_opaque_ref(instance.id)
        logging.debug(_("injecting network info to xenstore for vm: |%s|"),
                        vm_ref)
        admin_context = context.get_admin_context()
        IPs = db.fixed_ip_get_all_by_instance(admin_context, instance['id'])
        networks = db.network_get_all_by_instance(admin_context,
                                                  instance['id'])
        for network in networks:
            network_IPs = [ip for ip in IPs if ip.network_id == network.id]

            def ip_dict(ip):
                return {
                    "ip": ip.address,
                    "netmask": network["netmask"],
                    "enabled": "1"}

            def ip6_dict(ip6):
                return {
                    "ip": ip6.addressV6,
                    "netmask": ip6.netmaskV6,
                    "gateway": ip6.gatewayV6,
                    "enabled": "1"}

            mac_id = instance.mac_address.replace(':', '')
            location = 'vm-data/networking/%s' % mac_id
            mapping = {
                'label': network['label'],
                'gateway': network['gateway'],
                'mac': instance.mac_address,
                'dns': [network['dns']],
                'ips': [ip_dict(ip) for ip in network_IPs],
                'ip6s': [ip6_dict(ip) for ip in network_IPs]}

            self.write_to_param_xenstore(vm_ref, {location: mapping})

            try:
                self.write_to_xenstore(vm_ref, location, mapping['location'])
            except KeyError:
                # catch KeyError for domid if instance isn't running
                pass

        return networks

    def create_vifs(self, instance, networks=None):
        """
        Creates vifs for an instance

        """
        vm_ref = self._get_vm_opaque_ref(instance.id)
        logging.debug(_("creating vif(s) for vm: |%s|"), vm_ref)
        if networks is None:
            networks = db.network_get_all_by_instance(admin_context,
                                                      instance['id'])
        # TODO(tr3buchet) - remove comment in multi-nic
        # this bit here about creating the vifs will be updated
        # in multi-nic to handle multiple IPs on the same network
        # and multiple networks
        # for now it works as there is only one of each
        for network in networks:
            bridge = network['bridge']
            network_ref = \
                NetworkHelper.find_network_with_bridge(self._session, bridge)

            if network_ref:
                try:
                    device = "1" if instance._rescue else "0"
                except AttributeError:
                    device = "0"

                VMHelper.create_vif(self._session, vm_ref, network_ref,
                                    instance.mac_address, device)

    def reset_network(self, instance):
        """
        Creates uuid arg to pass to make_agent_call and calls it.

        """
        args = {'id': str(uuid.uuid4())}
        resp = self._make_agent_call('resetnetwork', instance, '', args)

    def list_from_xenstore(self, vm, path):
        """Runs the xenstore-ls command to get a listing of all records
        from 'path' downward. Returns a dict with the sub-paths as keys,
        and the value stored in those paths as values. If nothing is
        found at that path, returns None.
        """
        ret = self._make_xenstore_call('list_records', vm, path)
        return json.loads(ret)

    def read_from_xenstore(self, vm, path):
        """Returns the value stored in the xenstore record for the given VM
        at the specified location. A XenAPIPlugin.PluginError will be raised
        if any error is encountered in the read process.
        """
        try:
            ret = self._make_xenstore_call('read_record', vm, path,
                    {'ignore_missing_path': 'True'})
        except self.XenAPI.Failure, e:
            return None
        ret = json.loads(ret)
        if ret == "None":
            # Can't marshall None over RPC calls.
            return None
        return ret

    def write_to_xenstore(self, vm, path, value):
        """Writes the passed value to the xenstore record for the given VM
        at the specified location. A XenAPIPlugin.PluginError will be raised
        if any error is encountered in the write process.
        """
        return self._make_xenstore_call('write_record', vm, path,
                {'value': json.dumps(value)})

    def clear_xenstore(self, vm, path):
        """Deletes the VM's xenstore record for the specified path.
        If there is no such record, the request is ignored.
        """
        self._make_xenstore_call('delete_record', vm, path)

    def _make_xenstore_call(self, method, vm, path, addl_args={}):
        """Handles calls to the xenstore xenapi plugin."""
        return self._make_plugin_call('xenstore.py', method=method, vm=vm,
                path=path, addl_args=addl_args)

    def _make_agent_call(self, method, vm, path, addl_args={}):
        """Abstracts out the interaction with the agent xenapi plugin."""
        return self._make_plugin_call('agent', method=method, vm=vm,
                path=path, addl_args=addl_args)

    def _make_plugin_call(self, plugin, method, vm, path, addl_args={}):
        """Abstracts out the process of calling a method of a xenapi plugin.
        Any errors raised by the plugin will in turn raise a RuntimeError here.
        """
        instance_id = vm.id
        vm_ref = self._get_vm_opaque_ref(vm)
        vm_rec = self._session.get_xenapi().VM.get_record(vm_ref)
        args = {'dom_id': vm_rec['domid'], 'path': path}
        args.update(addl_args)
        try:
            task = self._session.async_call_plugin(plugin, method, args)
            ret = self._session.wait_for_task(task, instance_id)
        except self.XenAPI.Failure, e:
            ret = None
            err_trace = e.details[-1]
            err_msg = err_trace.splitlines()[-1]
            strargs = str(args)
            if 'TIMEOUT:' in err_msg:
                LOG.error(_('TIMEOUT: The call to %(method)s timed out. '
                        'VM id=%(instance_id)s; args=%(strargs)s') % locals())
            elif 'NOT IMPLEMENTED:' in err_msg:
                LOG.error(_('NOT IMPLEMENTED: The call to %(method)s is not'
                        ' supported by the agent. VM id=%(instance_id)s;'
                        ' args=%(strargs)s') % locals())
                raise NotImplementedError(err_msg)
            else:
                LOG.error(_('The call to %(method)s returned an error: %(e)s. '
                        'VM id=%(instance_id)s; args=%(strargs)s') % locals())
        return ret

    def add_to_xenstore(self, vm, path, key, value):
        """Adds the passed key/value pair to the xenstore record for
        the given VM at the specified location. A XenAPIPlugin.PluginError
        will be raised if any error is encountered in the write process.
        """
        current = self.read_from_xenstore(vm, path)
        if not current:
            # Nothing at that location
            current = {key: value}
        else:
            current[key] = value
        self.write_to_xenstore(vm, path, current)

    def remove_from_xenstore(self, vm, path, key_or_keys):
        """Takes either a single key or a list of keys and removes
        them from the xenstoreirecord data for the given VM.
        If the key doesn't exist, the request is ignored.
        """
        current = self.list_from_xenstore(vm, path)
        if not current:
            return
        if isinstance(key_or_keys, basestring):
            keys = [key_or_keys]
        else:
            keys = key_or_keys
        keys.sort(lambda x, y: cmp(y.count('/'), x.count('/')))
        for key in keys:
            if path:
                keypath = "%s/%s" % (path, key)
            else:
                keypath = key
            self._make_xenstore_call('delete_record', vm, keypath)

    ########################################################################
    ###### The following methods interact with the xenstore parameter
    ###### record, not the live xenstore. They were created before I
    ###### knew the difference, and are left in here in case they prove
    ###### to be useful. They all have '_param' added to their method
    ###### names to distinguish them. (dabo)
    ########################################################################
    def read_partial_from_param_xenstore(self, instance_or_vm, key_prefix):
        """Returns a dict of all the keys in the xenstore parameter record
        for the given instance that begin with the key_prefix.
        """
        data = self.read_from_param_xenstore(instance_or_vm)
        badkeys = [k for k in data.keys()
                if not k.startswith(key_prefix)]
        for badkey in badkeys:
            del data[badkey]
        return data

    def read_from_param_xenstore(self, instance_or_vm, keys=None):
        """Returns the xenstore parameter record data for the specified VM
        instance as a dict. Accepts an optional key or list of keys; if a
        value for 'keys' is passed, the returned dict is filtered to only
        return the values for those keys.
        """
        vm_ref = self._get_vm_opaque_ref(instance_or_vm)
        data = self._session.call_xenapi_request('VM.get_xenstore_data',
                (vm_ref, ))
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
        """Takes a key/value pair and adds it to the xenstore parameter
        record for the given vm instance. If the key exists in xenstore,
        it is overwritten"""
        vm_ref = self._get_vm_opaque_ref(instance_or_vm)
        self.remove_from_param_xenstore(instance_or_vm, key)
        jsonval = json.dumps(val)
        self._session.call_xenapi_request('VM.add_to_xenstore_data',
                                          (vm_ref, key, jsonval))

    def write_to_param_xenstore(self, instance_or_vm, mapping):
        """Takes a dict and writes each key/value pair to the xenstore
        parameter record for the given vm instance. Any existing data for
        those keys is overwritten.
        """
        for k, v in mapping.iteritems():
            self.add_to_param_xenstore(instance_or_vm, k, v)

    def remove_from_param_xenstore(self, instance_or_vm, key_or_keys):
        """Takes either a single key or a list of keys and removes
        them from the xenstore parameter record data for the given VM.
        If the key doesn't exist, the request is ignored.
        """
        vm_ref = self._get_vm_opaque_ref(instance_or_vm)
        if isinstance(key_or_keys, basestring):
            keys = [key_or_keys]
        else:
            keys = key_or_keys
        for key in keys:
            self._session.call_xenapi_request('VM.remove_from_xenstore_data',
                                              (vm_ref, key))

    def clear_param_xenstore(self, instance_or_vm):
        """Removes all data from the xenstore parameter record for this VM."""
        self.write_to_param_xenstore(instance_or_vm, {})
    ########################################################################


def _runproc(cmd):
    pipe = subprocess.PIPE
    return subprocess.Popen([cmd], shell=True, stdin=pipe, stdout=pipe,
            stderr=pipe, close_fds=True)


class SimpleDH(object):
    """This class wraps all the functionality needed to implement
    basic Diffie-Hellman-Merkle key exchange in Python. It features
    intelligent defaults for the prime and base numbers needed for the
    calculation, while allowing you to supply your own. It requires that
    the openssl binary be installed on the system on which this is run,
    as it uses that to handle the encryption and decryption. If openssl
    is not available, a RuntimeError will be raised.
    """
    def __init__(self, prime=None, base=None, secret=None):
        """You can specify the values for prime and base if you wish;
        otherwise, reasonable default values will be used.
        """
        if prime is None:
            self._prime = 162259276829213363391578010288127
        else:
            self._prime = prime
        if base is None:
            self._base = 5
        else:
            self._base = base
        self._shared = self._public = None

        self._dh = M2Crypto.DH.set_params(
                self.dec_to_mpi(self._prime),
                self.dec_to_mpi(self._base))
        self._dh.gen_key()
        self._public = self.mpi_to_dec(self._dh.pub)

    def get_public(self):
        return self._public

    def compute_shared(self, other):
        self._shared = self.bin_to_dec(
                self._dh.compute_key(self.dec_to_mpi(other)))
        return self._shared

    def mpi_to_dec(self, mpi):
        bn = M2Crypto.m2.mpi_to_bn(mpi)
        hexval = M2Crypto.m2.bn_to_hex(bn)
        dec = int(hexval, 16)
        return dec

    def bin_to_dec(self, binval):
        bn = M2Crypto.m2.bin_to_bn(binval)
        hexval = M2Crypto.m2.bn_to_hex(bn)
        dec = int(hexval, 16)
        return dec

    def dec_to_mpi(self, dec):
        bn = M2Crypto.m2.dec_to_bn('%s' % dec)
        mpi = M2Crypto.m2.bn_to_mpi(bn)
        return mpi

    def _run_ssl(self, text, which):
        base_cmd = ('cat %(tmpfile)s | openssl enc -aes-128-cbc '
                '-a -pass pass:%(shared)s -nosalt %(dec_flag)s')
        if which.lower()[0] == 'd':
            dec_flag = ' -d'
        else:
            dec_flag = ''
        fd, tmpfile = tempfile.mkstemp()
        os.close(fd)
        file(tmpfile, 'w').write(text)
        shared = self._shared
        cmd = base_cmd % locals()
        proc = _runproc(cmd)
        proc.wait()
        err = proc.stderr.read()
        if err:
            raise RuntimeError(_('OpenSSL error: %s') % err)
        return proc.stdout.read()

    def encrypt(self, text):
        return self._run_ssl(text, 'enc')

    def decrypt(self, text):
        return self._run_ssl(text, 'dec')

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

import json
import M2Crypto
import os
import subprocess
import tempfile
import uuid

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
        #ensure enough free memory, otherwise don't bother
        if not VMHelper.ensure_free_mem(self._session, instance):
                LOG.exception(_('instance %s: not enough free memory'),
                              instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                return
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
            pv_kernel = VMHelper.lookup_image(self._session, instance.id,
                                              vdi_ref)
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
        LOG.debug(_('Starting VM %s...'), vm_ref)
        self._session.call_xenapi('VM.start', vm_ref, False, False)
        instance_name = instance.name
        LOG.info(_('Spawning VM %(instance_name)s created %(vm_ref)s.')
                % locals())

        # NOTE(armando): Do we really need to do this in virt?
        timer = utils.LoopingCall(f=None)

        def _wait_for_boot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    LOG.debug(_('Instance %s: booted'), instance['name'])
                    timer.stop()
            except Exception, exc:
                LOG.warn(exc)
                LOG.exception(_('instance %s: failed to boot'),
                              instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_boot
        return timer.start(interval=0.5, now=True)

    def _get_vm_opaque_ref(self, instance_or_vm):
        """Refactored out the common code of many methods that receive either
        a vm name or a vm instance, and want a vm instance in return.
        """
        vm = None
        try:
            if instance_or_vm.startswith("OpaqueRef:"):
                # Got passed an opaque ref; return it
                return instance_or_vm
            else:
                # Must be the instance name
                instance_name = instance_or_vm
        except (AttributeError, KeyError):
            # Note the the KeyError will only happen with fakes.py
            # Not a string; must be an ID or a vm instance
            if isinstance(instance_or_vm, (int, long)):
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
            else:
                instance_name = instance_or_vm.name
        vm = VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise exception.NotFound(
                            _('Instance not present %s') % instance_name)
        return vm

    def snapshot(self, instance, image_id):
        """ Create snapshot from a running VM instance

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

        #TODO(sirp): Add quiesce and VSS locking support when Windows support
        # is added

        logging.debug(_("Starting snapshot for VM %s"), instance)
        vm_ref = VMHelper.lookup(self._session, instance.name)

        label = "%s-snapshot" % instance.name
        try:
            template_vm_ref, template_vdi_uuids = VMHelper.create_snapshot(
                self._session, instance.id, vm_ref, label)
        except self.XenAPI.Failure, exc:
            logging.error(_("Unable to Snapshot %(vm_ref)s: %(exc)s")
                    % locals())
            return

        try:
            # call plugin to ship snapshot off to glance
            VMHelper.upload_image(
                self._session, instance.id, template_vdi_uuids, image_id)
        finally:
            self._destroy(instance, template_vm_ref, shutdown=False)

        logging.debug(_("Finished snapshot and upload for VM %s"), instance)

    def reboot(self, instance):
        """Reboot VM instance"""
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.clean_reboot', vm)
        self._session.wait_for_task(instance.id, task)

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

    def _shutdown(self, instance, vm):
        """Shutdown an instance """
        state = self.get_info(instance['name'])['state']
        if state == power_state.SHUTDOWN:
            LOG.warn(_("VM %(vm)s already halted, skipping shutdown...") %
                     locals())
            return

        try:
            task = self._session.call_xenapi('Async.VM.hard_shutdown', vm)
            self._session.wait_for_task(instance.id, task)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)

    def _destroy_vdis(self, instance, vm):
        """Destroys all VDIs associated with a VM """
        vdis = VMHelper.lookup_vm_vdis(self._session, vm)

        if not vdis:
            return

        for vdi in vdis:
            try:
                task = self._session.call_xenapi('Async.VDI.destroy', vdi)
                self._session.wait_for_task(instance.id, task)
            except self.XenAPI.Failure, exc:
                LOG.exception(exc)

    def _destroy_vm(self, instance, vm):
        """Destroys a VM record """
        try:
            task = self._session.call_xenapi('Async.VM.destroy', vm)
            self._session.wait_for_task(instance.id, task)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)

    def destroy(self, instance):
        """
        Destroy VM instance

        This is the method exposed by xenapi_conn.destroy(). The rest of the
        destroy_* methods are internal.
        """
        vm = VMHelper.lookup(self._session, instance.name)
        return self._destroy(instance, vm, shutdown=True)

    def _destroy(self, instance, vm, shutdown=True):
        """
        Destroys VM instance by performing:

        1. A shutdown if requested
        2. Destroying associated VDIs
        3. Destroying that actual VM record
        """
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            return

        if shutdown:
            self._shutdown(instance, vm)

        self._destroy_vdis(instance, vm)
        self._destroy_vm(instance, vm)

    def _wait_with_callback(self, instance_id, task, callback):
        ret = None
        try:
            ret = self._session.wait_for_task(instance_id, task)
        except self.XenAPI.Failure, exc:
            LOG.exception(exc)
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
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.suspend', vm)
        self._wait_with_callback(instance.id, task, callback)

    def resume(self, instance, callback):
        """resume the specified instance"""
        vm = self._get_vm_opaque_ref(instance)
        task = self._session.call_xenapi('Async.VM.resume', vm, False, True)
        self._wait_with_callback(instance.id, task, callback)

    def get_info(self, instance):
        """Return data about VM instance"""
        vm = self._get_vm_opaque_ref(instance)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_info(rec)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        vm = self._get_vm_opaque_ref(instance)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_diagnostics(self._session, rec)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console"""
        # TODO: implement this!
        return 'http://fakeajaxconsole/fake_url'

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
        vm = self._get_vm_opaque_ref(vm)
        rec = self._session.get_xenapi().VM.get_record(vm)
        args = {'dom_id': rec['domid'], 'path': path}
        args.update(addl_args)
        try:
            task = self._session.async_call_plugin(plugin, method, args)
            ret = self._session.wait_for_task(instance_id, task)
        except self.XenAPI.Failure, e:
            ret = None
            err_trace = e.details[-1]
            err_msg = err_trace.splitlines()[-1]
            strargs = str(args)
            if 'TIMEOUT:' in err_msg:
                LOG.error(_('TIMEOUT: The call to %(method)s timed out. '
                        'VM id=%(instance_id)s; args=%(strargs)s') % locals())
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
        vm = self._get_vm_opaque_ref(instance_or_vm)
        data = self._session.call_xenapi_request('VM.get_xenstore_data',
                (vm, ))
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
        vm = self._get_vm_opaque_ref(instance_or_vm)
        self.remove_from_param_xenstore(instance_or_vm, key)
        jsonval = json.dumps(val)
        self._session.call_xenapi_request('VM.add_to_xenstore_data',
                (vm, key, jsonval))

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
        vm = self._get_vm_opaque_ref(instance_or_vm)
        if isinstance(key_or_keys, basestring):
            keys = [key_or_keys]
        else:
            keys = key_or_keys
        for key in keys:
            self._session.call_xenapi_request('VM.remove_from_xenstore_data',
                    (vm, key))

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

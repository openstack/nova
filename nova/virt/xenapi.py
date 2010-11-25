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
A connection to XenServer or Xen Cloud Platform.

The concurrency model for this class is as follows:

All XenAPI calls are on a thread (using t.i.t.deferToThread, via the decorator
deferredToThread).  They are remote calls, and so may hang for the usual
reasons.  They should not be allowed to block the reactor thread.

All long-running XenAPI calls (VM.start, VM.reboot, etc) are called async
(using XenAPI.VM.async_start etc).  These return a task, which can then be
polled for completion.  Polling is handled using reactor.callLater.

This combination of techniques means that we don't block the reactor thread at
all, and at the same time we don't hold lots of threads waiting for
long-running operations.

FIXME: get_info currently doesn't conform to these rules, and will block the
reactor thread if the VM.get_by_name_label or VM.get_record calls block.

**Related Flags**

:xenapi_connection_url:  URL for connection to XenServer/Xen Cloud Platform.
:xenapi_connection_username:  Username for connection to XenServer/Xen Cloud
                              Platform (default: root).
:xenapi_connection_password:  Password for connection to XenServer/Xen Cloud
                              Platform.
:xenapi_task_poll_interval:  The interval (seconds) used for polling of
                             remote tasks (Async.VM.start, etc)
                             (default: 0.5).

"""

import logging
import xmlrpclib

from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import task

from nova import db
from nova import flags
from nova import process
from nova import utils
from nova.auth.manager import AuthManager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import images

from xml.dom.minidom import parseString


XenAPI = None


FLAGS = flags.FLAGS
flags.DEFINE_string('xenapi_connection_url',
                    None,
                    'URL for connection to XenServer/Xen Cloud Platform.'
                    ' Required if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_username',
                    'root',
                    'Username for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_password',
                    None,
                    'Password for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_float('xenapi_task_poll_interval',
                   0.5,
                   'The interval used for polling of remote tasks '
                   '(Async.VM.start, etc).  Used only if '
                   'connection_type=xenapi.')


XENAPI_POWER_STATE = {
    'Halted': power_state.SHUTDOWN,
    'Running': power_state.RUNNING,
    'Paused': power_state.PAUSED,
    'Suspended': power_state.SHUTDOWN, # FIXME
    'Crashed': power_state.CRASHED}


def get_connection(_):
    """Note that XenAPI doesn't have a read-only connection mode, so
    the read_only parameter is ignored."""
    # This is loaded late so that there's no need to install this
    # library when not using XenAPI.
    global XenAPI
    if XenAPI is None:
        XenAPI = __import__('XenAPI')
    url = FLAGS.xenapi_connection_url
    username = FLAGS.xenapi_connection_username
    password = FLAGS.xenapi_connection_password
    if not url or password is None:
        raise Exception('Must specify xenapi_connection_url, '
                        'xenapi_connection_username (optionally), and '
                        'xenapi_connection_password to use '
                        'connection_type=xenapi')
    return XenAPIConnection(url, username, password)


class XenAPIConnection(object):
    def __init__(self, url, user, pw):
        self._conn = XenAPI.Session(url)
        self._conn.login_with_password(user, pw)

    def list_instances(self):
        return [self._conn.xenapi.VM.get_name_label(vm) \
                for vm in self._conn.xenapi.VM.get_all()]

    @defer.inlineCallbacks
    def spawn(self, instance):
        vm = yield self._lookup(instance.name)
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' % 
                            instance.name)

        network = db.project_get_network(None, instance.project_id)
        network_ref = \
            yield self._find_network_with_bridge(network.bridge)

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        vdi_uuid = yield self._fetch_image(
            instance.image_id, user, project, True)
        kernel = yield self._fetch_image(
            instance.kernel_id, user, project, False)
        ramdisk = yield self._fetch_image(
            instance.ramdisk_id, user, project, False)
        vdi_ref = yield self._call_xenapi('VDI.get_by_uuid', vdi_uuid)

        vm_ref = yield self._create_vm(instance, kernel, ramdisk)
        yield self._create_vbd(vm_ref, vdi_ref, 0, True, True, False)
        if network_ref:
            yield self._create_vif(vm_ref, network_ref, instance.mac_address)
        logging.debug('Starting VM %s...', vm_ref)
        yield self._call_xenapi('VM.start', vm_ref, False, False)
        logging.info('Spawning VM %s created %s.', instance.name, vm_ref)

    @defer.inlineCallbacks
    def _create_vm(self, instance, kernel, ramdisk):
        """Create a VM record.  Returns a Deferred that gives the new
        VM reference."""

        instance_type = instance_types.INSTANCE_TYPES[instance.instance_type]
        mem = str(long(instance_type['memory_mb']) * 1024 * 1024)
        vcpus = str(instance_type['vcpus'])
        rec = {
            'name_label': instance.name,
            'name_description': '',
            'is_a_template': False,
            'memory_static_min': '0',
            'memory_static_max': mem,
            'memory_dynamic_min': mem,
            'memory_dynamic_max': mem,
            'VCPUs_at_startup': vcpus,
            'VCPUs_max': vcpus,
            'VCPUs_params': {},
            'actions_after_shutdown': 'destroy',
            'actions_after_reboot': 'restart',
            'actions_after_crash': 'destroy',
            'PV_bootloader': '',
            'PV_kernel': kernel,
            'PV_ramdisk': ramdisk,
            'PV_args': 'root=/dev/xvda1',
            'PV_bootloader_args': '',
            'PV_legacy_args': '',
            'HVM_boot_policy': '',
            'HVM_boot_params': {},
            'platform': {},
            'PCI_bus': '',
            'recommendations': '',
            'affinity': '',
            'user_version': '0',
            'other_config': {},
            }
        logging.debug('Created VM %s...', instance.name)
        vm_ref = yield self._call_xenapi('VM.create', rec)
        logging.debug('Created VM %s as %s.', instance.name, vm_ref)
        defer.returnValue(vm_ref)

    @defer.inlineCallbacks
    def _create_vdi(self, sr_ref, size, type, label, description, read_only, sharable):
        vdi_rec = {}
        vdi_rec['read_only'] = read_only
        vdi_rec['SR'] = sr_ref
        vdi_rec['virtual_size'] = str(size)
        vdi_rec['name_label'] = label
        vdi_rec['name_description'] = description 
        vdi_rec['sharable'] = sharable
        vdi_rec['type'] = type
        vdi_rec['other_config'] = {}
        vdi_ref = yield self._call_xenapi('VDI.create', vdi_rec)
        defer.returnValue(vdi_ref)

    @defer.inlineCallbacks
    def _create_vbd(self, vm_ref, vdi_ref, userdevice, bootable, unpluggable, empty):
        """Create a VBD record.  Returns a Deferred that gives the new
        VBD reference."""

        vbd_rec = {}
        vbd_rec['VM'] = vm_ref
        vbd_rec['VDI'] = vdi_ref
        vbd_rec['userdevice'] = str(userdevice)
        vbd_rec['bootable'] = bootable
        vbd_rec['mode'] = 'RW'
        vbd_rec['type'] = 'disk'
        vbd_rec['unpluggable'] = unpluggable
        vbd_rec['empty'] = empty
        vbd_rec['other_config'] = {}
        vbd_rec['qos_algorithm_type'] = ''
        vbd_rec['qos_algorithm_params'] = {}
        vbd_rec['qos_supported_algorithms'] = []
        logging.debug('Creating VBD for VM %s, VDI %s ... ', vm_ref, vdi_ref)
        vbd_ref = yield self._call_xenapi('VBD.create', vbd_rec)
        logging.debug('Created VBD %s for VM %s, VDI %s.', vbd_ref, vm_ref,
                      vdi_ref)
        defer.returnValue(vbd_ref)

    @defer.inlineCallbacks
    def _create_vif(self, vm_ref, network_ref, mac_address):
        """Create a VIF record.  Returns a Deferred that gives the new
        VIF reference."""

        vif_rec = {}
        vif_rec['device'] = '0'
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = mac_address
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        vif_rec['qos_algorithm_type'] = ''
        vif_rec['qos_algorithm_params'] = {}
        logging.debug('Creating VIF for VM %s, network %s ... ', vm_ref,
                      network_ref)
        vif_ref = yield self._call_xenapi('VIF.create', vif_rec)
        logging.debug('Created VIF %s for VM %s, network %s.', vif_ref,
                      vm_ref, network_ref)
        defer.returnValue(vif_ref)

    @defer.inlineCallbacks
    def _find_network_with_bridge(self, bridge):
        expr = 'field "bridge" = "%s"' % bridge
        networks = yield self._call_xenapi('network.get_all_records_where',
                                           expr)
        if len(networks) == 1:
            defer.returnValue(networks.keys()[0])
        elif len(networks) > 1:
            raise Exception('Found non-unique network for bridge %s' % bridge)
        else:
            raise Exception('Found no network for bridge %s' % bridge)

    @defer.inlineCallbacks
    def _fetch_image(self, image, user, project, use_sr):
        """use_sr: True to put the image as a VDI in an SR, False to place
        it on dom0's filesystem.  The former is for VM disks, the latter for
        its kernel and ramdisk (if external kernels are being used).
        Returns a Deferred that gives the new VDI UUID."""

        url = images.image_url(image)
        access = AuthManager().get_access_key(user, project)
        logging.debug("Asking xapi to fetch %s as %s" % (url, access))
        fn = use_sr and 'get_vdi' or 'get_kernel'
        args = {}
        args['src_url'] = url
        args['username'] = access
        args['password'] = user.secret
        if use_sr:
            args['add_partition'] = 'true'
        task = yield self._async_call_plugin('objectstore', fn, args)
        uuid = yield self._wait_for_task(task)
        defer.returnValue(uuid)

    @defer.inlineCallbacks
    def reboot(self, instance):
        vm = yield self._lookup(instance.name)
        if vm is None:
            raise Exception('instance not present %s' % instance.name)
        task = yield self._call_xenapi('Async.VM.clean_reboot', vm)
        yield self._wait_for_task(task)

    @defer.inlineCallbacks
    def destroy(self, instance):
        vm = yield self._lookup(instance.name)
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            defer.returnValue(None)
        # Get the VDIs related to the VM
        vdis = yield self._lookup_vm_vdis(vm)
        try:
            task = yield self._call_xenapi('Async.VM.hard_shutdown', vm)
            yield self._wait_for_task(task)
        except Exception, exc:
            logging.warn(exc)
        # Disk clean-up
        if vdis:
            for vdi in vdis:
                try:
                    task = yield self._call_xenapi('Async.VDI.destroy', vdi)
                    yield self._wait_for_task(task)
                except Exception, exc:
                    logging.warn(exc)
        try:
            task = yield self._call_xenapi('Async.VM.destroy', vm)
            yield self._wait_for_task(task)
        except Exception, exc:
            logging.warn(exc)

    @defer.inlineCallbacks
    def attach_volume(self, instance_name, device_path, mountpoint):
        # NOTE: No Resource Pool concept so far
        logging.debug("Attach_volume: %s, %s, %s",
                      instance_name, device_path, mountpoint)
        volume_info = _parse_volume_info(device_path, mountpoint)
        # Create the iSCSI SR, and the PDB through which hosts access SRs.
        # But first, retrieve target info, like Host, IQN, LUN and SCSIID
        target = yield self._get_target(volume_info)
        label = 'SR-%s' % volume_info['volumeId']
        description = 'Attached-to:%s' % instance_name
        # Create SR and check the physical space available for the VDI allocation 
        sr_ref = yield self._create_sr(target, label, description)
        disk_size = yield self._get_sr_available_space(sr_ref)
        # Create VDI  and attach VBD to VM
        vm_ref = yield self._lookup(instance_name)
        logging.debug("Mounting disk of: %s GB", (disk_size / (1024*1024*1024.0)))
        try:
            vdi_ref = yield self._create_vdi(sr_ref, disk_size,
                                             'user', volume_info['volumeId'], '',
                                             False, False)
        except Exception, exc:
            logging.warn(exc)
            if sr_ref:
                yield self._destroy_sr(sr_ref)
            raise Exception('Unable to create VDI on SR %s' % sr_ref)
        else:
            try: 
                userdevice = 2  # FIXME: this depends on the numbers of attached disks 
                vbd_ref = yield self._create_vbd(vm_ref, vdi_ref, userdevice, False, True, False)
                task = yield self._call_xenapi('Async.VBD.plug', vbd_ref)
                yield self._wait_for_task(task)
            except Exception, exc:
                logging.warn(exc)
                if sr_ref:
                    yield self._destroy_sr(sr_ref)
                raise Exception('Unable to create VBD on SR %s' % sr_ref)
        yield True

    @defer.inlineCallbacks
    def detach_volume(self, instance_name, mountpoint):
        logging.debug("Detach_volume: %s, %s, %s", instance_name, mountpoint)
        # Detach VBD from VM
        # Forget SR/PDB info associated with host
        # TODO: can we avoid destroying the SR every time we detach?
        yield True

    def get_info(self, instance_id):
        vm = self._lookup_blocking(instance_id)
        if vm is None:
            raise Exception('instance not present %s' % instance_id)
        rec = self._conn.xenapi.VM.get_record(vm)
        return {'state': XENAPI_POWER_STATE[rec['power_state']],
                'max_mem': long(rec['memory_static_max']) >> 10,
                'mem': long(rec['memory_dynamic_max']) >> 10,
                'num_cpu': rec['VCPUs_max'],
                'cpu_time': 0}

    def get_console_output(self, instance):
        return 'FAKE CONSOLE OUTPUT'

    @utils.deferredToThread
    def _lookup(self, i):
        return self._lookup_blocking(i)

    def _lookup_blocking(self, i):
        vms = self._conn.xenapi.VM.get_by_name_label(i)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise Exception('duplicate name found: %s' % i)
        else:
            return vms[0]

    @utils.deferredToThread
    def _get_target(self, volume_info):
        return self._get_target_blocking(volume_info)

    def _get_target_blocking(self, volume_info):
        target = {}
        target['target'] = volume_info['targetHost']
        target['port'] = volume_info['targetPort']
        target['targetIQN'] = volume_info['iqn']
        # We expect SR_BACKEND_FAILURE_107 to retrieve params to create the SR
        try:
            self._conn.xenapi.SR.create(self._get_xenapi_host(),
                                        target, '-1', '', '',
                                        'lvmoiscsi', '', False, {})
        except XenAPI.Failure, exc:
            if exc.details[0] == 'SR_BACKEND_FAILURE_107':
                xml_response = parseString(exc.details[3])
                isciTargets = xml_response.getElementsByTagName('iscsi-target')
                # Make sure that only the correct Lun is visible
                if len(isciTargets) > 1:
                    raise Exception('More than one ISCSI Target available')
                isciLuns = isciTargets.item(0).getElementsByTagName('LUN')
                if len(isciLuns) > 1:
                    raise Exception('More than one ISCSI Lun available')
                # Parse params from the xml response into the dictionary
                for n in isciLuns.item(0).childNodes:
                    if n.nodeType == 1:
                        target[n.nodeName] = str(n.firstChild.data).strip()
        return target
        
    @utils.deferredToThread
    def _get_sr_available_space(self, sr_ref):
        return self._get_sr_available_space_blocking(sr_ref)

    def _get_sr_available_space_blocking(self, sr_ref):
        pu = self._conn.xenapi.SR.get_physical_utilisation(sr_ref)
        ps = self._conn.xenapi.SR.get_physical_size(sr_ref)
        return (int(ps) - int(pu)) - (8 * 1024 * 1024)

    @utils.deferredToThread
    def _create_sr(self, target, label, description):
        return self._create_sr_blocking(target, label, description)

    def _create_sr_blocking(self, target, label, description):
        # TODO: we might want to put all these string literals into constants
        sr_ref = self._conn.xenapi.SR.create(self._get_xenapi_host(),
                                         target,
                                         target['size'],
                                         label,
                                         description,
                                         'lvmoiscsi',
                                         '',
                                         True, {})
        # TODO: there might be some timing issues here
        self._conn.xenapi.SR.scan(sr_ref)
        return sr_ref

    @defer.inlineCallbacks
    def _destroy_sr(self, sr_ref):
        # Some clean-up depending on the state of the SR
        #yield self._destroy_vdbs(sr_ref)
        #yield self._destroy_vdis(sr_ref)
        # Destroy PDBs
        pbds = yield self._conn.xenapi.SR.get_PBDs(sr_ref)
        for pbd_ref in pbds:
            try:
                task = yield self._call_xenapi('Async.PBD.unplug', pbd_ref)
                yield self._wait_for_task(task)
            except Exception, exc:
                logging.warn(exc)
            else:
                task = yield self._call_xenapi('Async.PBD.destroy', pbd_ref)
                yield self._wait_for_task(task)
        # Forget SR
        try:
            task = yield self._call_xenapi('Async.SR.forget', sr_ref)
            yield self._wait_for_task(task)
        except Exception, exc:
            logging.warn(exc)
            
    @utils.deferredToThread
    def _lookup_vm_vdis(self, vm):
        return self._lookup_vm_vdis_blocking(vm)

    def _lookup_vm_vdis_blocking(self, vm):
        # Firstly we get the VBDs, then the VDIs.
        # TODO: do we leave the read-only devices?
        vbds = self._conn.xenapi.VM.get_VBDs(vm)
        vdis = []
        if vbds:
            for vbd in vbds:
                try:
                    vdi = self._conn.xenapi.VBD.get_VDI(vbd)
                    # Test valid VDI
                    record = self._conn.xenapi.VDI.get_record(vdi)
                except Exception, exc:
                    logging.warn(exc)
                else:
                    vdis.append(vdi)
            if len(vdis) > 0:
                return vdis
            else:
                return None

    def _wait_for_task(self, task):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes."""
        d = defer.Deferred()
        reactor.callLater(0, self._poll_task, task, d)
        return d

    @utils.deferredToThread
    def _poll_task(self, task, deferred):
        """Poll the given XenAPI task, and fire the given Deferred if we
        get a result."""
        try:
            #logging.debug('Polling task %s...', task)
            status = self._conn.xenapi.task.get_status(task)
            if status == 'pending':
                reactor.callLater(FLAGS.xenapi_task_poll_interval,
                                  self._poll_task, task, deferred)
            elif status == 'success':
                result = self._conn.xenapi.task.get_result(task)
                logging.info('Task %s status: success.  %s', task, result)
                deferred.callback(_parse_xmlrpc_value(result))
            else:
                error_info = self._conn.xenapi.task.get_error_info(task)
                logging.warn('Task %s status: %s.  %s', task, status,
                             error_info)
                deferred.errback(XenAPI.Failure(error_info))
            #logging.debug('Polling task %s done.', task)
        except Exception, exc:
            logging.warn(exc)
            deferred.errback(exc)

    @utils.deferredToThread
    def _call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread.  Returns
        a Deferred for the result."""
        f = self._conn.xenapi
        for m in method.split('.'):
            f = f.__getattr__(m)
        return f(*args)

    @utils.deferredToThread
    def _async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread.  Returns a
        Deferred with the task reference."""
        return _unwrap_plugin_exceptions(
            self._conn.xenapi.Async.host.call_plugin,
            self._get_xenapi_host(), plugin, fn, args)

    def _get_xenapi_host(self):
        return self._conn.xenapi.session.get_this_host(self._conn.handle)


def _unwrap_plugin_exceptions(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, exc:
        logging.debug("Got exception: %s", exc)
        if (len(exc.details) == 4 and
            exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
            exc.details[2] == 'Failure'):
            params = None
            try:
                params = eval(exc.details[3])
            except:
                raise exc
            raise XenAPI.Failure(params)
        else:
            raise
    except xmlrpclib.ProtocolError, exc:
        logging.debug("Got exception: %s", exc)
        raise


def _parse_xmlrpc_value(val):
    """Parse the given value as if it were an XML-RPC value.  This is
    sometimes used as the format for the task.result field."""
    if not val:
        return val
    x = xmlrpclib.loads(
        '<?xml version="1.0"?><methodResponse><params><param>' + 
        val + 
        '</param></params></methodResponse>')
    return x[0][0]


def _parse_volume_info(device_path, mountpoint):
    volume_info = {}
    volume_info['volumeId'] = 'vol-qurmrzn9'
    # Because XCP/XS want an x beforehand
    volume_info['xenMountpoint'] = '/dev/xvdc'
    volume_info['targetHost'] = ''
    volume_info['targetPort'] = '3260'  # default 3260
    volume_info['iqn'] = 'iqn.2010-10.org.openstack:vol-qurmrzn9'
    return volume_info

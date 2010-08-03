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
"""

import logging
import xmlrpclib

from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import flags
from nova import process
from nova.auth.manager import AuthManager
from nova.compute import power_state
from nova.virt import images

XenAPI = None

FLAGS = flags.FLAGS
flags.DEFINE_string('xenapi_connection_url',
                    None,
                    'URL for connection to XenServer/Xen Cloud Platform.  Required if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_username',
                    'root',
                    'Username for connection to XenServer/Xen Cloud Platform.  Used only if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_password',
                    None,
                    'Password for connection to XenServer/Xen Cloud Platform.  Used only if connection_type=xenapi.')


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
        raise Exception('Must specify xenapi_connection_url, xenapi_connection_username (optionally), and xenapi_connection_password to use connection_type=xenapi') 
    return XenAPIConnection(url, username, password)


class XenAPIConnection(object):

    def __init__(self, url, user, pw):
        self._conn = XenAPI.Session(url)
        self._conn.login_with_password(user, pw)

    def list_instances(self):
        result = [self._conn.xenapi.VM.get_name_label(vm) \
                  for vm in self._conn.xenapi.VM.get_all()]

    @defer.inlineCallbacks
    @exception.wrap_exception
    def spawn(self, instance):
        vm = yield self.lookup(instance.name)
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' %
                            instance.name)

        if 'bridge_name' in instance.datamodel:
            network_ref = \
                yield self._find_network_with_bridge(
                    instance.datamodel['bridge_name'])
        else:
            network_ref = None

        if 'mac_address' in instance.datamodel:
            mac_address = instance.datamodel['mac_address']
        else:
            mac_address = ''

        user = AuthManager().get_user(instance.datamodel['user_id'])
        vdi_uuid = yield self.fetch_image(
            instance.datamodel['image_id'], user, True)
        kernel = yield self.fetch_image(
            instance.datamodel['kernel_id'], user, False)
        ramdisk = yield self.fetch_image(
            instance.datamodel['ramdisk_id'], user, False)
        vdi_ref = yield self._conn.xenapi.VDI.get_by_uuid(vdi_uuid)

        vm_ref = yield self.create_vm(instance, kernel, ramdisk)
        yield self.create_vbd(vm_ref, vdi_ref, 0, True)
        if network_ref:
            yield self._create_vif(vm_ref, network_ref, mac_address)
        yield self._conn.xenapi.VM.start(vm_ref, False, False)


    def create_vm(self, instance, kernel, ramdisk):
        mem = str(long(instance.datamodel['memory_kb']) * 1024)
        vcpus = str(instance.datamodel['vcpus'])
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
        vm_ref = self._conn.xenapi.VM.create(rec)
        logging.debug('Created VM %s as %s.', instance.name, vm_ref)
        return vm_ref


    def create_vbd(self, vm_ref, vdi_ref, userdevice, bootable):
        vbd_rec = {}
        vbd_rec['VM'] = vm_ref
        vbd_rec['VDI'] = vdi_ref
        vbd_rec['userdevice'] = str(userdevice)
        vbd_rec['bootable'] = bootable
        vbd_rec['mode'] = 'RW'
        vbd_rec['type'] = 'disk'
        vbd_rec['unpluggable'] = True
        vbd_rec['empty'] = False
        vbd_rec['other_config'] = {}
        vbd_rec['qos_algorithm_type'] = ''
        vbd_rec['qos_algorithm_params'] = {}
        vbd_rec['qos_supported_algorithms'] = []
        logging.debug('Creating VBD for VM %s, VDI %s ... ', vm_ref, vdi_ref)
        vbd_ref = self._conn.xenapi.VBD.create(vbd_rec)
        logging.debug('Created VBD %s for VM %s, VDI %s.', vbd_ref, vm_ref,
                      vdi_ref)
        return vbd_ref


    def _create_vif(self, vm_ref, network_ref, mac_address):
        vif_rec = {}
        vif_rec['device'] = '0'
        vif_rec['network']= network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = mac_address
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        vif_rec['qos_algorithm_type'] = ''
        vif_rec['qos_algorithm_params'] = {}
        logging.debug('Creating VIF for VM %s, network %s ... ', vm_ref,
                      network_ref)
        vif_ref = self._conn.xenapi.VIF.create(vif_rec)
        logging.debug('Created VIF %s for VM %s, network %s.', vif_ref,
                      vm_ref, network_ref)
        return vif_ref


    def _find_network_with_bridge(self, bridge):
        expr = 'field "bridge" = "%s"' % bridge
        networks = self._conn.xenapi.network.get_all_records_where(expr)
        if len(networks) == 1:
            return networks.keys()[0]
        elif len(networks) > 1:
            raise Exception('Found non-unique network for bridge %s' % bridge)
        else:
            raise Exception('Found no network for bridge %s' % bridge)


    def fetch_image(self, image, user, use_sr):
        """use_sr: True to put the image as a VDI in an SR, False to place
        it on dom0's filesystem.  The former is for VM disks, the latter for
        its kernel and ramdisk (if external kernels are being used)."""

        url = images.image_url(image)
        logging.debug("Asking xapi to fetch %s as %s" % (url, user.access))
        fn = use_sr and 'get_vdi' or 'get_kernel'
        args = {}
        args['src_url'] = url
        args['username'] = user.access
        args['password'] = user.secret
        if use_sr:
            args['add_partition'] = 'true'
        return self._call_plugin('objectstore', fn, args)


    def reboot(self, instance):
        vm = self.lookup(instance.name)
        if vm is None:
            raise Exception('instance not present %s' % instance.name)
        yield self._conn.xenapi.VM.clean_reboot(vm)

    def destroy(self, instance):
        vm = self.lookup(instance.name)
        if vm is None:
            raise Exception('instance not present %s' % instance.name)
        yield self._conn.xenapi.VM.destroy(vm)

    def get_info(self, instance_id):
        vm = self.lookup(instance_id)
        if vm is None:
            raise Exception('instance not present %s' % instance_id)
        rec = self._conn.xenapi.VM.get_record(vm)
        return {'state': power_state_from_xenapi[rec['power_state']],
                'max_mem': long(rec['memory_static_max']) >> 10,
                'mem': long(rec['memory_dynamic_max']) >> 10,
                'num_cpu': rec['VCPUs_max'],
                'cpu_time': 0}

    def lookup(self, i):
        vms = self._conn.xenapi.VM.get_by_name_label(i)
        n = len(vms) 
        if n == 0:
            return None
        elif n > 1:
            raise Exception('duplicate name found: %s' % i)
        else:
            return vms[0]


    def _call_plugin(self, plugin, fn, args):
        return _unwrap_plugin_exceptions(
            self._conn.xenapi.host.call_plugin,
            self._get_xenapi_host(), plugin, fn, args)


    def _get_xenapi_host(self):
        return self._conn.xenapi.session.get_this_host(self._conn.handle)


power_state_from_xenapi = {
    'Halted'   : power_state.SHUTDOWN,
    'Running'  : power_state.RUNNING,
    'Paused'   : power_state.PAUSED,
    'Suspended': power_state.SHUTDOWN, # FIXME
    'Crashed'  : power_state.CRASHED
}


def _unwrap_plugin_exceptions(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, exn:
        logging.debug("Got exception: %s", exn)
        if (len(exn.details) == 4 and
            exn.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
            exn.details[2] == 'Failure'):
            params = None
            try:
                params = eval(exn.details[3])
            except:
                raise exn
            raise XenAPI.Failure(params)
        else:
            raise
    except xmlrpclib.ProtocolError, exn:
        logging.debug("Got exception: %s", exn)
        raise

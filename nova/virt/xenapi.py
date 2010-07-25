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

from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import flags
from nova import process
from nova.compute import power_state

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
        vm = self.lookup(instance.name)
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' %
                            instance.name)
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
            'PV_kernel': instance.datamodel['kernel_id'],
            'PV_ramdisk': instance.datamodel['ramdisk_id'],
            'PV_args': '',
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
        vm = yield self._conn.xenapi.VM.create(rec)
        #yield self._conn.xenapi.VM.start(vm, False, False)


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
            raise Exception('instance not present %s' % instance.name)
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

    power_state_from_xenapi = {
        'Halted'   : power_state.RUNNING, #FIXME
        'Running'  : power_state.RUNNING,
        'Paused'   : power_state.PAUSED,
        'Suspended': power_state.SHUTDOWN, # FIXME
        'Crashed'  : power_state.CRASHED
    }

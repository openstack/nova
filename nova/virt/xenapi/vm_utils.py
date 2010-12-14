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
Helper methods for operations related to the management of VM records and
their attributes like VDIs, VIFs, as well as their lookup functions.
"""

import logging
import XenAPI

from twisted.internet import defer

from nova import utils
from nova.auth.manager import AuthManager
from nova.compute import instance_types
from nova.virt import images
from nova.compute import power_state

XENAPI_POWER_STATE = {
    'Halted': power_state.SHUTDOWN,
    'Running': power_state.RUNNING,
    'Paused': power_state.PAUSED,
    'Suspended': power_state.SHUTDOWN,  # FIXME
    'Crashed': power_state.CRASHED}


class VMHelper():
    """
    The class that wraps the helper methods together.
    """
    def __init__(self):
        return

    @classmethod
    @defer.inlineCallbacks
    def create_vm(cls, session, instance, kernel, ramdisk,pv_kernel=False):
        """Create a VM record.  Returns a Deferred that gives the new
        VM reference.
        the pv_kernel flag indicates whether the guest is HVM or PV
        """

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
            'PV_kernel': '',
            'PV_ramdisk': '',
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
        #TODO: if there is no kernel we need to call a plugin to understand whether 
        #the VM should be launched as PV or HVM
        if (instance.kernel_id):
            logging.debug("A kernel (and hopefully a ramdisk) have been provided")
            rec['PV_bootloader'] = ''
            rec['PV_kernel'] = kernel
            rec['PV_ramdisk'] = ramdisk
            rec['PV_args'] = 'root=/dev/xvda1'
            rec['PV_bootloader_args'] = ''
            rec['PV_legacy_args'] = ''
        else:
            logging.debug("This a raw image")
            if (pv_kernel):
                rec['PV_args'] = 'noninteractive'
                rec['PV_bootloader'] = 'pygrub'    
            else:
                rec['HVM_boot_policy'] = 'BIOS order'
                rec['HVM_boot_params'] = {'order': 'dc'}
                rec['platform']={'acpi':'true','apic':'true','pae':'true','viridian':'true'}
        logging.debug('Created VM %s...', instance.name)
        vm_ref = yield session.call_xenapi('VM.create', rec)
        logging.debug('Created VM %s as %s.', instance.name, vm_ref)
        defer.returnValue(vm_ref)

    @classmethod
    @defer.inlineCallbacks
    def create_vbd(cls, session, vm_ref, vdi_ref, userdevice, bootable):
        """Create a VBD record.  Returns a Deferred that gives the new
        VBD reference."""

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
        vbd_ref = yield session.call_xenapi('VBD.create', vbd_rec)
        logging.debug('Created VBD %s for VM %s, VDI %s.', vbd_ref, vm_ref,
                      vdi_ref)
        defer.returnValue(vbd_ref)

    @classmethod
    @defer.inlineCallbacks
    def create_vif(cls, session, vm_ref, network_ref, mac_address):
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
        vif_ref = yield session.call_xenapi('VIF.create', vif_rec)
        logging.debug('Created VIF %s for VM %s, network %s.', vif_ref,
                      vm_ref, network_ref)
        defer.returnValue(vif_ref)

    @classmethod
    @defer.inlineCallbacks
    def fetch_image(cls, session, image, user, project, type):
        """type: integer field for specifying how to handle the image
            0 - kernel/ramdisk image (goes on dom0's filesystem)
            1 - disk image (local SR, partitioned by objectstore plugin)
            2 - raw disk image (local SR, NOT partitioned by objectstor plugin)"""
            
        url = images.image_url(image)
        access = AuthManager().get_access_key(user, project)
        logging.debug("Asking xapi to fetch %s as %s", url, access)
        logging.debug("Salvatore: image type = %d",type)
        fn = (type<>0) and 'get_vdi' or 'get_kernel'
        logging.debug("Salvatore: fn=%s",fn)
        args = {}
        args['src_url'] = url
        args['username'] = access
        args['password'] = user.secret
        args['add_partition']='false'
        args['raw']='false'
        if type<>0:
            args['add_partition'] = 'true'
            if type==2:
                args['raw']='true'    
        logging.debug("Salvatore: args['raw']=%s",args['raw'])
        logging.debug("Salvatore: args['add_partition']=%s",args['add_partition'])
        task = yield session.async_call_plugin('objectstore', fn, args)
        uuid = yield session.wait_for_task(task)
        defer.returnValue(uuid)

    @classmethod
    @defer.inlineCallbacks
    def lookup_image(cls, session, vdi_ref):
        logging.debug("Looking up vdi %s for PV kernel",vdi_ref)
        fn="is_vdi_pv"
        args={}
        args['vdi-ref']=vdi_ref
        #TODO: Call proper function in plugin
        task = yield session.async_call_plugin('objectstore', fn, args)
        logging.debug("Waiting for task completion")
        pv=yield session.wait_for_task(task)
        logging.debug("PV Kernel in VDI:%d",pv)
        defer.returnValue(pv)

    @classmethod
    @utils.deferredToThread
    def lookup(cls, session, i):
        """ Look the instance i up, and returns it if available """
        return VMHelper.lookup_blocking(session, i)

    @classmethod
    def lookup_blocking(cls, session, i):
        """ Synchronous lookup """
        vms = session.get_xenapi().VM.get_by_name_label(i)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise Exception('duplicate name found: %s' % i)
        else:
            return vms[0]

    @classmethod
    @utils.deferredToThread
    def lookup_vm_vdis(cls, session, vm):
        """ Look for the VDIs that are attached to the VM """
        return VMHelper.lookup_vm_vdis_blocking(session, vm)

    @classmethod
    def lookup_vm_vdis_blocking(cls, session, vm):
        """ Synchronous lookup_vm_vdis """
        # Firstly we get the VBDs, then the VDIs.
        # TODO(Armando): do we leave the read-only devices?
        vbds = session.get_xenapi().VM.get_VBDs(vm)
        vdis = []
        if vbds:
            for vbd in vbds:
                try:
                    vdi = session.get_xenapi().VBD.get_VDI(vbd)
                    # Test valid VDI
                    record = session.get_xenapi().VDI.get_record(vdi)
                    logging.debug('VDI %s is still available', record['uuid'])
                except XenAPI.Failure, exc:
                    logging.warn(exc)
                else:
                    vdis.append(vdi)
            if len(vdis) > 0:
                return vdis
            else:
                return None

    @classmethod
    def compile_info(cls, record):
        return {'state': XENAPI_POWER_STATE[record['power_state']],
                'max_mem': long(record['memory_static_max']) >> 10,
                'mem': long(record['memory_dynamic_max']) >> 10,
                'num_cpu': record['VCPUs_max'],
                'cpu_time': 0}

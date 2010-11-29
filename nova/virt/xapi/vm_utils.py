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

from twisted.internet import defer

from nova import utils

from novadeps import Instance
from novadeps import Image
from novadeps import User


class VMHelper():
    def __init__(self, session):
        return
    
    @classmethod
    @defer.inlineCallbacks
    def create_vm(self, session, instance, kernel, ramdisk):
        """Create a VM record.  Returns a Deferred that gives the new
        VM reference."""

        instance_type = Instance.get_type(instance)
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
        logging.debug('Created VM %s...', Instance.get_name(instance))
        vm_ref = yield session.call_xenapi('VM.create', rec)
        logging.debug('Created VM %s as %s.',
                      Instance.get_name(instance), vm_ref)
        defer.returnValue(vm_ref)

    @classmethod
    @defer.inlineCallbacks
    def create_vbd(self, session, vm_ref, vdi_ref, userdevice, bootable):
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
    def create_vif(self, session, vm_ref, network_ref, mac_address):
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
    def fetch_image(self, session, image, user, project, use_sr):
        """use_sr: True to put the image as a VDI in an SR, False to place
        it on dom0's filesystem.  The former is for VM disks, the latter for
        its kernel and ramdisk (if external kernels are being used).
        Returns a Deferred that gives the new VDI UUID."""

        url = Image.get_url(image)
        access = User.get_access(user, project)
        logging.debug("Asking xapi to fetch %s as %s" % (url, access))
        fn = use_sr and 'get_vdi' or 'get_kernel'
        args = {}
        args['src_url'] = url
        args['username'] = access
        args['password'] = User.get_secret(user)
        if use_sr:
            args['add_partition'] = 'true'
        task = yield session.async_call_plugin('objectstore', fn, args)
        uuid = yield session.wait_for_task(task)
        defer.returnValue(uuid)

    @classmethod
    @utils.deferredToThread
    def lookup(self, session, i):
        return VMHelper.lookup_blocking(session, i)

    @classmethod
    def lookup_blocking(self, session, i):
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
    def lookup_vm_vdis(self, session, vm):
        return VMHelper.lookup_vm_vdis_blocking(session, vm)

    @classmethod
    def lookup_vm_vdis_blocking(self, session, vm):
        # Firstly we get the VBDs, then the VDIs.
        # TODO: do we leave the read-only devices?
        vbds = session.get_xenapi().VM.get_VBDs(vm)
        vdis = []
        if vbds:
            for vbd in vbds:
                try:
                    vdi = session.get_xenapi().VBD.get_VDI(vbd)
                    # Test valid VDI
                    record = session.get_xenapi().VDI.get_record(vdi)
                except Exception, exc:
                    logging.warn(exc)
                else:
                    vdis.append(vdi)
            if len(vdis) > 0:
                return vdis
            else:
                return None

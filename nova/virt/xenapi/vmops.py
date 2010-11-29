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
import xmlrpclib

from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import task

import VMHelper
import NetworkHelper

from novadeps import XENAPI_POWER_STATE
from novadeps import Auth
from novadeps import Instance
from novadeps import Network

class VMOps(object):
    def __init__(self, session):
        self._session = session
    
    def list_instances(self):
        return [self._session.get_xenapi().VM.get_name_label(vm) \
                for vm in self._session.get_xenapi().VM.get_all()]

    @defer.inlineCallbacks
    def spawn(self, instance):
        vm = yield VMHelper.lookup(self._session, Instance.get_name(instance))
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' %
                            Instance.get_name(instance))

        network = Instance.get_network(instance)
        network_ref = \
            yield NetworkHelper.find_network_with_bridge(self._session, Network.get_bridge(network))

        user = Instance.get_user(instance)
        project = Instance.get_project(instance)
        vdi_uuid = yield VMHelper.fetch_image(self._session,
            Instance.get_image_id(instance), user, project, True)
        kernel = yield VMHelper.fetch_image(self._session,
            Instance.get_kernel_id(instance), user, project, False)
        ramdisk = yield VMHelper.fetch_image(self._session,
            Instance.get_ramdisk_id(instance), user, project, False)
        vdi_ref = yield self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)

        vm_ref = yield VMHelper.create_vm(self._session, instance, kernel, ramdisk)
        yield VMHelper.create_vbd(self._session, vm_ref, vdi_ref, 0, True)
        if network_ref:
            yield VMHelper.create_vif(self._session, vm_ref, network_ref, Instance.get_mac(instance))
        logging.debug('Starting VM %s...', vm_ref)
        yield self._session.call_xenapi('VM.start', vm_ref, False, False)
        logging.info('Spawning VM %s created %s.', Instance.get_name(instance), vm_ref)

    @defer.inlineCallbacks
    def reboot(self, instance):
        instance_name = Instance.get_name(instance)
        vm = yield VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception('instance not present %s' % instance_name)
        task = yield self._session.call_xenapi('Async.VM.clean_reboot', vm)
        yield self._session.wait_for_task(task)

    @defer.inlineCallbacks
    def destroy(self, instance):
        vm = yield VMHelper.lookup(self._session, Instance.get_name(instance))
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            defer.returnValue(None)
        # Get the VDIs related to the VM
        vdis = yield VMHelper.lookup_vm_vdis(self._session, vm)
        try:
            task = yield self._session.call_xenapi('Async.VM.hard_shutdown', vm)
            yield self._session.wait_for_task(task)
        except Exception, exc:
            logging.warn(exc)
        # Disk clean-up
        if vdis:
            for vdi in vdis:
                try:
                    task = yield self._session.call_xenapi('Async.VDI.destroy', vdi)
                    yield self._session.wait_for_task(task)
                except Exception, exc:
                    logging.warn(exc)
        try:
            task = yield self._session.call_xenapi('Async.VM.destroy', vm)
            yield self._session.wait_for_task(task)
        except Exception, exc:
            logging.warn(exc)

    def get_info(self, instance_id):
        vm = VMHelper.lookup_blocking(self._session, instance_id)
        if vm is None:
            raise Exception('instance not present %s' % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return {'state': XENAPI_POWER_STATE[rec['power_state']],
                'max_mem': long(rec['memory_static_max']) >> 10,
                'mem': long(rec['memory_dynamic_max']) >> 10,
                'num_cpu': rec['VCPUs_max'],
                'cpu_time': 0}

    def get_console_output(self, instance):
        return 'FAKE CONSOLE OUTPUT'
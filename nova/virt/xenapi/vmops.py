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

from twisted.internet import defer

from nova import db
from nova import context
from nova import exception

from nova.auth.manager import AuthManager
from nova.virt.xenapi.network_utils import NetworkHelper
from nova.virt.xenapi.vm_utils import VMHelper


class VMOps(object):
    """
    Management class for VM-related tasks
    """
    def __init__(self, session):
        self.XenAPI = __import__('XenAPI')
        self._session = session
        # Load XenAPI module in the helper class
        VMHelper.late_import()

    def list_instances(self):
        """ List VM instances """
        return [self._session.get_xenapi().VM.get_name_label(vm) \
                for vm in self._session.get_xenapi().VM.get_all()]

    @defer.inlineCallbacks
    def spawn(self, instance):
        """ Create VM instance """
        vm = yield VMHelper.lookup(self._session, instance.name)
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' %
                            instance.name)

        bridge = db.project_get_network(context.get_admin_context(),
                                      instance.project_id).bridge
        network_ref = \
            yield NetworkHelper.find_network_with_bridge(self._session, bridge)

        user = AuthManager().get_user(instance.user_id)
        project = AuthManager().get_project(instance.project_id)
        vdi_uuid = yield VMHelper.fetch_image(self._session,
            instance.image_id, user, project, True)
        kernel = yield VMHelper.fetch_image(self._session,
            instance.kernel_id, user, project, False)
        ramdisk = yield VMHelper.fetch_image(self._session,
            instance.ramdisk_id, user, project, False)
        vdi_ref = yield self._session.call_xenapi('VDI.get_by_uuid', vdi_uuid)
        vm_ref = yield VMHelper.create_vm(self._session,
                                          instance, kernel, ramdisk)
        yield VMHelper.create_vbd(self._session, vm_ref, vdi_ref, 0, True)
        if network_ref:
            yield VMHelper.create_vif(self._session, vm_ref,
                                      network_ref, instance.mac_address)
        logging.debug('Starting VM %s...', vm_ref)
        yield self._session.call_xenapi('VM.start', vm_ref, False, False)
        logging.info('Spawning VM %s created %s.', instance.name,
                     vm_ref)

    @defer.inlineCallbacks
    def reboot(self, instance):
        """ Reboot VM instance """
        instance_name = instance.name
        vm = yield VMHelper.lookup(self._session, instance_name)
        if vm is None:
            raise Exception('instance not present %s' % instance_name)
        task = yield self._session.call_xenapi('Async.VM.clean_reboot', vm)
        yield self._session.wait_for_task(task)

    @defer.inlineCallbacks
    def destroy(self, instance):
        """ Destroy VM instance """
        vm = yield VMHelper.lookup(self._session, instance.name)
        if vm is None:
            # Don't complain, just return.  This lets us clean up instances
            # that have already disappeared from the underlying platform.
            defer.returnValue(None)
        # Get the VDIs related to the VM
        vdis = yield VMHelper.lookup_vm_vdis(self._session, vm)
        try:
            task = yield self._session.call_xenapi('Async.VM.hard_shutdown',
                                                   vm)
            yield self._session.wait_for_task(task)
        except self.XenAPI.Failure, exc:
            logging.warn(exc)
        # Disk clean-up
        if vdis:
            for vdi in vdis:
                try:
                    task = yield self._session.call_xenapi('Async.VDI.destroy',
                                                           vdi)
                    yield self._session.wait_for_task(task)
                except self.XenAPI.Failure, exc:
                    logging.warn(exc)
        try:
            task = yield self._session.call_xenapi('Async.VM.destroy', vm)
            yield self._session.wait_for_task(task)
        except self.XenAPI.Failure, exc:
            logging.warn(exc)

    def get_info(self, instance_id):
        """ Return data about VM instance """
        vm = VMHelper.lookup_blocking(self._session, instance_id)
        if vm is None:
            raise exception.NotFound('Instance not found %s' % instance_id)
        rec = self._session.get_xenapi().VM.get_record(vm)
        return VMHelper.compile_info(rec)

    @defer.inlineCallbacks
    def get_diagnostics(self, instance_id):
        """Return data about VM diagnostics"""
        vm = yield VMHelper.lookup(self._session, instance_id)
        if vm is None:
            raise Exception("instance not present %s" % instance_id)
        rec = yield self._session.get_xenapi().VM.get_record(vm)
        defer.returnValue(VMHelper.compile_diagnostics(self._session, rec))

    def get_console_output(self, instance):
        """ Return snapshot of console """
        # TODO: implement this to fix pylint!
        return 'FAKE CONSOLE OUTPUT of instance'

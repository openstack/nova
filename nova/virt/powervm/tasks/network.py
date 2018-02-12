# Copyright 2015, 2017 IBM Corp.
#
# All Rights Reserved.
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

import eventlet
from oslo_log import log as logging
from pypowervm.tasks import cna as pvm_cna
from pypowervm.wrappers import managed_system as pvm_ms
from pypowervm.wrappers import network as pvm_net
from taskflow import task

from nova import conf as cfg
from nova import exception
from nova.virt.powervm import vif
from nova.virt.powervm import vm

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

SECURE_RMC_VSWITCH = 'MGMTSWITCH'
SECURE_RMC_VLAN = 4094


class PlugVifs(task.Task):

    """The task to plug the Virtual Network Interfaces to a VM."""

    def __init__(self, virt_api, adapter, instance, network_infos):
        """Create the task.

        Provides 'vm_cnas' - the list of the Virtual Machine's Client Network
        Adapters as they stand after all VIFs are plugged.  May be None, in
        which case the Task requiring 'vm_cnas' should discover them afresh.

        :param virt_api: The VirtAPI for the operation.
        :param adapter: The pypowervm adapter.
        :param instance: The nova instance.
        :param network_infos: The network information containing the nova
                              VIFs to create.
        """
        self.virt_api = virt_api
        self.adapter = adapter
        self.instance = instance
        self.network_infos = network_infos or []
        self.crt_network_infos, self.update_network_infos = [], []
        # Cache of CNAs that is filled on initial _vif_exists() call.
        self.cnas = None

        super(PlugVifs, self).__init__(
            name='plug_vifs', provides='vm_cnas', requires=['lpar_wrap'])

    def _vif_exists(self, network_info):
        """Does the instance have a CNA for a given net?

        :param network_info: A network information dict.  This method expects
                             it to contain key 'address' (MAC address).
        :return: True if a CNA with the network_info's MAC address exists on
                 the instance.  False otherwise.
        """
        if self.cnas is None:
            self.cnas = vm.get_cnas(self.adapter, self.instance)
        vifs = self.cnas

        return network_info['address'] in [vm.norm_mac(v.mac) for v in vifs]

    def execute(self, lpar_wrap):
        # Check to see if the LPAR is OK to add VIFs to.
        modifiable, reason = lpar_wrap.can_modify_io()
        if not modifiable:
            LOG.error("Unable to create VIF(s) for instance in the system's "
                      "current state. The reason from the system is: %s",
                      reason, instance=self.instance)
            raise exception.VirtualInterfaceCreateException()

        # We will have two types of network infos.  One is for newly created
        # vifs.  The others are those that exist, but should be re-'treated'
        for network_info in self.network_infos:
            if self._vif_exists(network_info):
                self.update_network_infos.append(network_info)
            else:
                self.crt_network_infos.append(network_info)

        # If there are no vifs to create or update, then just exit immediately.
        if not self.crt_network_infos and not self.update_network_infos:
            return []

        # For existing VIFs that we just need to update, run the plug but do
        # not wait for the neutron event as that likely won't be sent (it was
        # already done).
        for network_info in self.update_network_infos:
            LOG.info("Updating VIF with mac %s for instance.",
                     network_info['address'], instance=self.instance)
            vif.plug(self.adapter, self.instance, network_info, new_vif=False)

        # For the new VIFs, run the creates (and wait for the events back)
        try:
            with self.virt_api.wait_for_instance_event(
                    self.instance, self._get_vif_events(),
                    deadline=CONF.vif_plugging_timeout,
                    error_callback=self._vif_callback_failed):
                for network_info in self.crt_network_infos:
                    LOG.info('Creating VIF with mac %s for instance.',
                             network_info['address'], instance=self.instance)
                    new_vif = vif.plug(
                        self.adapter, self.instance, network_info,
                        new_vif=True)
                    if self.cnas is not None:
                        self.cnas.append(new_vif)
        except eventlet.timeout.Timeout:
            LOG.error('Error waiting for VIF to be created for instance.',
                      instance=self.instance)
            raise exception.VirtualInterfaceCreateException()

        return self.cnas

    def _vif_callback_failed(self, event_name, instance):
        LOG.error('VIF Plug failure for callback on event %s for instance.',
                  event_name, instance=self.instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _get_vif_events(self):
        """Returns the VIF events that need to be received for a VIF plug.

        In order for a VIF plug to be successful, certain events should be
        received from other components within the OpenStack ecosystem. This
        method returns the events neutron needs for a given deploy.
        """
        # See libvirt's driver.py -> _get_neutron_events method for
        # more information.
        if CONF.vif_plugging_is_fatal and CONF.vif_plugging_timeout:
            return [('network-vif-plugged', network_info['id'])
                    for network_info in self.crt_network_infos
                    if not network_info.get('active', True)]

    def revert(self, lpar_wrap, result, flow_failures):
        if not self.network_infos:
            return

        LOG.warning('VIF creation being rolled back for instance.',
                    instance=self.instance)

        # Get the current adapters on the system
        cna_w_list = vm.get_cnas(self.adapter, self.instance)
        for network_info in self.crt_network_infos:
            try:
                vif.unplug(self.adapter, self.instance, network_info,
                           cna_w_list=cna_w_list)
            except Exception:
                LOG.exception("An exception occurred during an unplug in the "
                              "vif rollback.  Ignoring.",
                              instance=self.instance)


class UnplugVifs(task.Task):

    """The task to unplug Virtual Network Interfaces from a VM."""

    def __init__(self, adapter, instance, network_infos):
        """Create the task.

        :param adapter: The pypowervm adapter.
        :param instance: The nova instance.
        :param network_infos: The network information containing the nova
                              VIFs to create.
        """
        self.adapter = adapter
        self.instance = instance
        self.network_infos = network_infos or []

        super(UnplugVifs, self).__init__(name='unplug_vifs')

    def execute(self):
        # If the LPAR is not in an OK state for deleting, then throw an
        # error up front.
        lpar_wrap = vm.get_instance_wrapper(self.adapter, self.instance)
        modifiable, reason = lpar_wrap.can_modify_io()
        if not modifiable:
            LOG.error("Unable to remove VIFs from instance in the system's "
                      "current state. The reason reported by the system is: "
                      "%s", reason, instance=self.instance)
            raise exception.VirtualInterfaceUnplugException(reason=reason)

        # Get all the current Client Network Adapters (CNA) on the VM itself.
        cna_w_list = vm.get_cnas(self.adapter, self.instance)

        # Walk through the VIFs and delete the corresponding CNA on the VM.
        for network_info in self.network_infos:
            vif.unplug(self.adapter, self.instance, network_info,
                       cna_w_list=cna_w_list)


class PlugMgmtVif(task.Task):

    """The task to plug the Management VIF into a VM."""

    def __init__(self, adapter, instance):
        """Create the task.

        Requires 'vm_cnas' from PlugVifs.  If None, this Task will retrieve the
        VM's list of CNAs.

        Provides the mgmt_cna.  This may be None if no management device was
        created.  This is the CNA of the mgmt vif for the VM.

        :param adapter: The pypowervm adapter.
        :param instance: The nova instance.
        """
        self.adapter = adapter
        self.instance = instance

        super(PlugMgmtVif, self).__init__(
            name='plug_mgmt_vif', provides='mgmt_cna', requires=['vm_cnas'])

    def execute(self, vm_cnas):
        LOG.info('Plugging the Management Network Interface to instance.',
                 instance=self.instance)
        # Determine if we need to create the secure RMC VIF.  This should only
        # be needed if there is not a VIF on the secure RMC vSwitch
        vswitch = None
        vswitches = pvm_net.VSwitch.search(
            self.adapter, parent_type=pvm_ms.System.schema_type,
            parent_uuid=self.adapter.sys_uuid, name=SECURE_RMC_VSWITCH)
        if len(vswitches) == 1:
            vswitch = vswitches[0]

        if vswitch is None:
            LOG.warning('No management VIF created for instance due to lack '
                        'of Management Virtual Switch', instance=self.instance)
            return None

        # This next check verifies that there are no existing NICs on the
        # vSwitch, so that the VM does not end up with multiple RMC VIFs.
        if vm_cnas is None:
            has_mgmt_vif = vm.get_cnas(self.adapter, self.instance,
                                       vswitch_uri=vswitch.href)
        else:
            has_mgmt_vif = vswitch.href in [cna.vswitch_uri for cna in vm_cnas]

        if has_mgmt_vif:
            LOG.debug('Management VIF already created for instance',
                instance=self.instance)
            return None

        lpar_uuid = vm.get_pvm_uuid(self.instance)
        return pvm_cna.crt_cna(self.adapter, None, lpar_uuid, SECURE_RMC_VLAN,
                               vswitch=SECURE_RMC_VSWITCH, crt_vswitch=True)

# Copyright 2016, 2017 IBM Corp.
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

import abc

from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import importutils
from pypowervm import exceptions as pvm_ex
from pypowervm.tasks import cna as pvm_cna
from pypowervm.tasks import partition as pvm_par
from pypowervm.wrappers import event as pvm_evt
import six

from nova import exception
from nova.network import model as network_model
from nova.virt.powervm import vm

LOG = log.getLogger(__name__)

NOVALINK_VSWITCH = 'NovaLinkVEABridge'

# Provider tag for custom events from this module
EVENT_PROVIDER_ID = 'NOVA_PVM_VIF'

VIF_TYPE_PVM_SEA = 'pvm_sea'
VIF_TYPE_PVM_OVS = 'ovs'
VIF_MAPPING = {VIF_TYPE_PVM_SEA:
               'nova.virt.powervm.vif.PvmSeaVifDriver',
               VIF_TYPE_PVM_OVS:
               'nova.virt.powervm.vif.PvmOvsVifDriver'}

CONF = cfg.CONF


def _build_vif_driver(adapter, instance, vif):
    """Returns the appropriate VIF Driver for the given VIF.

    :param adapter: The pypowervm adapter API interface.
    :param instance: The nova instance.
    :param vif: The virtual interface.
    :return: The appropriate PvmVifDriver for the VIF.
    """
    if vif.get('type') is None:
        LOG.exception("Failed to build vif driver. Missing vif type.",
                      instance=instance)
        raise exception.VirtualInterfacePlugException()

    # Check the type to the implementations
    if VIF_MAPPING.get(vif['type']):
        return importutils.import_object(
            VIF_MAPPING.get(vif['type']), adapter, instance)

    # No matching implementation, raise error.
    LOG.exception("Failed to build vif driver. Invalid vif type provided.",
                  instance=instance)
    raise exception.VirtualInterfacePlugException()


def _push_vif_event(adapter, action, vif_w, instance, vif_type):
    """Push a custom event to the REST server for a vif action (plug/unplug).

    This event prompts the neutron agent to mark the port up or down. It is
    consumed by custom neutron agents (e.g. Shared Ethernet Adapter)

    :param adapter: The pypowervm adapter.
    :param action: The action taken on the vif - either 'plug' or 'unplug'
    :param vif_w: The pypowervm wrapper of the affected vif (CNA, VNIC, etc.)
    :param instance: The nova instance for the event
    :param vif_type: The type of event source (pvm_sea, ovs, bridge,
                     pvm_sriov etc)
    """
    data = vif_w.href
    detail = jsonutils.dumps(dict(provider=EVENT_PROVIDER_ID, action=action,
                                  mac=vif_w.mac, type=vif_type))
    event = pvm_evt.Event.bld(adapter, data, detail)
    try:
        event = event.create()
        LOG.debug('Pushed custom event for consumption by neutron agent: %s',
                  str(event), instance=instance)
    except Exception:
        with excutils.save_and_reraise_exception(logger=LOG):
            LOG.exception('Custom VIF event push failed.  %s', str(event),
            instance=instance)


def plug(adapter, instance, vif, new_vif=True):
    """Plugs a virtual interface (network) into a VM.

    :param adapter: The pypowervm adapter.
    :param instance: The nova instance object.
    :param vif: The virtual interface to plug into the instance.
    :param new_vif: (Optional, Default: True) If set, indicates that it is
                    a brand new VIF.  If False, it indicates that the VIF
                    is already on the client but should be treated on the
                    bridge.
    :return: The wrapper (CNA) representing the plugged virtual network. None
             if the vnet was not created.
    """
    vif_drv = _build_vif_driver(adapter, instance, vif)

    try:
        vnet_w = vif_drv.plug(vif, new_vif=new_vif)
    except pvm_ex.HttpError:
        LOG.exception('VIF plug failed for instance.', instance=instance)
        raise exception.VirtualInterfacePlugException()
    # Other exceptions are (hopefully) custom VirtualInterfacePlugException
    # generated lower in the call stack.

    # Push a custom event if we really plugged the vif
    if vnet_w is not None:
        _push_vif_event(adapter, 'plug', vnet_w, instance, vif['type'])

    return vnet_w


def unplug(adapter, instance, vif, cna_w_list=None):
    """Unplugs a virtual interface (network) from a VM.

    :param adapter: The pypowervm adapter.
    :param instance: The nova instance object.
    :param vif: The virtual interface to plug into the instance.
    :param cna_w_list: (Optional, Default: None) The list of Client Network
                       Adapters from pypowervm.  Providing this input
                       allows for an improvement in operation speed.
    """
    vif_drv = _build_vif_driver(adapter, instance, vif)
    try:
        vnet_w = vif_drv.unplug(vif, cna_w_list=cna_w_list)
    except pvm_ex.HttpError as he:
        LOG.exception('VIF unplug failed for instance', instance=instance)
        raise exception.VirtualInterfaceUnplugException(reason=he.args[0])

    # Push a custom event if we successfully unplugged the vif.
    if vnet_w:
        _push_vif_event(adapter, 'unplug', vnet_w, instance, vif['type'])


@six.add_metaclass(abc.ABCMeta)
class PvmVifDriver(object):
    """Represents an abstract class for a PowerVM Vif Driver.

    A VIF Driver understands a given virtual interface type (network).  It
    understands how to plug and unplug a given VIF for a virtual machine.
    """

    def __init__(self, adapter, instance):
        """Initializes a VIF Driver.
        :param adapter: The pypowervm adapter API interface.
        :param instance: The nova instance that the vif action will be run
                         against.
        """
        self.adapter = adapter
        self.instance = instance

    @abc.abstractmethod
    def plug(self, vif, new_vif=True):
        """Plugs a virtual interface (network) into a VM.

        :param vif: The virtual interface to plug into the instance.
        :param new_vif: (Optional, Default: True) If set, indicates that it is
                        a brand new VIF.  If False, it indicates that the VIF
                        is already on the client but should be treated on the
                        bridge.
        :return: The new vif that was created.  Only returned if new_vif is
                 set to True.  Otherwise None is expected.
        """
        pass

    def unplug(self, vif, cna_w_list=None):
        """Unplugs a virtual interface (network) from a VM.

        :param vif: The virtual interface to plug into the instance.
        :param cna_w_list: (Optional, Default: None) The list of Client Network
                           Adapters from pypowervm.  Providing this input
                           allows for an improvement in operation speed.
        :return cna_w: The deleted Client Network Adapter or None if the CNA
                       is not found.
        """
        # This is a default implementation that most implementations will
        # require.

        # Need to find the adapters if they were not provided
        if not cna_w_list:
            cna_w_list = vm.get_cnas(self.adapter, self.instance)

        cna_w = self._find_cna_for_vif(cna_w_list, vif)
        if not cna_w:
            LOG.warning('Unable to unplug VIF with mac %(mac)s.  The VIF was '
                        'not found on the instance.',
                        {'mac': vif['address']}, instance=self.instance)
            return None

        LOG.info('Deleting VIF with mac %(mac)s.',
                 {'mac': vif['address']}, instance=self.instance)
        try:
            cna_w.delete()
        except Exception as e:
            LOG.exception('Unable to unplug VIF with mac %(mac)s.',
                          {'mac': vif['address']}, instance=self.instance)
            raise exception.VirtualInterfaceUnplugException(
                reason=six.text_type(e))
        return cna_w

    @staticmethod
    def _find_cna_for_vif(cna_w_list, vif):
        """Finds the PowerVM CNA for a given Nova VIF.

        :param cna_w_list: The list of Client Network Adapter wrappers from
                           pypowervm.
        :param vif: The Nova Virtual Interface (virtual network interface).
        :return: The CNA that corresponds to the VIF.  None if one is not
                 part of the cna_w_list.
        """
        for cna_w in cna_w_list:
            if vm.norm_mac(cna_w.mac) == vif['address']:
                return cna_w
        return None


class PvmOvsVifDriver(PvmVifDriver):
    """The Open vSwitch VIF driver for PowerVM."""

    def plug(self, vif, new_vif=True):
        """Plugs a virtual interface (network) into a VM.

        Creates a 'peer to peer' connection between the Management partition
        hosting the Linux I/O and the client VM.  There will be one trunk
        adapter for a given client adapter.

        The device will be 'up' on the mgmt partition.

        Will make sure that the trunk device has the appropriate metadata (e.g.
        port id) set on it so that the Open vSwitch agent picks it up properly.

        :param vif: The virtual interface to plug into the instance.
        :param new_vif: (Optional, Default: True) If set, indicates that it is
                        a brand new VIF.  If False, it indicates that the VIF
                        is already on the client but should be treated on the
                        bridge.
        :return: The new vif that was created.  Only returned if new_vif is
                 set to True.  Otherwise None is expected.
        """

        # Create the trunk and client adapter.
        lpar_uuid = vm.get_pvm_uuid(self.instance)
        mgmt_uuid = pvm_par.get_this_partition(self.adapter).uuid

        mtu = vif['network'].get_meta('mtu')
        if 'devname' in vif:
            dev_name = vif['devname']
        else:
            dev_name = ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]

        meta_attrs = ','.join([
                     'iface-id=%s' % (vif.get('ovs_interfaceid') or vif['id']),
                     'iface-status=active',
                     'attached-mac=%s' % vif['address'],
                     'vm-uuid=%s' % self.instance.uuid])

        if new_vif:
            return pvm_cna.crt_p2p_cna(
                self.adapter, None, lpar_uuid, [mgmt_uuid], NOVALINK_VSWITCH,
                crt_vswitch=True, mac_addr=vif['address'], dev_name=dev_name,
                ovs_bridge=vif['network']['bridge'],
                ovs_ext_ids=meta_attrs, configured_mtu=mtu)[0]
        else:
            # Bug : https://bugs.launchpad.net/nova-powervm/+bug/1731548
            # When a host is rebooted, something is discarding tap devices for
            # VMs deployed with OVS vif. To prevent VMs losing network
            # connectivity, this is fixed by recreating the tap devices during
            # init of the nova compute service, which will call vif plug with
            # new_vif==False.

            # Find the CNA for this vif.
            # TODO(esberglu) improve performance by caching VIOS wrapper(s) and
            # CNA lists (in case >1 vif per VM).
            cna_w_list = vm.get_cnas(self.adapter, self.instance)
            cna_w = self._find_cna_for_vif(cna_w_list, vif)
            if not cna_w:
                LOG.warning('Unable to plug VIF with mac %s for instance. The '
                            'VIF was not found on the instance.',
                            vif['address'], instance=self.instance)
                return None

            # Find the corresponding trunk adapter
            trunks = pvm_cna.find_trunks(self.adapter, cna_w)
            for trunk in trunks:
                # Set MTU, OVS external ids, and OVS bridge metadata
                trunk.configured_mtu = mtu
                trunk.ovs_ext_ids = meta_attrs
                trunk.ovs_bridge = vif['network']['bridge']
                # Updating the trunk adapter will cause NovaLink to reassociate
                # the tap device.
                trunk.update()

    def unplug(self, vif, cna_w_list=None):
        """Unplugs a virtual interface (network) from a VM.

        Extends the base implementation, but before calling it will remove
        the adapter from the Open vSwitch and delete the trunk.

        :param vif: The virtual interface to plug into the instance.
        :param cna_w_list: (Optional, Default: None) The list of Client Network
                           Adapters from pypowervm.  Providing this input
                           allows for an improvement in operation speed.
        :return cna_w: The deleted Client Network Adapter or None if the CNA
                       is not found.
        """
        # Need to find the adapters if they were not provided
        if not cna_w_list:
            cna_w_list = vm.get_cnas(self.adapter, self.instance)

        # Find the CNA for this vif.
        cna_w = self._find_cna_for_vif(cna_w_list, vif)

        if not cna_w:
            LOG.warning('Unable to unplug VIF with mac %s for instance. The '
                        'VIF was not found on the instance.', vif['address'],
                        instance=self.instance)
            return None

        # Find and delete the trunk adapters
        trunks = pvm_cna.find_trunks(self.adapter, cna_w)
        for trunk in trunks:
            trunk.delete()

        # Delete the client CNA
        return super(PvmOvsVifDriver, self).unplug(vif, cna_w_list=cna_w_list)


class PvmSeaVifDriver(PvmVifDriver):
    """The PowerVM Shared Ethernet Adapter VIF Driver."""

    def plug(self, vif, new_vif=True):
        """Plugs a virtual interface (network) into a VM.

        This method simply creates the client network adapter into the VM.

        :param vif: The virtual interface to plug into the instance.
        :param new_vif: (Optional, Default: True) If set, indicates that it is
                        a brand new VIF.  If False, it indicates that the VIF
                        is already on the client but should be treated on the
                        bridge.
        :return: The new vif that was created.  Only returned if new_vif is
                 set to True.  Otherwise None is expected.
        """
        # Do nothing if not a new VIF
        if not new_vif:
            return None

        lpar_uuid = vm.get_pvm_uuid(self.instance)

        # CNA's require a VLAN. The networking-powervm neutron agent puts this
        # in the vif details.
        vlan = int(vif['details']['vlan'])

        LOG.debug("Creating SEA-based VIF with VLAN %s", str(vlan),
                  instance=self.instance)
        cna_w = pvm_cna.crt_cna(self.adapter, None, lpar_uuid, vlan,
                                mac_addr=vif['address'])

        return cna_w

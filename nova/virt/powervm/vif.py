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

from oslo_config import cfg
from oslo_log import log
from oslo_utils import importutils
from pypowervm import exceptions as pvm_ex
from pypowervm.tasks import cna as pvm_cna
from pypowervm.tasks import partition as pvm_par
import six

from nova import exception
from nova.network import model as network_model
from nova.virt.powervm import vm

LOG = log.getLogger(__name__)

NOVALINK_VSWITCH = 'NovaLinkVEABridge'

VIF_TYPE_PVM_OVS = 'ovs'
VIF_MAPPING = {VIF_TYPE_PVM_OVS:
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
        return vif_drv.plug(vif, new_vif=new_vif)
    except pvm_ex.HttpError:
        LOG.exception('VIF plug failed for instance.', instance=instance)
        raise exception.VirtualInterfacePlugException()
    # Other exceptions are (hopefully) custom VirtualInterfacePlugException
    # generated lower in the call stack.


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
        vif_drv.unplug(vif, cna_w_list=cna_w_list)
    except pvm_ex.HttpError as he:
        LOG.exception('VIF unplug failed for instance', instance=instance)
        raise exception.VirtualInterfaceUnplugException(reason=he.args[0])


class PvmOvsVifDriver(object):
    """The Open vSwitch VIF driver for PowerVM."""

    def __init__(self, adapter, instance):
        """Initializes a VIF Driver.

        :param adapter: The pypowervm adapter API interface.
        :param instance: The nova instance that the vif action will be run
                         against.
        """
        self.adapter = adapter
        self.instance = instance

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

        This will remove the adapter from the Open vSwitch and delete the
        trunk adapters.

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

        # Now delete the client CNA
        LOG.info('Deleting VIF with mac %s for instance.', vif['address'],
                 instance=self.instance)
        try:
            cna_w.delete()
        except Exception as e:
            LOG.error('Unable to unplug VIF with mac %s for instance.',
                      vif['address'], instance=self.instance)
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

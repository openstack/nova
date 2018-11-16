# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
# Copyright (C) 2011 Nicira, Inc
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

"""VIF drivers for XenAPI."""

from os_xenapi.client import host_network
from oslo_log import log as logging

from nova.compute import power_state
import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model as network_model
from nova.virt.xenapi import network_utils
from nova.virt.xenapi import vm_utils


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class XenVIFDriver(object):
    def __init__(self, xenapi_session):
        self._session = xenapi_session

    def _get_vif_ref(self, vif, vm_ref):
        vif_refs = self._session.call_xenapi("VM.get_VIFs", vm_ref)
        for vif_ref in vif_refs:
            try:
                vif_rec = self._session.call_xenapi('VIF.get_record', vif_ref)
                if vif_rec['MAC'] == vif['address']:
                    return vif_ref
            except Exception:
                # When got exception here, maybe the vif is removed during the
                # loop, ignore this vif and continue
                continue
        return None

    def _create_vif(self, vif, vif_rec, vm_ref):
        try:
            vif_ref = self._session.call_xenapi('VIF.create', vif_rec)
        except Exception as e:
            LOG.warning("Failed to create vif, exception:%(exception)s, "
                        "vif:%(vif)s", {'exception': e, 'vif': vif})
            raise exception.NovaException(
                reason=_("Failed to create vif %s") % vif)

        LOG.debug("create vif %(vif)s for vm %(vm_ref)s successfully",
                  {'vif': vif, 'vm_ref': vm_ref})
        return vif_ref

    def unplug(self, instance, vif, vm_ref):
        try:
            LOG.debug("unplug vif, vif:%(vif)s, vm_ref:%(vm_ref)s",
                      {'vif': vif, 'vm_ref': vm_ref}, instance=instance)
            vif_ref = self._get_vif_ref(vif, vm_ref)
            if not vif_ref:
                LOG.debug("vif didn't exist, no need to unplug vif %s",
                        vif, instance=instance)
                return
            # hot unplug the VIF first
            self.hot_unplug(vif, instance, vm_ref, vif_ref)
            self._session.call_xenapi('VIF.destroy', vif_ref)
        except Exception as e:
            LOG.warning(
                "Fail to unplug vif:%(vif)s, exception:%(exception)s",
                {'vif': vif, 'exception': e}, instance=instance)
            raise exception.NovaException(
                reason=_("Failed to unplug vif %s") % vif)

    def get_vif_interim_net_name(self, vif_id):
        return ("net-" + vif_id)[:network_model.NIC_NAME_LEN]

    def hot_plug(self, vif, instance, vm_ref, vif_ref):
        """hotplug virtual interface to running instance.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to attach.
        :param nova.objects.instance.Instance instance:
            The instance which will get an additional network interface.
        :param string vm_ref:
            The instance's reference from hypervisor's point of view.
        :param string vif_ref:
            The interface's reference from hypervisor's point of view.
        :return: None
        """
        pass

    def hot_unplug(self, vif, instance, vm_ref, vif_ref):
        """hot unplug virtual interface from running instance.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to detach.
        :param nova.objects.instance.Instance instance:
            The instance which will remove additional network interface.
        :param string vm_ref:
            The instance's reference from hypervisor's point of view.
        :param string vif_ref:
            The interface's reference from hypervisor's point of view.
        :return: None
        """
        pass

    def post_start_actions(self, instance, vif_ref):
        """post actions when the instance is power on.
        :param nova.objects.instance.Instance instance:
            The instance which will execute extra actions after power on
        :param string vif_ref:
            The interface's reference from hypervisor's point of view.
        :return: None
        """
        pass

    def create_vif_interim_network(self, vif):
        pass

    def delete_network_and_bridge(self, instance, vif_id):
        pass


class XenAPIOpenVswitchDriver(XenVIFDriver):
    """VIF driver for Open vSwitch with XenAPI."""

    def plug(self, instance, vif, vm_ref=None, device=None):
        """create an interim network for this vif; and build
        the vif_rec which will be used by xapi to create VM vif
        """
        if not vm_ref:
            vm_ref = vm_utils.lookup(self._session, instance['name'])
        if not vm_ref:
            raise exception.VirtualInterfacePlugException(
                "Cannot find instance %s, discard vif plug" % instance['name'])

        # if VIF already exists, return this vif_ref directly
        vif_ref = self._get_vif_ref(vif, vm_ref)
        if vif_ref:
            LOG.debug("VIF %s already exists when plug vif",
                      vif_ref, instance=instance)
            return vif_ref

        if not device:
            device = 0

        # Create an interim network for each VIF, so dom0 has a single
        # bridge for each device (the emulated and PV ethernet devices
        # will both be on this bridge.
        network_ref = self.create_vif_interim_network(vif)
        vif_rec = {}
        vif_rec['device'] = str(device)
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = vif['address']
        vif_rec['MTU'] = '1500'
        vif_rec['qos_algorithm_type'] = ''
        vif_rec['qos_algorithm_params'] = {}
        vif_rec['other_config'] = {'neutron-port-id': vif['id']}
        vif_ref = self._create_vif(vif, vif_rec, vm_ref)

        # call XenAPI to plug vif
        self.hot_plug(vif, instance, vm_ref, vif_ref)

        return vif_ref

    def unplug(self, instance, vif, vm_ref):
        super(XenAPIOpenVswitchDriver, self).unplug(instance, vif, vm_ref)
        self.delete_network_and_bridge(instance, vif['id'])

    def delete_network_and_bridge(self, instance, vif_id):
        """Delete network and bridge:
        1. delete the patch port pair between the integration bridge and
           the qbr linux bridge(if exist) and the interim network.
        2. destroy the interim network
        3. delete the OVS bridge service for the interim network
        4. delete linux bridge qbr and related ports if exist
        """
        network = self._get_network_by_vif(vif_id)
        if not network:
            return
        vifs = self._session.network.get_VIFs(network)
        bridge_name = self._session.network.get_bridge(network)
        if vifs:
            # Still has vifs attached to this network
            for remain_vif in vifs:
                # if the remain vifs are on the local server, give up all the
                # operations. If the remain vifs are on the remote hosts, keep
                # the network and delete the bridge
                if self._get_host_by_vif(remain_vif) == self._session.host_ref:
                    return
        else:
            # No vif left, delete the network
            try:
                self._session.network.destroy(network)
            except Exception as e:
                LOG.warning("Failed to destroy network for vif (id=%(if)s), "
                            "exception:%(exception)s",
                            {'if': vif_id, 'exception': e}, instance=instance)
                raise exception.VirtualInterfaceUnplugException(
                    reason=_("Failed to destroy network"))
        # Two cases:
        # 1) No vif left, just delete the bridge
        # 2) For resize/intra-pool migrate, vifs on both of the
        #    source and target VM will be connected to the same
        #    interim network. If the VM is resident on a remote host,
        #    linux bridge on current host will be deleted.
        self.delete_bridge(instance, vif_id, bridge_name)

    def delete_bridge(self, instance, vif_id, bridge_name):
        LOG.debug('destroying patch port pair for vif id: vif_id=%(vif_id)s',
                  {'vif_id': vif_id})
        patch_port1, tap_name = self._get_patch_port_pair_names(vif_id)
        try:
            # delete the patch port pair
            host_network.ovs_del_port(self._session, bridge_name, patch_port1)
        except Exception as e:
            LOG.warning("Failed to delete patch port pair for vif id %(if)s,"
                        " exception:%(exception)s",
                        {'if': vif_id, 'exception': e}, instance=instance)
            raise exception.VirtualInterfaceUnplugException(
                reason=_("Failed to delete patch port pair"))

        LOG.debug('destroying bridge: bridge=%(br)s', {'br': bridge_name})
        try:
            # delete bridge if it still exists.
            # As there are patch ports existing on this bridge when
            # destroying won't be destroyed automatically by XAPI, let's
            # destroy it at here.
            host_network.ovs_del_br(self._session, bridge_name)
            qbr_name = self._get_qbr_name(vif_id)
            qvb_name, qvo_name = self._get_veth_pair_names(vif_id)
            if self._device_exists(qbr_name):
                # delete tap port, qvb port and qbr
                LOG.debug(
                    "destroy linux bridge %(qbr)s when unplug vif id"
                    " %(vif_id)s", {'qbr': qbr_name, 'vif_id': vif_id})
                self._delete_linux_port(qbr_name, tap_name)
                self._delete_linux_port(qbr_name, qvb_name)
                self._delete_linux_bridge(qbr_name)
            host_network.ovs_del_port(self._session,
                                      CONF.xenserver.ovs_integration_bridge,
                                      qvo_name)
        except Exception as e:
            LOG.warning("Failed to delete bridge for vif id %(if)s, "
                        "exception:%(exception)s",
                        {'if': vif_id, 'exception': e}, instance=instance)
            raise exception.VirtualInterfaceUnplugException(
                reason=_("Failed to delete bridge"))

    def _get_network_by_vif(self, vif_id):
        net_name = self.get_vif_interim_net_name(vif_id)
        network = network_utils.find_network_with_name_label(
            self._session, net_name)
        if network is None:
            LOG.debug("Failed to find network for vif id %(if)s",
                      {'if': vif_id})
            return
        return network

    def _get_host_by_vif(self, vif_id):
        network = self._get_network_by_vif(vif_id)
        if not network:
            return
        vif_info = self._session.VIF.get_all_records_where(
            'field "network" = "%s"' % network)
        if not vif_info or len(vif_info) != 1:
            raise exception.NovaException(
                "Couldn't find vif id information in network %s"
                % network)
        vm_ref = self._session.VIF.get_VM(list(vif_info.keys())[0])
        return self._session.VM.get_resident_on(vm_ref)

    def hot_plug(self, vif, instance, vm_ref, vif_ref):
        # hot plug vif only when VM's power state is running
        LOG.debug("Hot plug vif, vif: %s", vif, instance=instance)
        state = vm_utils.get_power_state(self._session, vm_ref)
        if state != power_state.RUNNING:
            LOG.debug("Skip hot plug VIF, VM is not running, vif: %s", vif,
                      instance=instance)
            return

        self._session.VIF.plug(vif_ref)
        self.post_start_actions(instance, vif_ref)

    def hot_unplug(self, vif, instance, vm_ref, vif_ref):
        # hot unplug vif only when VM's power state is running
        LOG.debug("Hot unplug vif, vif: %s", vif, instance=instance)
        state = vm_utils.get_power_state(self._session, vm_ref)
        if state != power_state.RUNNING:
            LOG.debug("Skip hot unplug VIF, VM is not running, vif: %s", vif,
                      instance=instance)
            return

        self._session.VIF.unplug(vif_ref)

    def _get_qbr_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def _get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def _device_exists(self, device):
        """Check if ethernet device exists."""
        try:
            host_network.ip_link_get_dev(self._session, device)
            return True
        except Exception:
            # Swallow exception from plugin, since this indicates the device
            # doesn't exist
            return False

    def _delete_net_dev(self, dev):
        """Delete a network device only if it exists."""
        if self._device_exists(dev):
            LOG.debug("delete network device '%s'", dev)
            host_network.ip_link_del_dev(self._session, dev)

    def _create_veth_pair(self, dev1_name, dev2_name):
        """Create a pair of veth devices with the specified names,
        deleting any previous devices with those names.
        """
        LOG.debug("Create veth pair, port1:%(qvb)s, port2:%(qvo)s",
                  {'qvb': dev1_name, 'qvo': dev2_name})
        for dev in [dev1_name, dev2_name]:
            self._delete_net_dev(dev)
        host_network.ip_link_add_veth_pair(self._session, dev1_name, dev2_name)
        for dev in [dev1_name, dev2_name]:
            host_network.ip_link_set_dev(self._session, dev, 'up')
            host_network.ip_link_set_promisc(self._session, dev, 'on')

    def _create_linux_bridge(self, vif_rec):
        """create a qbr linux bridge for neutron security group
        """
        iface_id = vif_rec['other_config']['neutron-port-id']
        linux_br_name = self._get_qbr_name(iface_id)
        if not self._device_exists(linux_br_name):
            LOG.debug("Create linux bridge %s", linux_br_name)
            host_network.brctl_add_br(self._session, linux_br_name)
            host_network.brctl_set_fd(self._session, linux_br_name, '0')
            host_network.brctl_set_stp(self._session, linux_br_name, 'off')
            host_network.ip_link_set_dev(self._session, linux_br_name, 'up')

        qvb_name, qvo_name = self._get_veth_pair_names(iface_id)
        if not self._device_exists(qvo_name):
            self._create_veth_pair(qvb_name, qvo_name)
            host_network.brctl_add_if(self._session, linux_br_name, qvb_name)
            host_network.ovs_create_port(
                self._session, CONF.xenserver.ovs_integration_bridge,
                qvo_name, iface_id, vif_rec['MAC'], 'active')
        return linux_br_name

    def _delete_linux_port(self, qbr_name, port_name):
        try:
            # delete port in linux bridge
            host_network.brctl_del_if(self._session, qbr_name, port_name)
            self._delete_net_dev(port_name)
        except Exception:
            LOG.debug("Fail to delete linux port %(port_name)s on bridge "
                      "%(qbr_name)s",
                      {'port_name': port_name, 'qbr_name': qbr_name})

    def _delete_linux_bridge(self, qbr_name):
        try:
            # delete linux bridge qbrxxx
            host_network.ip_link_set_dev(self._session, qbr_name, 'down')
            host_network.brctl_del_br(self._session, qbr_name)
        except Exception:
            LOG.debug("Fail to delete linux bridge %s", qbr_name)

    def post_start_actions(self, instance, vif_ref):
        """Do needed actions post vif start:
        plug the interim ovs bridge to the integration bridge;
        set external_ids to the int-br port which will service
        for this vif.
        """
        vif_rec = self._session.VIF.get_record(vif_ref)
        network_ref = vif_rec['network']
        bridge_name = self._session.network.get_bridge(network_ref)
        network_uuid = self._session.network.get_uuid(network_ref)
        iface_id = vif_rec['other_config']['neutron-port-id']
        patch_port1, tap_name = self._get_patch_port_pair_names(iface_id)
        LOG.debug('plug_ovs_bridge: port1=%(port1)s, port2=%(port2)s,'
                  'network_uuid=%(uuid)s, bridge_name=%(bridge_name)s',
                  {'port1': patch_port1, 'port2': tap_name,
                   'uuid': network_uuid, 'bridge_name': bridge_name})
        if bridge_name is None:
            raise exception.VirtualInterfacePlugException(
                      _("Failed to find bridge for vif"))

        # Create Linux bridge qbrXXX
        linux_br_name = self._create_linux_bridge(vif_rec)
        if not self._device_exists(tap_name):
            LOG.debug("create veth pair for interim bridge %(interim_bridge)s "
                      "and linux bridge %(linux_bridge)s",
                      {'interim_bridge': bridge_name,
                       'linux_bridge': linux_br_name})
            self._create_veth_pair(tap_name, patch_port1)
            host_network.brctl_add_if(self._session, linux_br_name, tap_name)
            # Add port to interim bridge
            host_network.ovs_add_port(self._session, bridge_name, patch_port1)

    def create_vif_interim_network(self, vif):
        net_name = self.get_vif_interim_net_name(vif['id'])
        # In a pooled environment, make the network shared in order to ensure
        # it can also be used in the target host while live migrating.
        # "assume_network_is_shared" flag does not affect environments where
        # storage pools are not used.
        network_rec = {'name_label': net_name,
                       'name_description': "interim network for vif[%s]"
                       % vif['id'],
                       'other_config': {'assume_network_is_shared': 'true'}}
        network_ref = network_utils.find_network_with_name_label(
            self._session, net_name)
        if network_ref:
            # already exist, just return
            # in some scenarios: e..g resize/migrate, it won't create new
            # interim network.
            return network_ref
        try:
            network_ref = self._session.network.create(network_rec)
        except Exception as e:
            LOG.warning("Failed to create interim network for vif %(if)s, "
                        "exception:%(exception)s",
                        {'if': vif, 'exception': e})
            raise exception.VirtualInterfacePlugException(
                _("Failed to create the interim network for vif"))
        return network_ref

    def _get_patch_port_pair_names(self, iface_id):
        return (("vif%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("tap%s" % iface_id)[:network_model.NIC_NAME_LEN])

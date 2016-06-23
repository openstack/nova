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

from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.i18n import _
from nova.i18n import _LW
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
            LOG.warn(_LW("Failed to create vif, exception:%(exception)s, "
                      "vif:%(vif)s"), {'exception': e, 'vif': vif})
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
            self._session.call_xenapi('VIF.destroy', vif_ref)
        except Exception as e:
            LOG.warn(
                _LW("Fail to unplug vif:%(vif)s, exception:%(exception)s"),
                {'vif': vif, 'exception': e}, instance=instance)
            raise exception.NovaException(
                reason=_("Failed to unplug vif %s") % vif)


class XenAPIBridgeDriver(XenVIFDriver):
    """VIF Driver for XenAPI that uses XenAPI to create Networks."""

    def plug(self, instance, vif, vm_ref=None, device=None):
        if not vm_ref:
            vm_ref = vm_utils.lookup(self._session, instance['name'])

        # if VIF already exists, return this vif_ref directly
        vif_ref = self._get_vif_ref(vif, vm_ref)
        if vif_ref:
            LOG.debug("VIF %s already exists when plug vif",
                      vif_ref, instance=instance)
            return vif_ref

        if not device:
            device = 0

        if vif['network'].get_meta('should_create_vlan'):
            network_ref = self._ensure_vlan_bridge(vif['network'])
        else:
            network_ref = network_utils.find_network_with_bridge(
                    self._session, vif['network']['bridge'])
        vif_rec = {}
        vif_rec['device'] = str(device)
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = vif['address']
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        if vif.get_meta('rxtx_cap'):
            vif_rec['qos_algorithm_type'] = 'ratelimit'
            vif_rec['qos_algorithm_params'] = {'kbps':
                         str(int(vif.get_meta('rxtx_cap')) * 1024)}
        else:
            vif_rec['qos_algorithm_type'] = ''
            vif_rec['qos_algorithm_params'] = {}
        return self._create_vif(vif, vif_rec, vm_ref)

    def _ensure_vlan_bridge(self, network):
        """Ensure that a VLAN bridge exists."""

        vlan_num = network.get_meta('vlan')
        bridge = network['bridge']
        bridge_interface = (CONF.vlan_interface or
                            network.get_meta('bridge_interface'))
        # Check whether bridge already exists
        # Retrieve network whose name_label is "bridge"
        network_ref = network_utils.find_network_with_name_label(
                                        self._session, bridge)
        if network_ref is None:
            # If bridge does not exists
            # 1 - create network
            description = 'network for nova bridge %s' % bridge
            network_rec = {'name_label': bridge,
                           'name_description': description,
                           'other_config': {}}
            network_ref = self._session.call_xenapi('network.create',
                                                    network_rec)
            # 2 - find PIF for VLAN NOTE(salvatore-orlando): using double
            # quotes inside single quotes as xapi filter only support
            # tokens in double quotes
            expr = ('field "device" = "%s" and field "VLAN" = "-1"' %
                    bridge_interface)
            pifs = self._session.call_xenapi('PIF.get_all_records_where',
                                             expr)

            # Multiple PIF are ok: we are dealing with a pool
            if len(pifs) == 0:
                raise Exception(_('Found no PIF for device %s') %
                                bridge_interface)
            for pif_ref in pifs.keys():
                self._session.call_xenapi('VLAN.create',
                                          pif_ref,
                                          str(vlan_num),
                                          network_ref)
        else:
            # Check VLAN tag is appropriate
            network_rec = self._session.call_xenapi('network.get_record',
                                                    network_ref)
            # Retrieve PIFs from network
            for pif_ref in network_rec['PIFs']:
                # Retrieve VLAN from PIF
                pif_rec = self._session.call_xenapi('PIF.get_record',
                                                    pif_ref)
                pif_vlan = int(pif_rec['VLAN'])
                # Raise an exception if VLAN != vlan_num
                if pif_vlan != vlan_num:
                    raise Exception(_("PIF %(pif_uuid)s for network "
                                      "%(bridge)s has VLAN id %(pif_vlan)d. "
                                      "Expected %(vlan_num)d"),
                                    {'pif_uuid': pif_rec['uuid'],
                                     'bridge': bridge,
                                     'pif_vlan': pif_vlan,
                                     'vlan_num': vlan_num})

        return network_ref

    def unplug(self, instance, vif, vm_ref):
        super(XenAPIBridgeDriver, self).unplug(instance, vif, vm_ref)

    def post_start_actions(self, instance, vif_ref):
        """no further actions needed for this driver type"""
        pass


class XenAPIOpenVswitchDriver(XenVIFDriver):
    """VIF driver for Open vSwitch with XenAPI."""

    def plug(self, instance, vif, vm_ref=None, device=None):
        """create an interim network for this vif; and build
        the vif_rec which will be used by xapi to create VM vif
        """
        if not vm_ref:
            vm_ref = vm_utils.lookup(self._session, instance['name'])

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
        # OVS on the hypervisor monitors this key and uses it to
        # set the iface-id attribute
        vif_rec['other_config'] = {'nicira-iface-id': vif['id']}
        return self._create_vif(vif, vif_rec, vm_ref)

    def unplug(self, instance, vif, vm_ref):
        """unplug vif:
        1. unplug and destroy vif.
        2. delete the patch port pair between the integration bridge and
           the interim network.
        3. destroy the interim network
        4. delete the OVS bridge service for the interim network
        """
        super(XenAPIOpenVswitchDriver, self).unplug(instance, vif, vm_ref)

        net_name = self.get_vif_interim_net_name(vif)
        network = network_utils.find_network_with_name_label(
            self._session, net_name)
        if network is None:
            return
        vifs = self._session.network.get_VIFs(network)
        if vifs:
            # only remove the interim network when it's empty.
            # for resize/migrate on local host, vifs on both of the
            # source and target VM will be connected to the same
            # interim network.
            return
        LOG.debug('destroying patch port pair for vif: vif_id=%(vif_id)s',
                  {'vif_id': vif['id']})
        bridge_name = self._session.network.get_bridge(network)
        patch_port1, patch_port2 = self._get_patch_port_pair_names(vif['id'])
        try:
            # delete the patch port pair
            self._ovs_del_port(bridge_name, patch_port1)
            self._ovs_del_port(CONF.xenserver.ovs_integration_bridge,
                               patch_port2)
        except Exception as e:
            LOG.warn(_LW("Failed to delete patch port pair for vif %(if)s,"
                         " exception:%(exception)s"),
                     {'if': vif, 'exception': e}, instance=instance)
            raise exception.VirtualInterfaceUnplugException(
                reason=_("Failed to delete patch port pair"))

        LOG.debug('destroying network: network=%(network)s,'
                  'bridge=%(br)s',
                  {'network': network, 'br': bridge_name})
        try:
            self._session.network.destroy(network)
            # delete bridge if it still exists.
            # As there is patch port existing on this bridge when destroying
            # the VM vif (which happens when shutdown the VM), the bridge
            # won't be destroyed automatically by XAPI. So let's destroy it
            # at here.
            self._ovs_del_br(bridge_name)
        except Exception as e:
            LOG.warn(_LW("Failed to delete bridge for vif %(if)s, "
                         "exception:%(exception)s"),
                     {'if': vif, 'exception': e}, instance=instance)
            raise exception.VirtualInterfaceUnplugException(
                reason=_("Failed to delete bridge"))

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
        iface_id = vif_rec['other_config']['nicira-iface-id']
        patch_port1, patch_port2 = self._get_patch_port_pair_names(iface_id)
        LOG.debug('plug_ovs_bridge: port1=%(port1)s, port2=%(port2)s,'
                  'network_uuid=%(uuid)s, bridge_name=%(bridge_name)s',
                  {'port1': patch_port1, 'port2': patch_port2,
                   'uuid': network_uuid, 'bridge_name': bridge_name})
        if bridge_name is None:
            raise exception.VirtualInterfacePlugException(
                      _("Failed to find bridge for vif"))

        self._ovs_add_patch_port(bridge_name, patch_port1, patch_port2)
        self._ovs_add_patch_port(CONF.xenserver.ovs_integration_bridge,
                                 patch_port2, patch_port1)
        self._ovs_map_external_ids(patch_port2, vif_rec)

    def get_vif_interim_net_name(self, vif):
        return ("net-" + vif['id'])[:network_model.NIC_NAME_LEN]

    def create_vif_interim_network(self, vif):
        net_name = self.get_vif_interim_net_name(vif)
        network_rec = {'name_label': net_name,
                   'name_description': "interim network for vif",
                   'other_config': {}}
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
            LOG.warn(_LW("Failed to create interim network for vif %(if)s, "
                         "exception:%(exception)s"),
                     {'if': vif, 'exception': e})
            raise exception.VirtualInterfacePlugException(
                _("Failed to create the interim network for vif"))
        return network_ref

    def _get_patch_port_pair_names(self, iface_id):
        return (("pp1-%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("pp2-%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def _ovs_add_patch_port(self, bridge_name, port_name, peer_port_name):
        cmd = 'ovs_add_patch_port'
        args = {'bridge_name': bridge_name,
                'port_name': port_name,
                'peer_port_name': peer_port_name
               }
        self._exec_dom0_cmd(cmd, args)

    def _ovs_del_port(self, bridge_name, port_name):
        cmd = 'ovs_del_port'
        args = {'bridge_name': bridge_name,
                'port_name': port_name
               }
        self._exec_dom0_cmd(cmd, args)

    def _ovs_del_br(self, bridge_name):
        cmd = 'ovs_del_br'
        args = {'bridge_name': bridge_name}
        self._exec_dom0_cmd(cmd, args)

    def _ovs_set_if_external_id(self, interface, extneral_id, value):
        cmd = 'ovs_set_if_external_id'
        args = {'interface': interface,
                'extneral_id': extneral_id,
                'value': value}
        self._exec_dom0_cmd(cmd, args)

    def _ovs_map_external_ids(self, interface, vif_rec):
        '''set external ids on the integration bridge vif
        '''
        mac = vif_rec['MAC']
        iface_id = vif_rec['other_config']['nicira-iface-id']
        vif_uuid = vif_rec['uuid']
        status = 'active'

        self._ovs_set_if_external_id(interface, 'attached-mac', mac)
        self._ovs_set_if_external_id(interface, 'iface-id', iface_id)
        self._ovs_set_if_external_id(interface, 'xs-vif-uuid', vif_uuid)
        self._ovs_set_if_external_id(interface, 'iface-status', status)

    def _exec_dom0_cmd(self, cmd, cmd_args):
        args = {'cmd': cmd,
                'args': cmd_args
               }
        self._session.call_plugin_serialized('xenhost', 'network_config', args)

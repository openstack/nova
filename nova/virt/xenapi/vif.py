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

from oslo_config import cfg

from nova.i18n import _
from nova.virt.xenapi import network_utils
from nova.virt.xenapi import vm_utils


xenapi_ovs_integration_bridge_opt = cfg.StrOpt('ovs_integration_bridge',
                        default='xapi1',
                        help='Name of Integration Bridge used by Open vSwitch')

CONF = cfg.CONF
CONF.register_opt(xenapi_ovs_integration_bridge_opt, 'xenserver')


class XenVIFDriver(object):
    def __init__(self, xenapi_session):
        self._session = xenapi_session


class XenAPIBridgeDriver(XenVIFDriver):
    """VIF Driver for XenAPI that uses XenAPI to create Networks."""

    def plug(self, instance, vif, vm_ref=None, device=None):
        if not vm_ref:
            vm_ref = vm_utils.lookup(self._session, instance['name'])
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
        return vif_rec

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
            pif_ref = None
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

    def unplug(self, instance, vif):
        pass


class XenAPIOpenVswitchDriver(XenVIFDriver):
    """VIF driver for Open vSwitch with XenAPI."""

    def plug(self, instance, vif, vm_ref=None, device=None):
        if not vm_ref:
            vm_ref = vm_utils.lookup(self._session, instance['name'])

        if not device:
            device = 0

        # with OVS model, always plug into an OVS integration bridge
        # that is already created
        network_ref = network_utils.find_network_with_bridge(
                self._session, CONF.xenserver.ovs_integration_bridge)
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
        return vif_rec

    def unplug(self, instance, vif):
        pass

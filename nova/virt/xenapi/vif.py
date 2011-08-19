# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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

from nova import flags
from nova import log as logging
from nova.virt.vif import VIFDriver
from nova.virt.xenapi.network_utils import NetworkHelper

FLAGS = flags.FLAGS
flags.DEFINE_string('xenapi_ovs_integration_bridge', 'xapi1',
                'Name of Integration Bridge used by Open vSwitch')

LOG = logging.getLogger("nova.virt.xenapi.vif")


class XenAPIBridgeDriver(VIFDriver):
    """VIF Driver for XenAPI that uses XenAPI to create Networks."""

    def plug(self, xenapi_session, vm_ref, instance, device, network,
                                                    network_mapping):
        if network_mapping.get('should_create_vlan'):
            network_ref = self.ensure_vlan_bridge(xenapi_session, network)
        else:
            network_ref = NetworkHelper.find_network_with_bridge(
                                        xenapi_session, network['bridge'])
        rxtx_cap = network_mapping.pop('rxtx_cap')
        vif_rec = {}
        vif_rec['device'] = str(device)
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = network_mapping['mac']
        vif_rec['MTU'] = '1500'
        vif_rec['other_config'] = {}
        vif_rec['qos_algorithm_type'] = "ratelimit" if rxtx_cap else ''
        vif_rec['qos_algorithm_params'] = \
                {"kbps": str(rxtx_cap * 1024)} if rxtx_cap else {}
        return vif_rec

    def ensure_vlan_bridge(self, xenapi_session, network):
        """Ensure that a VLAN bridge exists"""

        vlan_num = network['vlan']
        bridge = network['bridge']
        bridge_interface = network['bridge_interface']
        # Check whether bridge already exists
        # Retrieve network whose name_label is "bridge"
        network_ref = NetworkHelper.find_network_with_name_label(
                                        xenapi_session, bridge)
        if network_ref is None:
            # If bridge does not exists
            # 1 - create network
            description = 'network for nova bridge %s' % bridge
            network_rec = {'name_label': bridge,
                       'name_description': description,
                       'other_config': {}}
            network_ref = xenapi_session.call_xenapi('network.create',
                                                        network_rec)
            # 2 - find PIF for VLAN NOTE(salvatore-orlando): using double
            # quotes inside single quotes as xapi filter only support
            # tokens in double quotes
            expr = 'field "device" = "%s" and \
                field "VLAN" = "-1"' % bridge_interface
            pifs = xenapi_session.call_xenapi('PIF.get_all_records_where',
                                                                    expr)
            pif_ref = None
            # Multiple PIF are ok: we are dealing with a pool
            if len(pifs) == 0:
                raise Exception(_('Found no PIF for device %s') % \
                                        bridge_interface)
            for pif_ref in pifs.keys():
                xenapi_session.call_xenapi('VLAN.create',
                                pif_ref,
                                str(vlan_num),
                                network_ref)
        else:
            # Check VLAN tag is appropriate
            network_rec = xenapi_session.call_xenapi('network.get_record',
                                                            network_ref)
            # Retrieve PIFs from network
            for pif_ref in network_rec['PIFs']:
                # Retrieve VLAN from PIF
                pif_rec = xenapi_session.call_xenapi('PIF.get_record',
                                                                pif_ref)
                pif_vlan = int(pif_rec['VLAN'])
                # Raise an exception if VLAN != vlan_num
                if pif_vlan != vlan_num:
                    raise Exception(_(
                                "PIF %(pif_rec['uuid'])s for network "
                                "%(bridge)s has VLAN id %(pif_vlan)d. "
                                "Expected %(vlan_num)d") % locals())

        return network_ref

    def unplug(self, instance, network, mapping):
        pass


class XenAPIOpenVswitchDriver(VIFDriver):
    """VIF driver for Open vSwitch with XenAPI."""

    def plug(self, xenapi_session, vm_ref, instance, device, network,
                                                    network_mapping):
        # with OVS model, always plug into an OVS integration bridge
        # that is already created
        network_ref = NetworkHelper.find_network_with_bridge(xenapi_session,
                                        FLAGS.xenapi_ovs_integration_bridge)
        vif_rec = {}
        vif_rec['device'] = str(device)
        vif_rec['network'] = network_ref
        vif_rec['VM'] = vm_ref
        vif_rec['MAC'] = network_mapping['mac']
        vif_rec['MTU'] = '1500'
        vif_rec['qos_algorithm_type'] = ""
        vif_rec['qos_algorithm_params'] = {}
        # OVS on the hypervisor monitors this key and uses it to
        # set the iface-id attribute
        vif_rec['other_config'] = \
                {"nicira-iface-id": network_mapping['vif_uuid']}
        return vif_rec

    def unplug(self, instance, network, mapping):
        pass

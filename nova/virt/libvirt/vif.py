# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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

"""VIF drivers for libvirt."""

from nova import flags
from nova.network import linux_net
from nova.virt.libvirt import netutils
from nova.virt.vif import VIFDriver

FLAGS = flags.FLAGS
flags.DEFINE_bool('allow_project_net_traffic',
                  True,
                  'Whether to allow in project network traffic')


class LibvirtVIF(object):
    """VIF class for libvirt"""

    def get_configurations(self, instance, network, mapping):
        """Get a dictionary of VIF configuration for libvirt interfaces."""
        raise NotImplementedError()


class LibvirtBridge(LibvirtVIF):
    """Linux bridge VIF for Libvirt."""

    def get_configurations(self, instance, network, mapping):
        """Get a dictionary of VIF configurations for bridge type."""
        # Assume that the gateway also acts as the dhcp server.
        dhcp_server = mapping['gateway']
        gateway6 = mapping.get('gateway6')
        mac_id = mapping['mac'].replace(':', '')

        if FLAGS.allow_project_net_traffic:
            template = "<parameter name=\"%s\"value=\"%s\" />\n"
            net, mask = netutils.get_net_and_mask(network['cidr'])
            values = [("PROJNET", net), ("PROJMASK", mask)]
            if FLAGS.use_ipv6:
                net_v6, prefixlen_v6 = netutils.get_net_and_prefixlen(
                                           network['cidr_v6'])
                values.extend([("PROJNETV6", net_v6),
                               ("PROJMASKV6", prefixlen_v6)])

            extra_params = "".join([template % value for value in values])
        else:
            extra_params = "\n"

        result = {
            'id': mac_id,
            'bridge_name': network['bridge'],
            'mac_address': mapping['mac'],
            'ip_address': mapping['ips'][0]['ip'],
            'dhcp_server': dhcp_server,
            'extra_params': extra_params,
        }

        if gateway6:
            result['gateway6'] = gateway6 + "/128"

        return result

    
class LibvirtBridgeDriver(VIFDriver, LibvirtBridge):
    """VIF driver for Linux bridge."""

    def plug(self, network):
        """Ensure that the bridge exists, and add VIF to it."""
        linux_net.ensure_bridge(network['bridge'],
                                network['bridge_interface'])

    def unplug(self, network):
        pass


class LibvirtVlanBridgeDriver(VIFDriver, LibvirtBridge):
    """VIF driver for Linux bridge with VLAN."""

    def plug(self, network):
        """Ensure that VLAN and bridge exist and add VIF to the bridge."""
        linux_net.ensure_vlan_bridge(network['vlan'], network['bridge'],
                                     network['bridge_interface'])

    def unplug(self, network):
        pass

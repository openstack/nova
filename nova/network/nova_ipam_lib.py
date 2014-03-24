# Copyright 2011 Nicira Networks, Inc
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

import netaddr

from nova import ipv6
from nova.objects import fixed_ip as fixed_ip_obj
from nova.objects import floating_ip as floating_ip_obj
from nova.objects import network as network_obj
from nova.objects import virtual_interface as vif_obj


def get_ipam_lib(net_man):
    return NeutronNovaIPAMLib(net_man)


class NeutronNovaIPAMLib(object):
    """Implements Neutron IP Address Management (IPAM) interface
       using the local Nova database.  This implementation is inline
       with how IPAM is used by other NetworkManagers.
    """

    def __init__(self, net_manager):
        """Holds a reference to the "parent" network manager, used
           to take advantage of various FlatManager methods to avoid
           code duplication.
        """
        self.net_manager = net_manager

    def get_subnets_by_net_id(self, context, tenant_id, net_id, _vif_id=None):
        """Returns information about the IPv4 and IPv6 subnets
           associated with a Neutron Network UUID.
        """
        n = network_obj.Network.get_by_uuid(context.elevated(), net_id)
        subnet_v4 = {
            'network_id': n.uuid,
            'cidr': n.cidr,
            'gateway': n.gateway,
            'broadcast': n.broadcast,
            'netmask': n.netmask,
            'version': 4,
            'dns1': n.dns1,
            'dns2': n.dns2}
        #TODO(tr3buchet): I'm noticing we've assumed here that all dns is v4.
        #                 this is probably bad as there is no way to add v6
        #                 dns to nova
        subnet_v6 = {
            'network_id': n.uuid,
            'cidr': n.cidr_v6,
            'gateway': n.gateway_v6,
            'broadcast': None,
            'netmask': n.netmask_v6,
            'version': 6,
            'dns1': None,
            'dns2': None}

        def ips_to_strs(net):
            for key, value in net.items():
                if isinstance(value, netaddr.ip.BaseIP):
                    net[key] = str(value)
            return net

        return [ips_to_strs(subnet_v4), ips_to_strs(subnet_v6)]

    def get_routes_by_ip_block(self, context, block_id, project_id):
        """Returns the list of routes for the IP block."""
        return []

    def get_v4_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list of IPv4 address strings associated with
           the specified virtual interface, based on the fixed_ips table.
        """
        # TODO(tr3buchet): link fixed_ips to vif by uuid so only 1 db call
        vif_rec = vif_obj.VirtualInterface.get_by_uuid(context, vif_id)
        if not vif_rec:
            return []
        fixed_ips = fixed_ip_obj.FixedIPList.get_by_virtual_interface_id(
            context, vif_rec.id)
        return [str(fixed_ip.address) for fixed_ip in fixed_ips]

    def get_v6_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list containing a single IPv6 address strings
           associated with the specified virtual interface.
        """
        admin_context = context.elevated()
        network = network_obj.Network.get_by_uuid(admin_context, net_id)
        vif_rec = vif_obj.VirtualInterface.get_by_uuid(context, vif_id)
        if network.cidr_v6 and vif_rec and vif_rec.address:
            ip = ipv6.to_global(network.cidr_v6,
                                vif_rec.address,
                                project_id)
            return [ip]
        return []

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        return floating_ip_obj.FloatingIPList.get_by_fixed_address(
            context, fixed_address)

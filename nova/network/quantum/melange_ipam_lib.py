# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from netaddr import IPNetwork, IPAddress
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.network.quantum import melange_connection


LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


def get_ipam_lib(net_man):
    return QuantumMelangeIPAMLib()


class QuantumMelangeIPAMLib(object):
    """Implements Quantum IP Address Management (IPAM) interface
       using the Melange service, which is access using the Melange
       web services API.
    """

    def __init__(self):
        """Initialize class used to connect to Melange server"""
        self.m_conn = melange_connection.MelangeConnection()

    def create_subnet(self, context, label, project_id,
                      quantum_net_id, priority, cidr=None,
                      gateway=None, gateway_v6=None, cidr_v6=None,
                      dns1=None, dns2=None):
        """Contact Melange and create a subnet for any non-NULL
           IPv4 or IPv6 subnets.

           Also create a entry in the Nova networks DB, but only
           to store values not represented in Melange or to
           temporarily provide compatibility with Nova code that
           accesses IPAM data directly via the DB (e.g., nova-api)
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        if cidr:
            self.m_conn.create_block(quantum_net_id, cidr,
                                     project_id=tenant_id,
                                     gateway=gateway,
                                     dns1=dns1, dns2=dns2)
        if cidr_v6:
            self.m_conn.create_block(quantum_net_id, cidr_v6,
                                     project_id=tenant_id,
                                     gateway=gateway_v6,
                                     dns1=dns1, dns2=dns2)

        net = {"uuid": quantum_net_id,
               "project_id": tenant_id,
               "priority": priority,
               "label": label}
        if FLAGS.quantum_use_dhcp:
            if cidr:
                n = IPNetwork(cidr)
                net['dhcp_start'] = IPAddress(n.first + 2)
        else:
            net['dhcp_start'] = None
        admin_context = context.elevated()
        network = db.network_create_safe(admin_context, net)

    def allocate_fixed_ips(self, context, project_id, quantum_net_id,
                           network_tenant_id, vif_ref):
        """Pass call to allocate fixed IP on to Melange"""
        ips = self.m_conn.allocate_ip(quantum_net_id, network_tenant_id,
                                      vif_ref['uuid'], project_id,
                                      vif_ref['address'])
        return [ip['address'] for ip in ips]

    def delete_subnets_by_net_id(self, context, net_id, project_id):
        """Find Melange block associated with the Quantum UUID,
           then tell Melange to delete that block.
        """
        admin_context = context.elevated()
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['network_id'] == net_id:
                self.m_conn.delete_block(b['id'], tenant_id)

        network = db.network_get_by_uuid(admin_context, net_id)
        db.network_delete_safe(context, network['id'])

    def get_networks_by_tenant(self, admin_context, tenant_id):
        nets = {}
        blocks = self.m_conn.get_blocks(tenant_id)
        for ip_block in blocks['ip_blocks']:
            network_id = ip_block['network_id']
            network = db.network_get_by_uuid(admin_context, network_id)
            nets[network_id] = network
        return nets.values()

    def get_global_networks(self, admin_context):
        return self.get_networks_by_tenant(admin_context,
            FLAGS.quantum_default_tenant_id)

    def get_project_networks(self, admin_context):
        try:
            nets = db.network_get_all(admin_context.elevated())
        except exception.NoNetworksFound:
            return []
        # only return networks with a project_id set
        return [net for net in nets if net['project_id']]

    def get_project_and_global_net_ids(self, context, project_id):
        """Fetches all networks associated with this project, or
           that are "global" (i.e., have no project set).
           Returns list sorted by 'priority' (lowest integer value
           is highest priority).
        """
        if project_id is None:
            raise Exception(_("get_project_and_global_net_ids must be called"
                              " with a non-null project_id"))

        admin_context = context.elevated()

        # Decorate with priority
        priority_nets = []
        for tenant_id in (project_id, FLAGS.quantum_default_tenant_id):
            nets = self.get_networks_by_tenant(admin_context, tenant_id)
            for network in nets:
                priority = network['priority']
                priority_nets.append((priority, network['uuid'], tenant_id))

        # Sort by priority
        priority_nets.sort()

        # Undecorate
        return [(network_id, tenant_id)
                for priority, network_id, tenant_id in priority_nets]

    def get_tenant_id_by_net_id(self, context, net_id, vif_id, project_id):
        ipam_tenant_id = None
        tenant_ids = [FLAGS.quantum_default_tenant_id, project_id, None]
        # This is confusing, if there are IPs for the given net, vif,
        # tenant trifecta we assume that is the tenant for that network
        for tid in tenant_ids:
            try:
                self.m_conn.get_allocated_ips(net_id, vif_id, tid)
            except KeyError:
                continue
            ipam_tenant_id = tid
            break
        return ipam_tenant_id

    # TODO(bgh): Rename this method .. it's now more of a
    # "get_subnets_by_net_id_and_vif_id" method, but we could probably just
    # call it "get_subnets".
    def get_subnets_by_net_id(self, context, tenant_id, net_id, vif_id):
        """Returns information about the IPv4 and IPv6 subnets
           associated with a Quantum Network UUID.
        """
        subnets = []
        ips = self.m_conn.get_allocated_ips(net_id, vif_id, tenant_id)

        for ip_address in ips:
            block = ip_address['ip_block']
            subnet = {'network_id': block['network_id'],
                      'id': block['id'],
                      'cidr': block['cidr'],
                      'gateway': block['gateway'],
                      'broadcast': block['broadcast'],
                      'netmask': block['netmask'],
                      'dns1': block['dns1'],
                      'dns2': block['dns2']}
            if ip_address['version'] == 4:
                subnet['version'] = 4
            else:
                subnet['version'] = 6
            subnets.append(subnet)
        return subnets

    def get_routes_by_ip_block(self, context, block_id, project_id):
        """Returns the list of routes for the IP block"""
        return self.m_conn.get_routes(block_id, project_id)

    def get_v4_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list of IPv4 address strings associated with
           the specified virtual interface.
        """
        return self._get_ips_by_interface(context, net_id, vif_id,
                                                        project_id, 4)

    def get_v6_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list of IPv6 address strings associated with
           the specified virtual interface.
        """
        return self._get_ips_by_interface(context, net_id, vif_id,
                                                        project_id, 6)

    def _get_ips_by_interface(self, context, net_id, vif_id, project_id,
                              ip_version):
        """Helper method to fetch v4 or v6 addresses for a particular
           virtual interface.
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        ip_list = self.m_conn.get_allocated_ips(net_id, vif_id, tenant_id)
        return [ip['address'] for ip in ip_list
                if IPNetwork(ip['address']).version == ip_version]

    def verify_subnet_exists(self, context, project_id, quantum_net_id):
        """Confirms that a subnet exists that is associated with the
           specified Quantum Network UUID.
        """
        # TODO(bgh): Would be nice if we could just do something like:
        # GET /ipam/tenants/{tenant_id}/networks/{network_id}/ instead
        # of searching through all the blocks.  Checking for a 404
        # will then determine whether it exists.
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['network_id'] == quantum_net_id:
                return True
        return False

    def deallocate_ips_by_vif(self, context, project_id, net_id, vif_ref):
        """Deallocate all fixed IPs associated with the specified
           virtual interface.
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.m_conn.deallocate_ips(net_id, vif_ref['uuid'], tenant_id)

    def get_allocated_ips(self, context, subnet_id, project_id):
        ips = self.m_conn.get_allocated_ips_for_network(subnet_id, project_id)
        return [(ip['address'], ip['interface_id']) for ip in ips]

    def create_vif(self, vif_id, instance_id, project_id=None):
        """Create a new vif with the specified information.
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        return self.m_conn.create_vif(vif_id, instance_id, tenant_id)

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        """This call is not supported in quantum yet"""
        return []

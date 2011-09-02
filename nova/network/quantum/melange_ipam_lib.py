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

from netaddr import IPNetwork

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.network.quantum import melange_connection


LOG = logging.getLogger("nova.network.quantum.melange_ipam_lib")

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
                      gateway_v6=None, cidr_v6=None,
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
                                     dns1=dns1, dns2=dns2)
        if cidr_v6:
            self.m_conn.create_block(quantum_net_id, cidr_v6,
                                     project_id=tenant_id,
                                     dns1=dns1, dns2=dns2)

        net = {"uuid": quantum_net_id,
               "project_id": project_id,
               "priority": priority,
               "label": label}
        admin_context = context.elevated()
        network = db.network_create_safe(admin_context, net)

    def allocate_fixed_ip(self, context, project_id, quantum_net_id, vif_ref):
        """Pass call to allocate fixed IP on to Melange"""
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.m_conn.allocate_ip(quantum_net_id,
                                vif_ref['uuid'], project_id=tenant_id,
                                mac_address=vif_ref['address'])

    def get_network_id_by_cidr(self, context, cidr, project_id):
        """Find the Quantum UUID associated with a IPv4 CIDR
           address for the specified tenant.
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['cidr'] == cidr:
                return b['network_id']
        raise exception.NotFound(_("No network found for cidr %s" % cidr))

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
            blocks = self.m_conn.get_blocks(tenant_id)
            for ip_block in blocks['ip_blocks']:
                network_id = ip_block['network_id']
                network = db.network_get_by_uuid(admin_context, network_id)
                if network:
                    priority = network['priority']
                    priority_nets.append((priority, network_id, tenant_id))

        # Sort by priority
        priority_nets.sort()

        # Undecorate
        return [(network_id, tenant_id)
                for priority, network_id, tenant_id in priority_nets]

    def get_subnets_by_net_id(self, context, project_id, net_id):
        """Returns information about the IPv4 and IPv6 subnets
           associated with a Quantum Network UUID.
        """

        # FIXME(danwent):  Melange actually returns the subnet info
        # when we query for a particular interface.  We may want to
        # rework the ipam_manager python API to let us take advantage of
        # this, as right now we have to get all blocks and cycle through
        # them.
        subnet_v4 = None
        subnet_v6 = None
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['network_id'] == net_id:
                subnet = {'network_id': b['network_id'],
                          'cidr': b['cidr'],
                          'gateway': b['gateway'],
                          'broadcast': b['broadcast'],
                          'netmask': b['netmask'],
                          'dns1': b['dns1'],
                          'dns2': b['dns2']}

                if IPNetwork(b['cidr']).version == 6:
                    subnet_v6 = subnet
                else:
                    subnet_v4 = subnet
        return (subnet_v4, subnet_v6)

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
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        v4_subnet, v6_subnet = self.get_subnets_by_net_id(context, tenant_id,
                                    quantum_net_id)
        return v4_subnet is not None

    def deallocate_ips_by_vif(self, context, project_id, net_id, vif_ref):
        """Deallocate all fixed IPs associated with the specified
           virtual interface.
        """
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.m_conn.deallocate_ips(net_id, vif_ref['uuid'], tenant_id)

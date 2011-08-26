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

from nova import flags
from nova import log as logging
from nova.network.quantum import melange_connection


LOG = logging.getLogger("quantum_melange_ipam")

FLAGS = flags.FLAGS


def get_ipam_lib(net_man):
    return QuantumMelangeIPAMLib()


class QuantumMelangeIPAMLib:

    def __init__(self):
        self.m_conn = melange_connection.MelangeConnection()

    def create_subnet(self, context, label, project_id,
                                quantum_net_id, priority, cidr=None,
                                gateway_v6=None, cidr_v6=None,
                                dns1=None, dns2=None):
            tenant_id = project_id or FLAGS.quantum_default_tenant_id
            if cidr:
                self.m_conn.create_block(quantum_net_id, cidr,
                            project_id=tenant_id,
                            dns1=dns1, dns2=dns2)
            if cidr_v6:
                self.m_conn.create_block(quantum_net_id, cidr_v6,
                                     project_id=tenant_id,
                                     dns1=dns1, dns2=dns2)

            # create a entry in the network table just to store
            # the priority order for this network
            net = {"bridge": quantum_net_id,
                   "project_id": project_id,
                   "priority": priority}
            network = self.db.network_create_safe(context, net)

    def allocate_fixed_ip(self, context, project_id, quantum_net_id, vif_ref):
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.m_conn.allocate_ip(quantum_net_id,
                               vif_ref['uuid'], project_id=tenant_id,
                               mac_address=vif_ref['address'])

    def get_network_id_by_cidr(self, context, cidr, project_id):
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['cidr'] == cidr:
                return b['network_id']
        raise Exception("No network found for cidr %s" % cidr)

    def delete_subnets_by_net_id(self, context, net_id, project_id):
        admin_context = context.elevated()
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        all_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_blocks['ip_blocks']:
            if b['network_id'] == net_id:
                self.m_conn.delete_block(b['id'], tenant_id)

        network = db.network_get_by_bridge(admin_context, net_id)
        if network is not None:
            db.network_delete_safe(context, network['id'])

    # get all networks with this project_id, as well as all networks
    # where the project-id is not set (these are shared networks)
    def get_project_and_global_net_ids(self, context, project_id):
        admin_context = context.elevated()
        id_proj_map = {}
        if project_id is None:
            raise Exception("get_project_and_global_net_ids must be called" \
                    " with a non-null project_id")
        tenant_id = project_id
        all_tenant_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_tenant_blocks['ip_blocks']:
            id_proj_map[b['network_id']] = tenant_id
        tenant_id = FLAGS.quantum_default_tenant_id
        all_provider_blocks = self.m_conn.get_blocks(tenant_id)
        for b in all_provider_blocks['ip_blocks']:
            id_proj_map[b['network_id']] = tenant_id

        id_priority_map = {}
        network = db.network_get_by_bridge(admin_context, net_id)
        for net_id, project_id in id_project_map.item():
            network = db.network_get_by_bridge(admin_context, net_id)
            if network is None:
                del id_proj_map[net_id]
            else:
                id_priority_map[net_id] = network['priority']
        return sorted(id_priority_map.items(),
                        key=lambda x: id_priority_map[x[0]])

    # FIXME: there must be a more efficient way to do this,
    # talk to the melange folks
    def get_subnets_by_net_id(self, context, project_id, net_id):
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
        return self.get_ips_by_interface(context, net_id, vif_id,
                                                        project_id, 4)

    def get_v6_ips_by_interface(self, context, net_id, vif_id, project_id):
        return self.get_ips_by_interface(context, net_id, vif_id,
                                                        project_id, 6)

    def get_ips_by_interface(self, context, net_id, vif_id, project_id,
                                                               ip_version):
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        ip_list = self.m_conn.get_allocated_ips(net_id, vif_id, tenant_id)
        return [ip['address'] for ip in ip_list \
                        if IPNetwork(ip['address']).version == ip_version]

    def verify_subnet_exists(self, context, project_id, quantum_net_id):
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        v4_subnet, v6_subnet = self.get_subnets_by_net_id(context, tenant_id,
                                    quantum_net_id)
        return v4_subnet is not None

    def deallocate_ips_by_vif(self, context, project_id, net_id, vif_ref):
        tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.m_conn.deallocate_ips(net_id, vif_ref['uuid'], tenant_id)

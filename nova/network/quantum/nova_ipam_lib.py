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

import netaddr

from nova import db
from nova import exception
from nova import flags
from nova import ipv6
from nova import log as logging
from nova.network import manager
from nova.network.quantum import melange_connection as melange
from nova import utils


LOG = logging.getLogger("nova.network.quantum.nova_ipam_lib")

FLAGS = flags.FLAGS


def get_ipam_lib(net_man):
    return QuantumNovaIPAMLib(net_man)


class QuantumNovaIPAMLib(object):
    """Implements Quantum IP Address Management (IPAM) interface
       using the local Nova database.  This implementation is inline
       with how IPAM is used by other NetworkManagers.
    """

    def __init__(self, net_manager):
        """Holds a reference to the "parent" network manager, used
           to take advantage of various FlatManager methods to avoid
           code duplication.
        """
        self.net_manager = net_manager

    def create_subnet(self, context, label, tenant_id,
                      quantum_net_id, priority, cidr=None,
                      gateway_v6=None, cidr_v6=None,
                      dns1=None, dns2=None):
        """Re-use the basic FlatManager create_networks method to
           initialize the networks and fixed_ips tables in Nova DB.

           Also stores a few more fields in the networks table that
           are needed by Quantum but not the FlatManager.
        """
        admin_context = context.elevated()
        subnet_size = len(netaddr.IPNetwork(cidr))
        networks = manager.FlatManager.create_networks(self.net_manager,
                    admin_context, label, cidr,
                    False, 1, subnet_size, cidr_v6,
                    gateway_v6, quantum_net_id, None, dns1, dns2)

        if len(networks) != 1:
            raise Exception(_("Error creating network entry"))

        network = networks[0]
        net = {"project_id": tenant_id,
               "priority": priority,
               "uuid": quantum_net_id}
        db.network_update(admin_context, network['id'], net)

    def get_network_id_by_cidr(self, context, cidr, project_id):
        """ Grabs Quantum network UUID based on IPv4 CIDR. """
        admin_context = context.elevated()
        network = db.network_get_by_cidr(admin_context, cidr)
        if not network:
            raise Exception(_("No network with fixed_range = %s" %
                              fixed_range))
        return network['uuid']

    def delete_subnets_by_net_id(self, context, net_id, project_id):
        """Deletes a network based on Quantum UUID.  Uses FlatManager
           delete_network to avoid duplication.
        """
        admin_context = context.elevated()
        network = db.network_get_by_uuid(admin_context, net_id)
        if not network:
            raise Exception(_("No network with net_id = %s" % net_id))
        manager.FlatManager.delete_network(self.net_manager,
                                           admin_context, network['cidr'],
                                           require_disassociated=False)

    def get_project_and_global_net_ids(self, context, project_id):
        """Fetches all networks associated with this project, or
           that are "global" (i.e., have no project set).
           Returns list sorted by 'priority'.
        """
        admin_context = context.elevated()
        networks = db.project_get_networks(admin_context, project_id, False)
        networks.extend(db.project_get_networks(admin_context, None, False))
        id_priority_map = {}
        net_list = []
        for n in networks:
            net_id = n['uuid']
            net_list.append((net_id, n["project_id"]))
            id_priority_map[net_id] = n['priority']
        return sorted(net_list, key=lambda x: id_priority_map[x[0]])

    def allocate_fixed_ip(self, context, tenant_id, quantum_net_id, vif_rec):
        """Allocates a single fixed IPv4 address for a virtual interface."""
        admin_context = context.elevated()
        network = db.network_get_by_uuid(admin_context, quantum_net_id)
        if network['cidr']:
            address = db.fixed_ip_associate_pool(admin_context,
                                                 network['id'],
                                                 vif_rec['instance_id'])
            values = {'allocated': True,
                      'virtual_interface_id': vif_rec['id']}
            db.fixed_ip_update(admin_context, address, values)

    def get_subnets_by_net_id(self, context, tenant_id, net_id):
        """Returns information about the IPv4 and IPv6 subnets
           associated with a Quantum Network UUID.
        """
        n = db.network_get_by_uuid(context.elevated(), net_id)
        subnet_data_v4 = {
            'network_id': n['uuid'],
            'cidr': n['cidr'],
            'gateway': n['gateway'],
            'broadcast': n['broadcast'],
            'netmask': n['netmask'],
            'dns1': n['dns1'],
            'dns2': n['dns2']}
        subnet_data_v6 = {
            'network_id': n['uuid'],
            'cidr': n['cidr_v6'],
            'gateway': n['gateway_v6'],
            'broadcast': None,
            'netmask': None,
            'dns1': None,
            'dns2': None}
        return (subnet_data_v4, subnet_data_v6)

    def get_v4_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list of IPv4 address strings associated with
           the specified virtual interface, based on the fixed_ips table.
        """
        vif_rec = db.virtual_interface_get_by_uuid(context, vif_id)
        fixed_ips = db.fixed_ip_get_by_virtual_interface(context,
                                                         vif_rec['id'])
        return [fixed_ip['address'] for fixed_ip in fixed_ips]

    def get_v6_ips_by_interface(self, context, net_id, vif_id, project_id):
        """Returns a list containing a single IPv6 address strings
           associated with the specified virtual interface.
        """
        admin_context = context.elevated()
        network = db.network_get_by_uuid(admin_context, net_id)
        vif_rec = db.virtual_interface_get_by_uuid(context, vif_id)
        if network['cidr_v6']:
            ip = ipv6.to_global(network['cidr_v6'],
                                vif_rec['address'],
                                project_id)
            return [ip]
        return []

    def verify_subnet_exists(self, context, tenant_id, quantum_net_id):
        """Confirms that a subnet exists that is associated with the
           specified Quantum Network UUID.  Raises an exception if no
           such subnet exists.
        """
        admin_context = context.elevated()
        db.network_get_by_uuid(admin_context, quantum_net_id)

    def deallocate_ips_by_vif(self, context, tenant_id, net_id, vif_ref):
        """Deallocate all fixed IPs associated with the specified
           virtual interface.
        """
        try:
            admin_context = context.elevated()
            fixed_ips = db.fixed_ip_get_by_virtual_interface(admin_context,
                                                             vif_ref['id'])
            for fixed_ip in fixed_ips:
                db.fixed_ip_update(admin_context, fixed_ip['address'],
                                   {'allocated': False,
                                    'virtual_interface_id': None})
        except exception.FixedIpNotFoundForInstance:
            LOG.error(_('No fixed IPs to deallocate for vif %s' %
                            vif_ref['id']))

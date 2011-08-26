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

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import utils
from nova.network import manager
from nova.network.quantum import quantum_connection
from nova.network.quantum import fake

LOG = logging.getLogger("quantum_manager")

FLAGS = flags.FLAGS

flags.DEFINE_string('quantum_ipam_lib',
                    'nova.network.quantum.nova_ipam_lib',
                    "Indicates underlying IP address management library")


class QuantumManager(manager.FlatManager):

    def __init__(self, ipam_lib=None, *args, **kwargs):

        if FLAGS.fake_network:
            self.q_conn = fake.FakeQuantumClientConnection()
        else:
            self.q_conn = quantum_connection.QuantumClientConnection()

        if not ipam_lib:
            ipam_lib = FLAGS.quantum_ipam_lib
        self.ipam = utils.import_object(ipam_lib).get_ipam_lib(self)

        super(QuantumManager, self).__init__(*args, **kwargs)

    def create_networks(self, context, label, cidr, multi_host, num_networks,
                        network_size, cidr_v6, gateway_v6, bridge,
                        bridge_interface, dns1=None, dns2=None, **kwargs):
        if num_networks != 1:
            raise Exception("QuantumManager requires that only one"
                            " network is created per call")
        q_tenant_id = kwargs["project_id"] or \
                            FLAGS.quantum_default_tenant_id
        quantum_net_id = bridge
        if quantum_net_id:
            if not self.q_conn.network_exists(q_tenant_id, quantum_net_id):
                    raise Exception("Unable to find existing quantum " \
                        " network for tenant '%s' with net-id '%s'" % \
                         (q_tenant_id, quantum_net_id))
        else:
            # otherwise, create network from default quantum pool
            quantum_net_id = self.q_conn.create_network(q_tenant_id, label)

        ipam_tenant_id = kwargs.get("project_id", None)
        self.ipam.create_subnet(context, label, ipam_tenant_id, quantum_net_id,
                            cidr, gateway_v6, cidr_v6, dns1, dns2)

    def delete_network(self, context, fixed_range):
            project_id = context.project_id
            quantum_net_id = self.ipam.get_network_id_by_cidr(
                                    context, fixed_range, project_id)
            self.ipam.delete_subnets_by_net_id(context, quantum_net_id,
                                                            project_id)
            try:
                q_tenant_id = project_id or FLAGS.quantum_default_tenant_id
                self.q_conn.delete_network(q_tenant_id, quantum_net_id)
            except Exception, e:
                raise Exception("Unable to delete Quantum Network with "
                    "fixed_range = %s (ports still in use?)." % fixed_range)

    def allocate_for_instance(self, context, **kwargs):
        instance_id = kwargs.pop('instance_id')
        instance_type_id = kwargs['instance_type_id']
        host = kwargs.pop('host')
        project_id = kwargs.pop('project_id')
        LOG.debug(_("network allocations for instance %s"), instance_id)

        # if using the create-server-networks extension, 'requested_networks'
        # will be defined, otherwise, just grab relevant nets from IPAM
        requested_networks = kwargs.get('requested_networks')

        if requested_networks:
            net_proj_pairs = [(net_id, project_id) \
                for (net_id, _i) in requested_networks]
        else:
            net_proj_pairs = self.ipam.get_project_and_global_net_ids(context,
                                                                project_id)

        # Create a port via quantum and attach the vif
        for (net_id, project_id) in net_proj_pairs:
            vif_rec = manager.FlatManager.add_virtual_interface(self,
                                      context, instance_id, None)

            q_tenant_id = project_id or FLAGS.quantum_default_tenant_id
            self.q_conn.create_and_attach_port(q_tenant_id, net_id,
                                               vif_rec['uuid'])
            self.ipam.allocate_fixed_ip(context, project_id, net_id, vif_rec)

        return self.get_instance_nw_info(context, instance_id,
                                            instance_type_id, host)

    def get_instance_nw_info(self, context, instance_id,
                                instance_type_id, host):
        network_info = []
        project_id = context.project_id

        admin_context = context.elevated()
        vifs = db.virtual_interface_get_by_instance(admin_context,
                                                    instance_id)
        for vif in vifs:
            q_tenant_id = project_id
            ipam_tenant_id = project_id
            net_id, port_id = self.q_conn.get_port_by_attachment(q_tenant_id,
                                                                 vif['uuid'])
            if not net_id:
                q_tenant_id = FLAGS.quantum_default_tenant_id
                ipam_tenant_id = None
                net_id, port_id = self.q_conn.get_port_by_attachment(
                                             q_tenant_id, vif['uuid'])
            if not net_id:
                raise Exception(_("No network for for virtual interface %s") %\
                                        vif['uuid'])
            (v4_subnet, v6_subnet) = self.ipam.get_subnets_by_net_id(context,
                                        ipam_tenant_id, net_id)
            v4_ips = self.ipam.get_v4_ips_by_interface(context,
                                        net_id, vif['uuid'],
                                        project_id=ipam_tenant_id)
            v6_ips = self.ipam.get_v6_ips_by_interface(context,
                                        net_id, vif['uuid'],
                                        project_id=ipam_tenant_id)

            quantum_net_id = v4_subnet['network_id'] or v6_subnet['network_id']

            def ip_dict(ip, subnet):
                return {
                    "ip": ip,
                    "netmask": subnet["netmask"],
                    "enabled": "1"}

            network_dict = {
                'cidr': v4_subnet['cidr'],
                'injected': True,
                'multi_host': False}

            info = {
                'gateway': v4_subnet['gateway'],
                'dhcp_server': v4_subnet['gateway'],
                'broadcast': v4_subnet['broadcast'],
                'mac': vif['address'],
                'vif_uuid': vif['uuid'],
                'dns': [],
                'ips': [ip_dict(ip, v4_subnet) for ip in v4_ips]}

            if v6_subnet['cidr']:
                network_dict['cidr_v6'] = v6_subnet['cidr']
                info['ip6s'] = [ip_dict(ip, v6_subnet) for ip in v6_ips]
            # TODO(tr3buchet): handle ip6 routes here as well
            if v6_subnet['gateway']:
                info['gateway6'] = v6_subnet['gateway']

            dns_dict = {}
            for s in [v4_subnet, v6_subnet]:
                for k in ['dns1', 'dns2']:
                    if s[k]:
                        dns_dict[s[k]] = None
            info['dns'] = [d for d in dns_dict.keys()]

            network_info.append((network_dict, info))
        return network_info

    def deallocate_for_instance(self, context, **kwargs):
        instance_id = kwargs.get('instance_id')
        project_id = kwargs.pop('project_id', None)

        admin_context = context.elevated()
        vifs = db.virtual_interface_get_by_instance(admin_context,
                                                    instance_id)
        for vif_ref in vifs:
            interface_id = vif_ref['uuid']
            q_tenant_id = project_id
            ipam_tenant_id = project_id
            (net_id, port_id) = self.q_conn.get_port_by_attachment(q_tenant_id,
                                            interface_id)
            if not net_id:
                q_tenant_id = FLAGS.quantum_default_tenant_id
                ipam_tenant_id = None
                (net_id, port_id) = self.q_conn.get_port_by_attachment(
                                        q_tenant_id, interface_id)
            if not net_id:
                LOG.error("Unable to find port with attachment: %s" % \
                                                        (interface_id))
                continue
            self.q_conn.detach_and_delete_port(q_tenant_id,
                                                   net_id, port_id)

            self.ipam.deallocate_ips_by_vif(context, ipam_tenant_id,
                                                    net_id, vif_ref)

        self.net_manager.db.virtual_interface_delete_by_instance(admin_context,
                                                            instance_id)
        self._do_trigger_security_group_members_refresh_for_instance(
                                                                   instance_id)

    # validates that this tenant has quantum networks with the associated
    # UUIDs.  This is called by the 'os-create-server-ext' API extension
    # code so that we can return an API error code to the caller if they
    # request an invalid network.
    def validate_networks(self, context, networks):
        if networks is None:
            return

        project_id = context.project_id
        for (net_id, _i) in networks:
            self.ipam.verify_subnet_exists(context, project_id, net_id)
            if not self.q_conn.network_exists(project_id, net_id):
                raise exception.NetworkNotFound(network_id=net_id)

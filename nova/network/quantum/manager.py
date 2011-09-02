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
from nova.network import manager
from nova.network.quantum import quantum_connection
from nova import utils

LOG = logging.getLogger("nova.network.quantum.manager")

FLAGS = flags.FLAGS

flags.DEFINE_string('quantum_ipam_lib',
                    'nova.network.quantum.nova_ipam_lib',
                    "Indicates underlying IP address management library")


class QuantumManager(manager.FlatManager):
    """NetworkManager class that communicates with a Quantum service
       via a web services API to provision VM network connectivity.

       For IP Address management, QuantumManager can be configured to
       use either Nova's local DB or the Melange IPAM service.

       Currently, the QuantumManager does NOT support any of the 'gateway'
       functionality implemented by the Nova VlanManager, including:
            * floating IPs
            * DHCP
            * NAT gateway

       Support for these capabilities are targted for future releases.
    """

    def __init__(self, q_conn=None, ipam_lib=None, *args, **kwargs):
        """Initialize two key libraries, the connection to a
           Quantum service, and the library for implementing IPAM.

           Calls inherited FlatManager constructor.
        """

        if not q_conn:
            q_conn = quantum_connection.QuantumClientConnection()
        self.q_conn = q_conn

        if not ipam_lib:
            ipam_lib = FLAGS.quantum_ipam_lib
        self.ipam = utils.import_object(ipam_lib).get_ipam_lib(self)

        super(QuantumManager, self).__init__(*args, **kwargs)

    def create_networks(self, context, label, cidr, multi_host, num_networks,
                        network_size, cidr_v6, gateway_v6, bridge,
                        bridge_interface, dns1=None, dns2=None, uuid=None,
                        **kwargs):
        """Unlike other NetworkManagers, with QuantumManager, each
           create_networks calls should create only a single network.

           Two scenarios exist:
                - no 'uuid' is specified, in which case we contact
                  Quantum and create a new network.
                - an existing 'uuid' is specified, corresponding to
                  a Quantum network created out of band.

           In both cases, we initialize a subnet using the IPAM lib.
        """
        if num_networks != 1:
            raise Exception(_("QuantumManager requires that only one"
                              " network is created per call"))
        q_tenant_id = kwargs["project_id"] or FLAGS.quantum_default_tenant_id
        quantum_net_id = uuid
        if quantum_net_id:
            if not self.q_conn.network_exists(q_tenant_id, quantum_net_id):
                    raise Exception(_("Unable to find existing quantum " \
                        " network for tenant '%(q_tenant_id)s' with "
                        "net-id '%(quantum_net_id)s'" % locals()))
        else:
            # otherwise, create network from default quantum pool
            quantum_net_id = self.q_conn.create_network(q_tenant_id, label)

        ipam_tenant_id = kwargs.get("project_id", None)
        priority = kwargs.get("priority", 0)
        self.ipam.create_subnet(context, label, ipam_tenant_id, quantum_net_id,
                            priority, cidr, gateway_v6, cidr_v6, dns1, dns2)

    def delete_network(self, context, fixed_range):
        """Lookup network by IPv4 cidr, delete both the IPAM
           subnet and the corresponding Quantum network.
        """
        project_id = context.project_id
        quantum_net_id = self.ipam.get_network_id_by_cidr(
                                    context, fixed_range, project_id)
        self.ipam.delete_subnets_by_net_id(context, quantum_net_id,
                                                            project_id)
        q_tenant_id = project_id or FLAGS.quantum_default_tenant_id
        self.q_conn.delete_network(q_tenant_id, quantum_net_id)

    def allocate_for_instance(self, context, **kwargs):
        """Called by compute when it is creating a new VM.

           There are three key tasks:
                - Determine the number and order of vNICs to create
                - Allocate IP addresses
                - Create ports on a Quantum network and attach vNICs.

           We support two approaches to determining vNICs:
                - By default, a VM gets a vNIC for any network belonging
                  to the VM's project, and a vNIC for any "global" network
                  that has a NULL project_id.  vNIC order is determined
                  by the network's 'priority' field.
                - If the 'os-create-server-ext' was used to create the VM,
                  only the networks in 'requested_networks' are used to
                  create vNICs, and the vNIC order is determiend by the
                  order in the requested_networks array.

           For each vNIC, use the FlatManager to create the entries
           in the virtual_interfaces table, contact Quantum to
           create a port and attachment the vNIC, and use the IPAM
           lib to allocate IP addresses.
        """
        instance_id = kwargs.pop('instance_id')
        instance_type_id = kwargs['instance_type_id']
        host = kwargs.pop('host')
        project_id = kwargs.pop('project_id')
        LOG.debug(_("network allocations for instance %s"), instance_id)

        requested_networks = kwargs.get('requested_networks')

        if requested_networks:
            net_proj_pairs = [(net_id, project_id) \
                for (net_id, _i) in requested_networks]
        else:
            net_proj_pairs = self.ipam.get_project_and_global_net_ids(context,
                                                                project_id)

        # Create a port via quantum and attach the vif
        for (quantum_net_id, project_id) in net_proj_pairs:

            # FIXME(danwent): We'd like to have the manager be
            # completely decoupled from the nova networks table.
            # However, other parts of nova sometimes go behind our
            # back and access network data directly from the DB.  So
            # for now, the quantum manager knows that there is a nova
            # networks DB table and accesses it here.  updating the
            # virtual_interfaces table to use UUIDs would be one
            # solution, but this would require significant work
            # elsewhere.
            admin_context = context.elevated()
            network_ref = db.network_get_by_uuid(admin_context,
                                                 quantum_net_id)

            vif_rec = manager.FlatManager.add_virtual_interface(self,
                                  context, instance_id, network_ref['id'])

            # talk to Quantum API to create and attach port.
            q_tenant_id = project_id or FLAGS.quantum_default_tenant_id
            self.q_conn.create_and_attach_port(q_tenant_id, quantum_net_id,
                                               vif_rec['uuid'])
            self.ipam.allocate_fixed_ip(context, project_id, quantum_net_id,
                                        vif_rec)

        return self.get_instance_nw_info(context, instance_id,
                                         instance_type_id, host)

    def get_instance_nw_info(self, context, instance_id,
                                instance_type_id, host):
        """This method is used by compute to fetch all network data
           that should be used when creating the VM.

           The method simply loops through all virtual interfaces
           stored in the nova DB and queries the IPAM lib to get
           the associated IP data.

           The format of returned data is 'defined' by the initial
           set of NetworkManagers found in nova/network/manager.py .
           Ideally this 'interface' will be more formally defined
           in the future.
        """
        network_info = []
        instance = db.instance_get(context, instance_id)
        project_id = instance.project_id

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
                # TODO(bgh): We need to figure out a way to tell if we
                # should actually be raising this exception or not.
                # In the case that a VM spawn failed it may not have
                # attached the vif and raising the exception here
                # prevents deletion of the VM.  In that case we should
                # probably just log, continue, and move on.
                raise Exception(_("No network for for virtual interface %s") %
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

            if v6_subnet:
                if v6_subnet['cidr']:
                    network_dict['cidr_v6'] = v6_subnet['cidr']
                    info['ip6s'] = [ip_dict(ip, v6_subnet) for ip in v6_ips]

                if v6_subnet['gateway']:
                    info['gateway6'] = v6_subnet['gateway']

            dns_dict = {}
            for s in [v4_subnet, v6_subnet]:
                for k in ['dns1', 'dns2']:
                    if s and s[k]:
                        dns_dict[s[k]] = None
            info['dns'] = [d for d in dns_dict.keys()]

            network_info.append((network_dict, info))
        return network_info

    def deallocate_for_instance(self, context, **kwargs):
        """Called when a VM is terminated.  Loop through each virtual
           interface in the Nova DB and remove the Quantum port and
           clear the IP allocation using the IPAM.  Finally, remove
           the virtual interfaces from the Nova DB.
        """
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
                LOG.error("Unable to find port with attachment: %s" %
                          (interface_id))
                continue
            self.q_conn.detach_and_delete_port(q_tenant_id,
                                               net_id, port_id)

            self.ipam.deallocate_ips_by_vif(context, ipam_tenant_id,
                                            net_id, vif_ref)

        try:
            db.virtual_interface_delete_by_instance(admin_context,
                                                    instance_id)
        except exception.InstanceNotFound:
            LOG.error(_("Attempted to deallocate non-existent instance: %s" %
                        (instance_id)))

    def validate_networks(self, context, networks):
        """Validates that this tenant has quantum networks with the associated
           UUIDs.  This is called by the 'os-create-server-ext' API extension
           code so that we can return an API error code to the caller if they
           request an invalid network.
        """
        if networks is None:
            return

        project_id = context.project_id
        for (net_id, _i) in networks:
            self.ipam.verify_subnet_exists(context, project_id, net_id)
            if not self.q_conn.network_exists(project_id, net_id):
                raise exception.NetworkNotFound(network_id=net_id)

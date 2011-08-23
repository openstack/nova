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

from nova import exception
from nova import ipv6
from nova import log as logging
from nova import utils
import math
from netaddr import IPNetwork


LOG = logging.getLogger("network.quantum.fake")


# this class can be used for unit functional/testing on nova,
# as it does not actually make remote calls to the Quantum service
class FakeQuantumClientConnection:

    def __init__(self):
        self.nets = {}

    def get_networks_for_tenant(self, tenant_id):
        net_ids = []
        for net_id, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                net_ids.append(net_id)
        return net_ids

    def create_network(self, tenant_id, network_name):

        uuid = str(utils.gen_uuid())
        self.nets[uuid] = {'net-name': network_name,
                           'tenant-id': tenant_id,
                           'ports': {}}
        return uuid

    def delete_network(self, tenant_id, net_id):
        if self.nets[net_id]['tenant-id'] == tenant_id:
            del self.nets[net_id]

    def network_exists(self, tenant_id, net_id):
        try:
            return self.nets[net_id]['tenant-id'] == tenant_id
        except:
            return False

    def _confirm_not_attached(self, interface_id):
        for n in self.nets.values():
            for p in n['ports'].values():
                if p['attachment-id'] == interface_id:
                    raise Exception("interface '%s' is already attached" %\
                                        interface_id)

    def create_and_attach_port(self, tenant_id, net_id, interface_id):
        if not self.network_exists(tenant_id, net_id):
            raise Exception("network %s does not exist for tenant %s" %\
                                (net_id, tenant_id))

        self._confirm_not_attached(interface_id)
        uuid = str(utils.gen_uuid())
        self.nets[net_id]['ports'][uuid] = \
                {"port-state": "ACTIVE",
                "attachment-id": interface_id}

    def detach_and_delete_port(self, tenant_id, net_id, port_id):
        if not self.network_exists(tenant_id, net_id):
            raise Exception("network %s does not exist for tenant %s" %\
                                (net_id, tenant_id))
        del self.nets[net_id]['ports'][port_id]

    def get_port_by_attachment(self, tenant_id, attachment_id):
        for net_id, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                for port_id, p in n['ports'].items():
                    if p['attachment-id'] == attachment_id:
                        return (net_id, port_id)

        return (None, None)


def get_ipam_lib(net_man):
    return FakeQuantumIPAMLib()


class FakeQuantumIPAMLib():

    def __init__(self):
        self.subnets = {}

    def create_subnet(self, context, label, tenant_id, quantum_net_id,
                                cidr=None, gateway_v6=None, cidr_v6=None,
                                dns1=None, dns2=None):
            if int(cidr.split("/")[1]) != 24:
                raise Exception("fake ipam_lib only supports /24s")
            v4_ips = []
            net_start = cidr[0:cidr.rfind(".") + 1]
            subnet_size = int(math.pow(2, (32 - int(cidr.split("/")[1]))))
            for i in xrange(2, subnet_size - 1):
                v4_ips.append({"ip": net_start + str(i),
                              "allocated": False,
                              "virtual_interface_id": None,
                              "instance_id": None})
            self.subnets[quantum_net_id] = {\
                    "label": label,
                    "gateway": net_start + "1",
                    "netmask": "255.255.255.0",
                    "broadcast": net_start + "255",
                    "cidr": cidr,
                    "gateway_v6": gateway_v6,
                    "cidr_v6": cidr_v6,
                    "dns1": dns1,
                    "dns2": dns2,
                    "project_id": tenant_id,
                    "v4_ips": v4_ips}

    def get_network_id_by_cidr(self, context, cidr, project_id):
            for net_id, s in self.subnets.items():
                if s['cidr'] == cidr or s['cidr_v6'] == cidr:
                    return net_id
            return None

    def delete_subnets_by_net_id(self, context, net_id, project_id):
        self.verify_subnet_exists(context, project_id, net_id)
        del self.subnets[net_id]

    def get_project_and_global_net_ids(self, context, project_id):
        net_ids = []
        for nid, s in self.subnets.items():
            if s['project_id'] == project_id or \
               s['project_id'] == None:
                    net_ids.append((nid, s['project_id']))
        return net_ids

    def allocate_fixed_ip(self, context, tenant_id, quantum_net_id, vif_rec):
        subnet = self.subnets[quantum_net_id]
        for i in xrange(0, len(subnet['v4_ips'])):
            ip = subnet['v4_ips'][i]
            if not ip['allocated']:
                subnet['v4_ips'][i] = {'ip': ip['ip'],
                                       'allocated': True,
                                       'virtual_interface_id': vif_rec['uuid'],
                                       'instance_id': vif_rec['instance_id']}
                return
        raise Exception("Unable to find available IP for net '%s'" %\
                        quantum_net_id)

    def get_subnets_by_net_id(self, context, tenant_id, net_id):
        self.verify_subnet_exists(context, tenant_id, net_id)

        subnet_data = self.subnets[net_id]
        subnet_data_v4 = {
                        'network_id': net_id,
                        'cidr': subnet_data['cidr'],
                        'gateway': subnet_data['gateway'],
                        'broadcast': subnet_data['broadcast'],
                        'netmask': subnet_data['netmask'],
                        'dns1': subnet_data['dns1'],
                        'dns2': subnet_data['dns2']}
        subnet_data_v6 = {
                        'network_id': net_id,
                        'cidr': subnet_data['cidr_v6'],
                        'gateway': subnet_data['gateway_v6'],
                        'broadcast': None,
                        'netmask': None,
                        'dns1': None,
                        'dns2': None}
        return (subnet_data_v4, subnet_data_v6)

    def get_v6_ips_by_interface(self, context, net_id, vif_id, project_id):
        self.verify_subnet_exists(context, project_id, net_id)

        subnet_data = self.subnets[net_id]
        if subnet_data['cidr_v6']:
            ip = ipv6.to_global(subnet_data['cidr_v6'],
                                "ca:fe:de:ad:be:ef",
                                project_id)
            return [ip]
        return []

    def get_v4_ips_by_interface(self, context, net_id, vif_id, project_id):
        self.verify_subnet_exists(context, project_id, net_id)

        subnet_data = self.subnets[net_id]
        for ip in subnet_data['v4_ips']:
            if ip['virtual_interface_id'] == vif_id:
                return [ip['ip']]
        return []

    def verify_subnet_exists(self, context, tenant_id, quantum_net_id):
        if quantum_net_id not in self.subnets:
            raise exception.NetworkNotFound(network_id=quantum_net_id)

    def deallocate_ips_by_vif(self, context, tenant_id, net_id, vif_ref):
        s = self.subnets[net_id]
        for ip in s['v4_ips']:
            if ip['virtual_interface_id'] == vif_ref['id']:
                ip['allocated'] = False
                ip['instance_id'] = None
                ip['virtual_interface_id'] = None

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack, LLC
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

"""Stubouts, mocks and fixtures for the test suite"""

import time

from nova import db
from nova import exception
from nova import test
from nova import utils


class FakeModel(object):
    """Stubs out for model."""
    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        return self.values[name]

    def __getitem__(self, key):
        if key in self.values:
            return self.values[key]
        else:
            raise NotImplementedError()

    def __repr__(self):
        return '<FakeModel: %s>' % self.values


def stub_out(stubs, funcs):
    """Set the stubs in mapping in the db api."""
    for func in funcs:
        func_name = '_'.join(func.__name__.split('_')[1:])
        stubs.Set(db, func_name, func)


def stub_out_db_network_api(stubs):
    network_fields = {'id': 0,
                      'cidr': '192.168.0.0/24',
                      'netmask': '255.255.255.0',
                      'cidr_v6': 'dead:beef::/64',
                      'netmask_v6': '64',
                      'project_id': 'fake',
                      'label': 'fake',
                      'gateway': '192.168.0.1',
                      'bridge': 'fa0',
                      'bridge_interface': 'fake_fa0',
                      'broadcast': '192.168.0.255',
                      'gateway_v6': 'dead:beef::1',
                      'dns': '192.168.0.1',
                      'vlan': None,
                      'host': None,
                      'injected': False,
                      'vpn_public_address': '192.168.0.2'}

    fixed_ip_fields = {'id': 0,
                       'network_id': 0,
                       'network': FakeModel(network_fields),
                       'address': '192.168.0.100',
                       'instance': False,
                       'instance_id': 0,
                       'allocated': False,
                       'virtual_interface_id': 0,
                       'virtual_interface': None,
                       'floating_ips': []}

    flavor_fields = {'id': 0,
                     'rxtx_cap': 3}

    floating_ip_fields = {'id': 0,
                          'address': '192.168.1.100',
                          'fixed_ip_id': None,
                          'fixed_ip': None,
                          'project_id': None,
                          'auto_assigned': False}

    virtual_interface_fields = {'id': 0,
                                'address': 'DE:AD:BE:EF:00:00',
                                'network_id': 0,
                                'instance_id': 0,
                                'network': FakeModel(network_fields)}

    fixed_ips = [fixed_ip_fields]
    floating_ips = [floating_ip_fields]
    virtual_interfacees = [virtual_interface_fields]
    networks = [network_fields]

    def fake_floating_ip_allocate_address(context, project_id):
        ips = filter(lambda i: i['fixed_ip_id'] == None \
                           and i['project_id'] == None,
                     floating_ips)
        if not ips:
            raise exception.NoMoreFloatingIps()
        ips[0]['project_id'] = project_id
        return FakeModel(ips[0])

    def fake_floating_ip_deallocate(context, address):
        ips = filter(lambda i: i['address'] == address,
                     floating_ips)
        if ips:
            ips[0]['project_id'] = None
            ips[0]['auto_assigned'] = False

    def fake_floating_ip_disassociate(context, address):
        ips = filter(lambda i: i['address'] == address,
                     floating_ips)
        if ips:
            fixed_ip_address = None
            if ips[0]['fixed_ip']:
                fixed_ip_address = ips[0]['fixed_ip']['address']
            ips[0]['fixed_ip'] = None
            ips[0]['host'] = None
            return fixed_ip_address

    def fake_floating_ip_fixed_ip_associate(context, floating_address,
                                            fixed_address, host):
        float = filter(lambda i: i['address'] == floating_address,
                       floating_ips)
        fixed = filter(lambda i: i['address'] == fixed_address,
                       fixed_ips)
        if float and fixed:
            float[0]['fixed_ip'] = fixed[0]
            float[0]['fixed_ip_id'] = fixed[0]['id']
            float[0]['host'] = host

    def fake_floating_ip_get_all_by_host(context, host):
        # TODO(jkoelker): Once we get the patches that remove host from
        #                 the floating_ip table, we'll need to stub
        #                 this out
        pass

    def fake_floating_ip_get_by_address(context, address):
        if isinstance(address, FakeModel):
            # NOTE(tr3buchet): yo dawg, i heard you like addresses
            address = address['address']
        ips = filter(lambda i: i['address'] == address,
                     floating_ips)
        if not ips:
            raise exception.FloatingIpNotFoundForAddress(address=address)
        return FakeModel(ips[0])

    def fake_floating_ip_set_auto_assigned(contex, address):
        ips = filter(lambda i: i['address'] == address,
                     floating_ips)
        if ips:
            ips[0]['auto_assigned'] = True

    def fake_fixed_ip_associate(context, address, instance_id):
        ips = filter(lambda i: i['address'] == address,
                     fixed_ips)
        if not ips:
            raise exception.NoMoreFixedIps()
        ips[0]['instance'] = True
        ips[0]['instance_id'] = instance_id

    def fake_fixed_ip_associate_pool(context, network_id, instance_id):
        ips = filter(lambda i: (i['network_id'] == network_id \
                             or i['network_id'] is None) \
                            and not i['instance'],
                     fixed_ips)
        if not ips:
            raise exception.NoMoreFixedIps()
        ips[0]['instance'] = True
        ips[0]['instance_id'] = instance_id
        return ips[0]['address']

    def fake_fixed_ip_create(context, values):
        ip = dict(fixed_ip_fields)
        ip['id'] = max([i['id'] for i in fixed_ips] or [-1]) + 1
        for key in values:
            ip[key] = values[key]
        return ip['address']

    def fake_fixed_ip_disassociate(context, address):
        ips = filter(lambda i: i['address'] == address,
                     fixed_ips)
        if ips:
            ips[0]['instance_id'] = None
            ips[0]['instance'] = None
            ips[0]['virtual_interface'] = None
            ips[0]['virtual_interface_id'] = None

    def fake_fixed_ip_disassociate_all_by_timeout(context, host, time):
        return 0

    def fake_fixed_ip_get_by_instance(context, instance_id):
        ips = filter(lambda i: i['instance_id'] == instance_id,
                     fixed_ips)
        return [FakeModel(i) for i in ips]

    def fake_fixed_ip_get_by_address(context, address):
        ips = filter(lambda i: i['address'] == address,
                     fixed_ips)
        if ips:
            return FakeModel(ips[0])

    def fake_fixed_ip_get_network(context, address):
        ips = filter(lambda i: i['address'] == address,
                     fixed_ips)
        if ips:
            nets = filter(lambda n: n['id'] == ips[0]['network_id'],
                          networks)
            if nets:
                return FakeModel(nets[0])

    def fake_fixed_ip_update(context, address, values):
        ips = filter(lambda i: i['address'] == address,
                     fixed_ips)
        if ips:
            for key in values:
                ips[0][key] = values[key]
                if key == 'virtual_interface_id':
                    vif = filter(lambda x: x['id'] == values[key],
                                 virtual_interfacees)
                    if not vif:
                        continue
                    fixed_ip_fields['virtual_interface'] = FakeModel(vif[0])

    def fake_instance_type_get(context, id):
        if flavor_fields['id'] == id:
            return FakeModel(flavor_fields)

    def fake_virtual_interface_create(context, values):
        vif = dict(virtual_interface_fields)
        vif['id'] = max([m['id'] for m in virtual_interfacees] or [-1]) + 1
        for key in values:
            vif[key] = values[key]
        return FakeModel(vif)

    def fake_virtual_interface_delete_by_instance(context, instance_id):
        addresses = [m for m in virtual_interfacees \
                     if m['instance_id'] == instance_id]
        try:
            for address in addresses:
                virtual_interfacees.remove(address)
        except ValueError:
            pass

    def fake_virtual_interface_get_by_instance(context, instance_id):
        return [FakeModel(m) for m in virtual_interfacees \
                if m['instance_id'] == instance_id]

    def fake_virtual_interface_get_by_instance_and_network(context,
                                                           instance_id,
                                                           network_id):
        vif = filter(lambda m: m['instance_id'] == instance_id and \
                               m['network_id'] == network_id,
                     virtual_interfacees)
        if not vif:
            return None
        return FakeModel(vif[0])

    def fake_network_create_safe(context, values):
        net = dict(network_fields)
        net['id'] = max([n['id'] for n in networks] or [-1]) + 1
        for key in values:
            net[key] = values[key]
        return FakeModel(net)

    def fake_network_get(context, network_id):
        net = filter(lambda n: n['id'] == network_id, networks)
        if not net:
            return None
        return FakeModel(net[0])

    def fake_network_get_all(context):
        return [FakeModel(n) for n in networks]

    def fake_network_get_all_by_host(context, host):
        nets = filter(lambda n: n['host'] == host, networks)
        return [FakeModel(n) for n in nets]

    def fake_network_get_all_by_instance(context, instance_id):
        nets = filter(lambda n: n['instance_id'] == instance_id, networks)
        return [FakeModel(n) for n in nets]

    def fake_network_set_host(context, network_id, host_id):
        nets = filter(lambda n: n['id'] == network_id, networks)
        for net in nets:
            net['host'] = host_id
        return host_id

    def fake_network_update(context, network_id, values):
        nets = filter(lambda n: n['id'] == network_id, networks)
        for net in nets:
            for key in values:
                net[key] = values[key]

    def fake_project_get_networks(context, project_id):
        return [FakeModel(n) for n in networks \
                if n['project_id'] == project_id]

    def fake_queue_get_for(context, topic, node):
        return "%s.%s" % (topic, node)

    funcs = [fake_floating_ip_allocate_address,
             fake_floating_ip_deallocate,
             fake_floating_ip_disassociate,
             fake_floating_ip_fixed_ip_associate,
             fake_floating_ip_get_all_by_host,
             fake_floating_ip_get_by_address,
             fake_floating_ip_set_auto_assigned,
             fake_fixed_ip_associate,
             fake_fixed_ip_associate_pool,
             fake_fixed_ip_create,
             fake_fixed_ip_disassociate,
             fake_fixed_ip_disassociate_all_by_timeout,
             fake_fixed_ip_get_by_instance,
             fake_fixed_ip_get_by_address,
             fake_fixed_ip_get_network,
             fake_fixed_ip_update,
             fake_instance_type_get,
             fake_virtual_interface_create,
             fake_virtual_interface_delete_by_instance,
             fake_virtual_interface_get_by_instance,
             fake_virtual_interface_get_by_instance_and_network,
             fake_network_create_safe,
             fake_network_get,
             fake_network_get_all,
             fake_network_get_all_by_host,
             fake_network_get_all_by_instance,
             fake_network_set_host,
             fake_network_update,
             fake_project_get_networks,
             fake_queue_get_for]

    stub_out(stubs, funcs)


def stub_out_db_instance_api(stubs, injected=True):
    """Stubs out the db API for creating Instances."""

    INSTANCE_TYPES = {
        'm1.tiny': dict(id=2,
                        memory_mb=512,
                        vcpus=1,
                        local_gb=0,
                        flavorid=1,
                        rxtx_cap=1),
        'm1.small': dict(id=5,
                         memory_mb=2048,
                         vcpus=1,
                         local_gb=20,
                         flavorid=2,
                         rxtx_cap=2),
        'm1.medium':
            dict(id=1,
                 memory_mb=4096,
                 vcpus=2,
                 local_gb=40,
                 flavorid=3,
                 rxtx_cap=3),
        'm1.large': dict(id=3,
                         memory_mb=8192,
                         vcpus=4,
                         local_gb=80,
                         flavorid=4,
                         rxtx_cap=4),
        'm1.xlarge':
            dict(id=4,
                 memory_mb=16384,
                 vcpus=8,
                 local_gb=160,
                 flavorid=5,
                 rxtx_cap=5)}

    flat_network_fields = {'id': 'fake_flat',
                           'bridge': 'xenbr0',
                           'label': 'fake_flat_network',
                           'netmask': '255.255.255.0',
                           'cidr_v6': 'fe80::a00:0/120',
                           'netmask_v6': '120',
                           'gateway': '10.0.0.1',
                           'gateway_v6': 'fe80::a00:1',
                           'broadcast': '10.0.0.255',
                           'dns': '10.0.0.2',
                           'ra_server': None,
                           'injected': injected}

    vlan_network_fields = {'id': 'fake_vlan',
                           'bridge': 'br111',
                           'label': 'fake_vlan_network',
                           'netmask': '255.255.255.0',
                           'cidr_v6': 'fe80::a00:0/120',
                           'netmask_v6': '120',
                           'gateway': '10.0.0.1',
                           'gateway_v6': 'fe80::a00:1',
                           'broadcast': '10.0.0.255',
                           'dns': '10.0.0.2',
                           'ra_server': None,
                           'vlan': 111,
                           'injected': False}

    fixed_ip_fields = {'address': '10.0.0.3',
                       'address_v6': 'fe80::a00:3',
                       'network_id': 'fake_flat'}

    def fake_instance_type_get_all(context, inactive=0):
        return INSTANCE_TYPES

    def fake_instance_type_get_by_name(context, name):
        return INSTANCE_TYPES[name]

    def fake_instance_type_get(context, id):
        for name, inst_type in INSTANCE_TYPES.iteritems():
            if str(inst_type['id']) == str(id):
                return inst_type
        return None

    def fake_network_get_by_instance(context, instance_id):
        # Even instance numbers are on vlan networks
        if instance_id % 2 == 0:
            return FakeModel(vlan_network_fields)
        else:
            return FakeModel(flat_network_fields)

    def fake_network_get_all_by_instance(context, instance_id):
        # Even instance numbers are on vlan networks
        if instance_id % 2 == 0:
            return [FakeModel(vlan_network_fields)]
        else:
            return [FakeModel(flat_network_fields)]

    def fake_instance_get_fixed_addresses(context, instance_id):
        return [FakeModel(fixed_ip_fields).address]

    def fake_instance_get_fixed_addresses_v6(context, instance_id):
        return [FakeModel(fixed_ip_fields).address]

    def fake_fixed_ip_get_by_instance(context, instance_id):
        return [FakeModel(fixed_ip_fields)]

    funcs = [fake_network_get_by_instance,
             fake_network_get_all_by_instance,
             fake_instance_type_get_all,
             fake_instance_type_get_by_name,
             fake_instance_type_get,
             fake_instance_get_fixed_addresses,
             fake_instance_get_fixed_addresses_v6,
             fake_network_get_all_by_instance,
             fake_fixed_ip_get_by_instance]
    stub_out(stubs, funcs)

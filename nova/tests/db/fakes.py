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


def stub_out(stubs, funcs):
    """
    Set the stubs in mapping in the db api
    """
    for func in funcs:
        stubs.set(db, func.__name__.lstrip("fake_"), func)


def stub_out_db_network_api(stubs, host='localhost'):
    network_fields = {'id': 0,
                      'cidr': '192.168.0.0/24',
                      'netmask': '255.255.255.0'
                      'cidr_v6': 'dead:beef::/64',
                      'netmask_v6': '64'
                      'project_id': 'fake',
                      'label': 'fake',
                      'gateway': '192.168.0.1',
                      'bridge': 'fa0',
                      'bridge_interface': 'fake_fa0',
                      'broadcast': '192.168.0.255',
                      'gateway_v6': 'dead:beef::1',
                      'vlan': None,
                      'host': host}

    fixed_ip_fields = {'id': 0,
                       'address': '192.168.0.100',
                       'instance': True}

    flavor_fields = {'id': 0,
                     'rxtx_cap': 3}

    floating_ip_fields = {'id': 0,
                          'address': '192.168.1.100',
                          'fixed_ip_id': 0,
                          'fixed_ip': FakeModel(fixed_ip_fields),
                          'project_id': 'fake',
                          'host': host,
                          'auto_assigned': True}

    mac_address_fields = {'id': 0,
                          'address': 'DE:AD:BE:EF:00:00',
                          'network_id': 0,
                          'instance_id':0,
                          'network': FakeModel(network_fields)}
    

    def fake_floating_ip_allocate_address(context, host, project_id):
        return FakeModel(floating_ip_fields)

    def fake_floating_ip_deallocate(context, floating_address):
        pass

    def fake_floating_ip_disassociate(context, address):
        return fixed_ip_fields['address']

    def fake_floating_ip_fixed_ip_associate(context, floating_address,
                                            fixed_address):
        pass

    def fake_floating_ip_get_all_by_host(context, host):
        return [FakeModel(floating_ip_fields)]

    def fake_floating_ip_get_by_address(context, address):
        return FakeModel(floating_ip_fields)

    def fake_floating_ip_set_auto_assigned(contex, public_ip):
        pass

    def fake_fixed_ip_associate(context, address, instance_id):
        pass

    def fake_fixed_ip_associate_pool(context, network_id, instance_id):
        return fixed_ip_fields['address']

    def fake_fixed_ip_create(context, values):
        return values['address']

    def fake_fixed_ip_disassociate(context, address):
        pass

    def fake_fixed_ip_disassociate_all_by_timeout(context, host, time):
        return 1

    def fake_fixed_ip_get_all_by_instance(context, instance_id):
        return [FakeModel(fixed_ip_fields)]

    def fake_fixed_ip_get_by_address(context, address):
        ip = dict(fixed_ip_fields)
        ip['address'] = address
        return FakeModel(ip)

    def fake_fixed_ip_get_network(context, address):
        return FakeModel(network_fields)

    def fake_fixed_ip_update(context, address, values):
        pass

    def fake_instance_type_get_by_id(context, id):
        return FakeModel(flavor_fields)

    def fake_mac_address_create(context, values):
        return FakeModel(values)

    def fake_mac_address_delete_by_instance(context, instance_id):
        pass

    def fake_mac_address_get_all_by_instance(context, instance_id):
        mac = dict(mac_address_fields)
        mac['instance_id'] = instance_id
        return [FakeModel(mac)]

    def fake_mac_address_get_by_instance_and_network(context, instance_id,
                                                     network_id):
        mac = dict(mac_address_fields)
        mac['instance_id'] = instance_id
        mac['network_id'] = network_id
        return FakeModel(mac)

    def fake_network_create_safe(context, net):
        return True

    def fake_network_get(context, network_id):
        net = dict(network_fields)
        net['network_id'] = network_id
        return FakeModel(net)

    def fake_network_get_all(context):
        return [FakeModel(network_fields)]

    def fake_network_get_all_by_host(context, host)
        net = dict(network_fields)
        net['host'] = host
        return [FakeModel(net)]

    def fake_network_get_all_by_instance(context, instance_id)
        return [FakeModel(network_fields)]

    def fake_network_set_host(context, network_id, host_id):
        return host_id

    def fake_network_update(context, network_id, net):
        pass

    def fake_project_get_networks(context, project_id):
        net = dict(network_fields)
        net['project_id'] = project_id
        return [FakeModel(net)]

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
             fake_fixed_ip_get_all_by_instance,
             fake_fixed_ip_get_by_address,
             fake_fixed_ip_get_network,
             fake_fixed_ip_update,
             fake_instance_type_get_by_id,
             fake_mac_address_create,
             fake_mac_address_delete_by_instance,
             fake_mac_address_get_all_by_instance,
             fake_mac_address_get_by_instance_and_network,
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

    def fake_instance_type_get_by_id(context, id):
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

    def fake_fixed_ip_get_all_by_instance(context, instance_id):
        return [FakeModel(fixed_ip_fields)]

    funcs = [fake_network_get_by_instance
             fake_network_get_all_by_instance,
             fake_instance_type_get_all,
             fake_instance_type_get_by_name,
             fake_instance_type_get_by_id,
             fake_instance_get_fixed_addresses,
             fake_instance_get_fixed_addresses_v6,
             fake_network_get_all_by_instance,
             fake_fixed_ip_get_all_by_instance]
    stub_out(stubs, funcs)

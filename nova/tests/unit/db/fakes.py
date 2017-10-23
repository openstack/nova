# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 OpenStack Foundation
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

"""Stubouts, mocks and fixtures for the test suite."""

import copy
import datetime

from nova import exception


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

    def get(self, name):
        return self.values[name]


def stub_out(test, funcs):
    """Set the stubs in mapping in the db api."""
    for module, func in funcs.items():
        test.stub_out(module, func)


fixed_ip_fields = {'id': 0,
                   'network_id': 0,
                   'address': '192.168.0.100',
                   'instance': False,
                   'instance_uuid': 'eb57d790-fc60-4119-a51a-f2b0913bdc93',
                   'allocated': False,
                   'virtual_interface_id': 0,
                   'virtual_interface': None,
                   'floating_ips': []}

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

flavor_fields = {'id': 0,
                 'rxtx_cap': 3}

floating_ip_fields = {'id': 0,
                      'address': '192.168.1.100',
                      'fixed_ip_id': None,
                      'fixed_ip': None,
                      'project_id': None,
                      'pool': 'nova',
                      'auto_assigned': False}

virtual_interface_fields = {'id': 0,
                            'address': 'DE:AD:BE:EF:00:00',
                            'network_id': 0,
                            'instance_id': 0,
                            'network': FakeModel(network_fields)}

fixed_ips = [fixed_ip_fields]
floating_ips = [floating_ip_fields]
virtual_interfaces = [virtual_interface_fields]
networks = [network_fields]


def fake_floating_ip_allocate_address(context, project_id, pool,
                                      auto_assigned=False):
    ips = [i for i in floating_ips if i['fixed_ip_id'] is None and
           i['project_id'] is None and i['pool'] == pool]
    if not ips:
        raise exception.NoMoreFloatingIps()
    ips[0]['project_id'] = project_id
    ips[0]['auto_assigned'] = auto_assigned
    return FakeModel(ips[0])


def fake_floating_ip_deallocate(context, address):
    ips = [i for i in floating_ips if i['address'] == address]
    if ips:
        ips[0]['project_id'] = None
        ips[0]['auto_assigned'] = False


def fake_floating_ip_disassociate(context, address):
    ips = [i for i in floating_ips if i['address'] == address]
    if ips:
        fixed_ip_address = None
        if ips[0]['fixed_ip']:
            fixed_ip_address = ips[0]['fixed_ip']['address']
        ips[0]['fixed_ip'] = None
        ips[0]['host'] = None
        return fixed_ip_address


def fake_floating_ip_fixed_ip_associate(context, floating_address,
                                        fixed_address, host):
    float = [i for i in floating_ips if i['address'] == floating_address]
    fixed = [i for i in fixed_ips if i['address'] == fixed_address]
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
    ips = [i for i in floating_ips if i['address'] == address]
    if not ips:
        raise exception.FloatingIpNotFoundForAddress(address=address)
    return FakeModel(ips[0])


def fake_fixed_ip_associate(context, address, instance_id):
    ips = [i for i in fixed_ips if i['address'] == address]
    if not ips:
        raise exception.NoMoreFixedIps(net='fake_net')
    ips[0]['instance'] = True
    ips[0]['instance_id'] = instance_id


def fake_fixed_ip_associate_pool(context, network_id, instance_id):
    ips = [i for i in fixed_ips if not i['instance'] and
           (i['network_id'] == network_id or i['network_id'] is None)]
    if not ips:
        raise exception.NoMoreFixedIps(net=network_id)
    ips[0]['instance'] = True
    ips[0]['instance_id'] = instance_id
    return ips[0]['address']


def fake_fixed_ip_create(context, values):
    ip = dict(fixed_ip_fields)
    ip['id'] = max([i['id'] for i in fixed_ips] or [-1]) + 1
    for key in values:
        ip[key] = values[key]
    return ip


def fake_fixed_ip_disassociate(context, address):
    ips = [i for i in fixed_ips if i['address'] == address]
    if ips:
        ips[0]['instance_id'] = None
        ips[0]['instance'] = None
        ips[0]['virtual_interface'] = None
        ips[0]['virtual_interface_id'] = None


def fake_fixed_ip_disassociate_all_by_timeout(context, host, time):
    return 0


def fake_fixed_ip_get_all(context):
    return [FakeModel(i) for i in fixed_ips]


def fake_fixed_ip_get_by_instance(context, instance_uuid):
    ips = [i for i in fixed_ips if i['instance_uuid'] == instance_uuid]
    return [FakeModel(i) for i in ips]


def fake_fixed_ip_get_by_address(context, address):
    ips = [i for i in fixed_ips if i['address'] == address]
    if ips:
        return FakeModel(ips[0])


def fake_fixed_ip_update(context, address, values):
    ips = [i for i in fixed_ips if i['address'] == address]
    fif = copy.deepcopy(fixed_ip_fields)
    if ips:
        for key in values:
            ips[0][key] = values[key]
            if key == 'virtual_interface_id':
                vif = [v for v in virtual_interfaces
                       if v['id'] == values[key]]
                if not vif:
                    continue
                fif['virtual_interface'] = FakeModel(vif[0])


def fake_flavor_get(context, id):
    if flavor_fields['id'] == id:
        return FakeModel(flavor_fields)


def fake_virtual_interface_create(context, values):
    vif = dict(virtual_interface_fields)
    vif['id'] = max([m['id'] for m in virtual_interfaces] or [-1]) + 1
    for key in values:
        vif[key] = values[key]
    return FakeModel(vif)


def fake_virtual_interface_delete_by_instance(context, instance_id):
    vif = copy.copy(virtual_interfaces)
    addresses = [m for m in vif
                 if m['instance_id'] == instance_id]
    try:
        for address in addresses:
            vif.remove(address)
    except ValueError:
        pass


def fake_virtual_interface_get_by_instance(context, instance_id):
    return [FakeModel(m) for m in virtual_interfaces
            if m['instance_id'] == instance_id]


def fake_virtual_interface_get_by_instance_and_network(context,
                                                       instance_id,
                                                       network_id):
    vif = [v for v in virtual_interfaces if v['instance_id'] == instance_id
           and v['network_id'] == network_id]
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
    net = [n for n in networks if n['id'] == network_id]
    if not net:
        return None
    return FakeModel(net[0])


def fake_network_get_all(context):
    return [FakeModel(n) for n in networks]


def fake_network_get_all_by_host(context, host):
    nets = [n for n in networks if n['host'] == host]
    return [FakeModel(n) for n in nets]


def fake_network_set_host(context, network_id, host_id):
    nets = [n for n in networks if n['id'] == network_id]
    for net in nets:
        net['host'] = host_id
    return host_id


def fake_network_update(context, network_id, values):
    nets = [n for n in networks if n['id'] == network_id]
    for net in nets:
        for key in values:
            net[key] = values[key]


def fake_project_get_networks(context, project_id):
    return [FakeModel(n) for n in networks
            if n['project_id'] == project_id]


def stub_out_db_network_api(test):

    funcs = [fake_floating_ip_allocate_address,
             fake_floating_ip_deallocate,
             fake_floating_ip_disassociate,
             fake_floating_ip_fixed_ip_associate,
             fake_floating_ip_get_all_by_host,
             fake_floating_ip_get_by_address,
             fake_fixed_ip_associate,
             fake_fixed_ip_associate_pool,
             fake_fixed_ip_create,
             fake_fixed_ip_disassociate,
             fake_fixed_ip_disassociate_all_by_timeout,
             fake_fixed_ip_get_all,
             fake_fixed_ip_get_by_instance,
             fake_fixed_ip_get_by_address,
             fake_fixed_ip_update,
             fake_flavor_get,
             fake_virtual_interface_create,
             fake_virtual_interface_delete_by_instance,
             fake_virtual_interface_get_by_instance,
             fake_virtual_interface_get_by_instance_and_network,
             fake_network_create_safe,
             fake_network_get,
             fake_network_get_all,
             fake_network_get_all_by_host,
             fake_network_set_host,
             fake_network_update,
             fake_project_get_networks]
    funcs = {'nova.db.%s' % fn.__name__.replace('fake_', ''): fn
             for fn in funcs}

    stub_out(test, funcs)


def stub_out_db_instance_api(test, injected=True):
    """Stubs out the db API for creating Instances."""

    def _create_instance_type(**updates):
        instance_type = {'id': 2,
                         'name': 'm1.tiny',
                         'memory_mb': 512,
                         'vcpus': 1,
                         'vcpu_weight': None,
                         'root_gb': 0,
                         'ephemeral_gb': 10,
                         'flavorid': 1,
                         'rxtx_factor': 1.0,
                         'swap': 0,
                         'deleted_at': None,
                         'created_at': datetime.datetime(2014, 8, 8, 0, 0, 0),
                         'updated_at': None,
                         'deleted': False,
                         'disabled': False,
                         'is_public': True,
                         'extra_specs': {},
                         'description': None
                        }
        if updates:
            instance_type.update(updates)
        return instance_type

    INSTANCE_TYPES = {
        'm1.tiny': _create_instance_type(
                        id=2,
                        name='m1.tiny',
                        memory_mb=512,
                        vcpus=1,
                        vcpu_weight=None,
                        root_gb=0,
                        ephemeral_gb=10,
                        flavorid=1,
                        rxtx_factor=1.0,
                        swap=0),
        'm1.small': _create_instance_type(
                        id=5,
                        name='m1.small',
                        memory_mb=2048,
                        vcpus=1,
                        vcpu_weight=None,
                        root_gb=20,
                        ephemeral_gb=0,
                        flavorid=2,
                        rxtx_factor=1.0,
                        swap=1024),
        'm1.medium': _create_instance_type(
                        id=1,
                         name='m1.medium',
                         memory_mb=4096,
                         vcpus=2,
                         vcpu_weight=None,
                         root_gb=40,
                         ephemeral_gb=40,
                         flavorid=3,
                         rxtx_factor=1.0,
                         swap=0),
        'm1.large': _create_instance_type(
                        id=3,
                         name='m1.large',
                         memory_mb=8192,
                         vcpus=4,
                         vcpu_weight=10,
                         root_gb=80,
                         ephemeral_gb=80,
                         flavorid=4,
                         rxtx_factor=1.0,
                         swap=0),
        'm1.xlarge': _create_instance_type(
                         id=4,
                         name='m1.xlarge',
                         memory_mb=16384,
                         vcpus=8,
                         vcpu_weight=None,
                         root_gb=160,
                         ephemeral_gb=160,
                         flavorid=5,
                         rxtx_factor=1.0,
                         swap=0)}

    fixed_ip_fields = {'address': '10.0.0.3',
                       'address_v6': 'fe80::a00:3',
                       'network_id': 'fake_flat'}

    def fake_flavor_get_all(*a, **k):
        return INSTANCE_TYPES.values()

    @classmethod
    def fake_flavor_get_by_name(cls, context, name):
        return INSTANCE_TYPES[name]

    @classmethod
    def fake_flavor_get(cls, context, id):
        for inst_type in INSTANCE_TYPES.values():
            if str(inst_type['id']) == str(id):
                return inst_type
        return None

    def fake_fixed_ip_get_by_instance(context, instance_id):
        return [FakeModel(fixed_ip_fields)]

    funcs = {
        'nova.objects.flavor._flavor_get_all_from_db': (
            fake_flavor_get_all),
        'nova.objects.Flavor._flavor_get_by_name_from_db': (
            fake_flavor_get_by_name),
        'nova.objects.Flavor._flavor_get_from_db': fake_flavor_get,
        'nova.db.api.fixed_ip_get_by_instance': fake_fixed_ip_get_by_instance,
    }
    stub_out(test, funcs)

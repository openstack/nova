# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Rackspace
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import nova.context
from nova import db
from nova import exception
from nova import flags
from nova import utils
import nova.compute.utils
from nova.network import manager as network_manager
from nova.network.quantum import nova_ipam_lib
from nova.tests import fake_network_cache_model


HOST = "testhost"
FLAGS = flags.FLAGS


class FakeIptablesFirewallDriver(object):
    def __init__(self, **kwargs):
        pass

    def setattr(self, key, val):
        self.__setattr__(key, val)

    def apply_instance_filter(self, instance, network_info):
        pass


class FakeVIFDriver(object):

    def __init__(self, **kwargs):
        pass

    def setattr(self, key, val):
        self.__setattr__(key, val)

    def plug(self, instance, network, mapping):
        return {
            'id': 'fake',
            'bridge_name': 'fake',
            'mac_address': 'fake',
            'ip_address': 'fake',
            'dhcp_server': 'fake',
            'extra_params': 'fake',
        }


class FakeModel(dict):
    """Represent a model from the db"""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)

        def __getattr__(self, name):
            return self[name]


class FakeNetworkManager(network_manager.NetworkManager):
    """This NetworkManager doesn't call the base class so we can bypass all
    inherited service cruft and just perform unit tests.
    """

    class FakeDB:
        vifs = [{'id': 0,
                 'instance_id': 0,
                 'network_id': 1,
                 'address': 'DC:AD:BE:FF:EF:01'},
                {'id': 1,
                 'instance_id': 20,
                 'network_id': 21,
                 'address': 'DC:AD:BE:FF:EF:02'},
                {'id': 2,
                 'instance_id': 30,
                 'network_id': 31,
                 'address': 'DC:AD:BE:FF:EF:03'}]

        floating_ips = [dict(address='172.16.1.1',
                             fixed_ip_id=100),
                        dict(address='172.16.1.2',
                             fixed_ip_id=200),
                        dict(address='173.16.1.2',
                             fixed_ip_id=210)]

        fixed_ips = [dict(id=100,
                          address='172.16.0.1',
                          virtual_interface_id=0),
                     dict(id=200,
                          address='172.16.0.2',
                          virtual_interface_id=1),
                     dict(id=210,
                          address='173.16.0.2',
                          virtual_interface_id=2)]

        def fixed_ip_get_by_instance(self, context, instance_id):
            return [dict(address='10.0.0.0'), dict(address='10.0.0.1'),
                    dict(address='10.0.0.2')]

        def network_get_by_cidr(self, context, cidr):
            raise exception.NetworkNotFoundForCidr()

        def network_create_safe(self, context, net):
            fakenet = dict(net)
            fakenet['id'] = 999
            return fakenet

        def network_get(self, context, network_id):
            return {'cidr_v6': '2001:db8:69:%x::/64' % network_id}

        def network_get_all(self, context):
            raise exception.NoNetworksFound()

        def network_get_all_by_uuids(self, context):
            raise exception.NoNetworksFound()

        def network_disassociate(self, context, network_id):
            return True

        def virtual_interface_get_all(self, context):
            return self.vifs

        def instance_get_id_to_uuid_mapping(self, context, ids):
            # NOTE(jkoelker): This is just here until we can rely on UUIDs
            mapping = {}
            for id in ids:
                mapping[id] = str(utils.gen_uuid())
            return mapping

        def fixed_ips_by_virtual_interface(self, context, vif_id):
            return [ip for ip in self.fixed_ips
                    if ip['virtual_interface_id'] == vif_id]

    def __init__(self):
        self.db = self.FakeDB()
        self.deallocate_called = None

    def deallocate_fixed_ip(self, context, address=None, host=None):
        self.deallocate_called = address

    def _create_fixed_ips(self, context, network_id, fixed_cidr=None):
        pass


def fake_network(network_id, ipv6=None):
    if ipv6 is None:
        ipv6 = FLAGS.use_ipv6
    fake_network = {'id': network_id,
             'uuid': '00000000-0000-0000-0000-00000000000000%02d' % network_id,
             'label': 'test%d' % network_id,
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.%d.0/24' % network_id,
             'cidr_v6': None,
             'netmask': '255.255.255.0',
             'netmask_v6': None,
             'bridge': 'fake_br%d' % network_id,
             'bridge_interface': 'fake_eth%d' % network_id,
             'gateway': '192.168.%d.1' % network_id,
             'gateway_v6': None,
             'broadcast': '192.168.%d.255' % network_id,
             'dns1': '192.168.%d.3' % network_id,
             'dns2': '192.168.%d.4' % network_id,
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.%d.2' % network_id,
             'rxtx_base': '%d' % network_id * 10}
    if ipv6:
        fake_network['cidr_v6'] = '2001:db8:0:%x::/64' % network_id
        fake_network['gateway_v6'] = '2001:db8:0:%x::1' % network_id
        fake_network['netmask_v6'] = '64'

    return fake_network


def vifs(n):
    for x in xrange(1, n + 1):
        yield {'id': x,
               'address': 'DE:AD:BE:EF:00:%02x' % x,
               'uuid': '00000000-0000-0000-0000-00000000000000%02d' % x,
               'network_id': x,
               'instance_id': 0}


def floating_ip_ids():
    for i in xrange(1, 100):
        yield i


def fixed_ip_ids():
    for i in xrange(1, 100):
        yield i


floating_ip_id = floating_ip_ids()
fixed_ip_id = fixed_ip_ids()


def next_fixed_ip(network_id, num_floating_ips=0):
    next_id = fixed_ip_id.next()
    f_ips = [FakeModel(**next_floating_ip(next_id))
             for i in xrange(num_floating_ips)]
    return {'id': next_id,
            'network_id': network_id,
            'address': '192.168.%d.%03d' % (network_id, (next_id + 99)),
            'instance_id': 1,
            'allocated': False,
            # and since network_id and vif_id happen to be equivalent
            'virtual_interface_id': network_id,
            'floating_ips': f_ips}


def next_floating_ip(fixed_ip_id):
    next_id = floating_ip_id.next()
    return {'id': next_id,
            'address': '10.10.10.%03d' % (next_id + 99),
            'fixed_ip_id': fixed_ip_id,
            'project_id': None,
            'auto_assigned': False}


def ipv4_like(ip, match_string):
    ip = ip.split('.')
    match_octets = match_string.split('.')

    for i, octet in enumerate(match_octets):
        if octet == '*':
            continue
        if octet != ip[i]:
            return False
    return True


def fake_get_instance_nw_info(stubs, num_networks=1, ips_per_vif=2,
                              floating_ips_per_fixed_ip=0,
                              spectacular=False):
    # stubs is the self.stubs from the test
    # ips_per_vif is the number of ips each vif will have
    # num_floating_ips is number of float ips for each fixed ip
    network = network_manager.FlatManager(host=HOST)
    network.db = db

    # reset the fixed and floating ip generators
    global floating_ip_id, fixed_ip_id, fixed_ips
    floating_ip_id = floating_ip_ids()
    fixed_ip_id = fixed_ip_ids()
    fixed_ips = []

    networks = [fake_network(x) for x in xrange(1, num_networks + 1)]

    def fixed_ips_fake(*args, **kwargs):
        global fixed_ips
        ips = [next_fixed_ip(i, floating_ips_per_fixed_ip)
               for i in xrange(1, num_networks + 1)
               for j in xrange(ips_per_vif)]
        fixed_ips = ips
        return ips

    def floating_ips_fake(context, address):
        for ip in fixed_ips:
            if address == ip['address']:
                return ip['floating_ips']
        return []

    def fixed_ips_v6_fake():
        return ['2001:db8:0:%x::1' % i
                for i in xrange(1, num_networks + 1)]

    def virtual_interfaces_fake(*args, **kwargs):
        return [vif for vif in vifs(num_networks)]

    def vif_by_uuid_fake(context, uuid):
        return {'id': 1,
               'address': 'DE:AD:BE:EF:00:01',
               'uuid': uuid,
               'network_id': 1,
               'network': None,
               'instance_id': 0}

    def network_get_fake(context, network_id):
        nets = [n for n in networks if n['id'] == network_id]
        if not nets:
            raise exception.NetworkNotFound(network_id=network_id)
        return nets[0]

    def update_cache_fake(*args, **kwargs):
        pass

    def get_subnets_by_net_id(self, context, project_id, network_uuid,
                              vif_uuid):
        i = int(network_uuid[-2:])
        subnet_v4 = dict(
            cidr='192.168.%d.0/24' % i,
            dns1='192.168.%d.3' % i,
            dns2='192.168.%d.4' % i,
            gateway='192.168.%d.1' % i)

        subnet_v6 = dict(
            cidr='2001:db8:0:%x::/64' % i,
            gateway='fe80::def')
        return [subnet_v4, subnet_v6]

    def get_network_by_uuid(context, uuid):
        return dict(id=1,
                    cidr_v6='fe80::/64',
                    bridge='br0',
                    label='public')

    def get_v4_fake(*args, **kwargs):
        ips = fixed_ips_fake(*args, **kwargs)
        return [ip['address'] for ip in ips]

    def get_v6_fake(*args, **kwargs):
        return fixed_ips_v6_fake()

    stubs.Set(db, 'fixed_ip_get_by_instance', fixed_ips_fake)
    stubs.Set(db, 'floating_ip_get_by_fixed_address', floating_ips_fake)
    stubs.Set(db, 'virtual_interface_get_by_uuid', vif_by_uuid_fake)
    stubs.Set(db, 'network_get_by_uuid', get_network_by_uuid)
    stubs.Set(db, 'virtual_interface_get_by_instance', virtual_interfaces_fake)
    stubs.Set(db, 'network_get', network_get_fake)
    stubs.Set(db, 'instance_info_cache_update', update_cache_fake)

    stubs.Set(nova_ipam_lib.QuantumNovaIPAMLib, 'get_subnets_by_net_id',
              get_subnets_by_net_id)
    stubs.Set(nova_ipam_lib.QuantumNovaIPAMLib, 'get_v4_ips_by_interface',
                    get_v4_fake)
    stubs.Set(nova_ipam_lib.QuantumNovaIPAMLib, 'get_v6_ips_by_interface',
                    get_v6_fake)

    class FakeContext(nova.context.RequestContext):
        def is_admin(self):
            return True

    nw_model = network.get_instance_nw_info(
                FakeContext('fakeuser', 'fake_project'),
                0, 0, 3, None)
    if spectacular:
        return nw_model
    return nova.compute.utils.legacy_network_info(nw_model)


def stub_out_nw_api_get_instance_nw_info(stubs, func=None,
                                         num_networks=1,
                                         ips_per_vif=1,
                                         floating_ips_per_fixed_ip=0,
                                         spectacular=False):
    import nova.network

    def get_instance_nw_info(self, context, instance):
        return fake_get_instance_nw_info(stubs, num_networks=num_networks,
                        ips_per_vif=ips_per_vif,
                        floating_ips_per_fixed_ip=floating_ips_per_fixed_ip,
                        spectacular=spectacular)

    if func is None:
        func = get_instance_nw_info
    stubs.Set(nova.network.API, 'get_instance_nw_info', func)

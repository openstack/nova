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

from nova import db
from nova import flags
from nova import test
from nova.network import manager as network_manager


HOST = "testhost"
FLAGS = flags.FLAGS


class FakeModel(dict):
    """Represent a model from the db"""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)

        def __getattr__(self, name):
            return self[name]


flavor = {'id': 0,
          'name': 'fake_flavor',
          'memory_mb': 2048,
          'vcpus': 2,
          'local_gb': 10,
          'flavor_id': 0,
          'swap': 0,
          'rxtx_quota': 0,
          'rxtx_cap': 3}


def fake_network(network_id, ipv6=None):
    if ipv6 is None:
        ipv6 = FLAGS.use_ipv6
    fake_network = {'id': network_id,
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
                    'vpn_public_address': '192.168.%d.2' % network_id}
    if ipv6:
        fake_network['cidr_v6'] = '2001:db8:0:%x::/64' % network_id
        fake_network['gateway_v6'] = '2001:db8:0:%x::1' % network_id
        fake_network['netmask_v6'] = '64'

    return fake_network


def vifs(n):
    for x in xrange(n):
        yield {'id': x,
               'address': 'DE:AD:BE:EF:00:%02x' % x,
               'uuid': '00000000-0000-0000-0000-00000000000000%02d' % x,
               'network_id': x,
               'network': FakeModel(**fake_network(x)),
               'instance_id': 0}


def floating_ip_ids():
    for i in xrange(99):
        yield i


def fixed_ip_ids():
    for i in xrange(99):
        yield i


floating_ip_id = floating_ip_ids()
fixed_ip_id = fixed_ip_ids()


def next_fixed_ip(network_id, num_floating_ips=0):
    next_id = fixed_ip_id.next()
    f_ips = [FakeModel(**next_floating_ip(next_id))
             for i in xrange(num_floating_ips)]
    return {'id': next_id,
            'network_id': network_id,
            'address': '192.168.%d.1%02d' % (network_id, next_id),
            'instance_id': 0,
            'allocated': False,
            # and since network_id and vif_id happen to be equivalent
            'virtual_interface_id': network_id,
            'floating_ips': f_ips}


def next_floating_ip(fixed_ip_id):
    next_id = floating_ip_id.next()
    return {'id': next_id,
            'address': '10.10.10.1%02d' % next_id,
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
                              floating_ips_per_fixed_ip=0):
    # stubs is the self.stubs from the test
    # ips_per_vif is the number of ips each vif will have
    # num_floating_ips is number of float ips for each fixed ip
    network = network_manager.FlatManager(host=HOST)
    network.db = db

    # reset the fixed and floating ip generators
    global floating_ip_id, fixed_ip_id
    floating_ip_id = floating_ip_ids()
    fixed_ip_id = fixed_ip_ids()

    def fixed_ips_fake(*args, **kwargs):
        return [next_fixed_ip(i, floating_ips_per_fixed_ip)
                for i in xrange(num_networks) for j in xrange(ips_per_vif)]

    def virtual_interfaces_fake(*args, **kwargs):
        return [vif for vif in vifs(num_networks)]

    def instance_type_fake(*args, **kwargs):
        return flavor

    stubs.Set(db, 'fixed_ip_get_by_instance', fixed_ips_fake)
    stubs.Set(db, 'virtual_interface_get_by_instance', virtual_interfaces_fake)
    stubs.Set(db, 'instance_type_get', instance_type_fake)

    return network.get_instance_nw_info(None, 0, 0, None)

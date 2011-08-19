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
from nova import test
from nova.network import manager as network_manager


HOST = "testhost"


class FakeModel(dict):
    """Represent a model from the db"""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)

        def __getattr__(self, name):
            return self[name]


def fake_network(n):
    return {'id': n,
            'label': 'test%d' % n,
            'injected': False,
            'multi_host': False,
            'cidr': '192.168.%d.0/24' % n,
            'cidr_v6': '2001:db8:0:%x::/64' % n,
            'gateway_v6': '2001:db8:0:%x::1' % n,
            'netmask_v6': '64',
            'netmask': '255.255.255.0',
            'bridge': 'fa%d' % n,
            'bridge_interface': 'fake_br%d' % n,
            'gateway': '192.168.%d.1' % n,
            'broadcast': '192.168.%d.255' % n,
            'dns1': '192.168.%d.3' % n,
            'dns2': '192.168.%d.4' % n,
            'vlan': None,
            'host': None,
            'project_id': 'fake_project',
            'vpn_public_address': '192.168.%d.2' % n}


def fixed_ips(num_networks, num_ips):
    for network in xrange(num_networks):
        for ip in xrange(num_ips):
            yield {'id': network * ip,
                   'network_id': network,
                   'address': '192.168.%d.100' % network,
                   'instance_id': 0,
                   'allocated': False,
                   # and since network_id and vif_id happen to be equivalent
                   'virtual_interface_id': network,
                   'floating_ips': [FakeModel(**floating_ip)]}


flavor = {'id': 0,
          'rxtx_cap': 3}


floating_ip = {'id': 0,
               'address': '10.10.10.10',
               'fixed_ip_id': 0,
               'project_id': None,
               'auto_assigned': False}


def vifs(n):
    for x in xrange(n):
        yield {'id': x,
               'address': 'DE:AD:BE:EF:00:%02x' % x,
               'uuid': '00000000-0000-0000-0000-00000000000000%2d' % x,
               'network_id': x,
               'network': FakeModel(**fake_network(x)),
               'instance_id': 0}


def fake_get_instance_nw_info(stubs, n=1, ips_per_vif=2):
    network = network_manager.FlatManager(host=HOST)
    network.db = db

    def fixed_ips_fake(*args, **kwargs):
        return fixed_ips(n, ips_per_vif)

    def virtual_interfaces_fake(*args, **kwargs):
        return [vif for vif in vifs(n)]

    def instance_type_fake(*args, **kwargs):
        return flavor

    stubs.Set(db, 'fixed_ip_get_by_instance', fixed_ips_fake)
    stubs.Set(db, 'virtual_interface_get_by_instance', virtual_interfaces_fake)
    stubs.Set(db, 'instance_type_get', instance_type_fake)

    nw_info = network.get_instance_nw_info(None, 0, 0, None)

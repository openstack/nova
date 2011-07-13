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
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.network import manager as network_manager


import mox


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


HOST = "testhost"


class FakeModel(dict):
    """Represent a model from the db"""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)

        def __getattr__(self, name):
            return self[name]


networks = [{'id': 0,
             'label': 'test0',
             'injected': False,
             'cidr': '192.168.0.0/24',
             'cidr_v6': '2001:db8::/64',
             'gateway_v6': '2001:db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa0',
             'bridge_interface': 'fake_fa0',
             'gateway': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns': '192.168.0.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2'},
            {'id': 1,
             'label': 'test1',
             'injected': False,
             'cidr': '192.168.1.0/24',
             'cidr_v6': '2001:db9::/64',
             'gateway_v6': '2001:db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa1',
             'bridge_interface': 'fake_fa1',
             'gateway': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns': '192.168.0.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.1.2'}]


fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_id': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []},
             {'id': 0,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_id': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []}]


flavor = {'id': 0,
          'rxtx_cap': 3}


floating_ip_fields = {'id': 0,
                      'address': '192.168.10.100',
                      'fixed_ip_id': 0,
                      'project_id': None,
                      'auto_assigned': False}

vifs = [{'id': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'network_id': 0,
         'network': FakeModel(**networks[0]),
         'instance_id': 0},
        {'id': 1,
         'address': 'DE:AD:BE:EF:00:01',
         'network_id': 1,
         'network': FakeModel(**networks[1]),
         'instance_id': 0}]


class FlatNetworkTestCase(test.TestCase):
    def setUp(self):
        super(FlatNetworkTestCase, self).setUp()
        self.network = network_manager.FlatManager(host=HOST)
        self.network.db = db

    def test_set_network_hosts(self):
        self.mox.StubOutWithMock(db, 'network_get_all')
        self.mox.StubOutWithMock(db, 'network_set_host')
        self.mox.StubOutWithMock(db, 'network_update')

        db.network_get_all(mox.IgnoreArg()).AndReturn([networks[0]])
        db.network_set_host(mox.IgnoreArg(),
                            networks[0]['id'],
                            mox.IgnoreArg()).AndReturn(HOST)
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        self.network.set_network_hosts(None)

    def test_get_instance_nw_info(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_instance')
        self.mox.StubOutWithMock(db, 'virtual_interface_get_by_instance')
        self.mox.StubOutWithMock(db, 'instance_type_get_by_id')

        db.fixed_ip_get_by_instance(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips)
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn(vifs)
        db.instance_type_get_by_id(mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn(flavor)
        self.mox.ReplayAll()

        nw_info = self.network.get_instance_nw_info(None, 0, 0)

        self.assertTrue(nw_info)

        for i, nw in enumerate(nw_info):
            i8 = i + 8
            check = {'bridge': 'fa%s' % i,
                     'cidr': '192.168.%s.0/24' % i,
                     'cidr_v6': '2001:db%s::/64' % i8,
                     'id': i,
                     'injected': 'DONTCARE'}

            self.assertDictMatch(nw[0], check)

            check = {'broadcast': '192.168.%s.255' % i,
                     'dns': 'DONTCARE',
                     'gateway': '192.168.%s.1' % i,
                     'gateway6': '2001:db%s::1' % i8,
                     'ip6s': 'DONTCARE',
                     'ips': 'DONTCARE',
                     'label': 'test%s' % i,
                     'mac': 'DE:AD:BE:EF:00:0%s' % i,
                     'rxtx_cap': 'DONTCARE'}
            self.assertDictMatch(nw[1], check)

            check = [{'enabled': 'DONTCARE',
                      'ip': '2001:db%s::dcad:beff:feef:%s' % (i8, i),
                      'netmask': '64'}]
            self.assertDictListMatch(nw[1]['ip6s'], check)

            check = [{'enabled': '1',
                      'ip': '192.168.%s.100' % i,
                      'netmask': '255.255.255.0'}]
            self.assertDictListMatch(nw[1]['ips'], check)

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'network_get_requested_networks')
        self.mox.StubOutWithMock(db, "fixed_ip_validate_by_network_address")

        requested_networks = [(1, "192.168.0.100")]
        db.network_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        db.fixed_ip_validate_by_network_address(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips[0])

        self.mox.ReplayAll()
        self.network.validate_networks(None, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(None, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.StubOutWithMock(db, 'network_get_requested_networks')
        db.network_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_requested_networks')
        requested_networks = [(1, "192.168.0.100.1")]
        db.network_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, None,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_requested_networks')

        requested_networks = [(1, "")]
        db.network_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          None, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_requested_networks')

        requested_networks = [(1, None)]
        db.network_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)


class VlanNetworkTestCase(test.TestCase):
    def setUp(self):
        super(VlanNetworkTestCase, self).setUp()
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db

    def test_vpn_allocate_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_associate')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')

        db.fixed_ip_associate(mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              mox.IgnoreArg()).AndReturn('192.168.0.1')
        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn({'id': 0})
        self.mox.ReplayAll()

        network = dict(networks[0])
        network['vpn_private_address'] = '192.168.0.2'
        self.network.allocate_fixed_ip(None, 0, network, vpn=True)

    def test_allocate_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_by_address')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')

        db.fixed_ip_associate_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn('192.168.0.1')
        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn({'id': 0})
        self.mox.ReplayAll()

        network = dict(networks[0])
        network['vpn_private_address'] = '192.168.0.2'
        self.network.allocate_fixed_ip(None, 0, network)

    def test_create_networks_too_big(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=4094, vlan_start=1)

    def test_create_networks_too_many(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=100, vlan_start=1,
                          cidr='192.168.0.1/24', network_size=100)

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'project_get_requested_networks')
        self.mox.StubOutWithMock(db, "fixed_ip_validate_by_network_address")

        requested_networks = [(1, "192.168.0.100")]
        db.project_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        db.fixed_ip_validate_by_network_address(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips[0])
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(None, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.StubOutWithMock(db, 'project_get_requested_networks')
        db.project_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'project_get_requested_networks')

        requested_networks = [(1, "192.168.0.100.1")]
        db.project_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          None, requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'project_get_requested_networks')

        requested_networks = [(1, "")]
        db.project_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          None, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'project_get_requested_networks')

        requested_networks = [(1, None)]
        db.project_get_requested_networks(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)

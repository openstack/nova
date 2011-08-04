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
             'multi_host': False,
             'cidr': '192.168.0.0/24',
             'cidr_v6': '2001:db8::/64',
             'gateway_v6': '2001:db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa0',
             'bridge_interface': 'fake_fa0',
             'gateway': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2'},
            {'id': 1,
             'label': 'test1',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.1.0/24',
             'cidr_v6': '2001:db9::/64',
             'gateway_v6': '2001:db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa1',
             'bridge_interface': 'fake_fa1',
             'gateway': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
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

    def test_get_instance_nw_info(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_instance')
        self.mox.StubOutWithMock(db, 'virtual_interface_get_by_instance')
        self.mox.StubOutWithMock(db, 'instance_type_get')

        db.fixed_ip_get_by_instance(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips)
        db.virtual_interface_get_by_instance(mox.IgnoreArg(),
                                             mox.IgnoreArg()).AndReturn(vifs)
        db.instance_type_get(mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn(flavor)
        self.mox.ReplayAll()

        nw_info = self.network.get_instance_nw_info(None, 0, 0, None)

        self.assertTrue(nw_info)

        for i, nw in enumerate(nw_info):
            i8 = i + 8
            check = {'bridge': 'fa%s' % i,
                     'cidr': '192.168.%s.0/24' % i,
                     'cidr_v6': '2001:db%s::/64' % i8,
                     'id': i,
                     'multi_host': False,
                     'injected': 'DONTCARE',
                     'bridge_interface': 'fake_fa%s' % i,
                     'vlan': None}

            self.assertDictMatch(nw[0], check)

            check = {'broadcast': '192.168.%s.255' % i,
                     'dhcp_server': '192.168.%s.1' % i,
                     'dns': 'DONTCARE',
                     'gateway': '192.168.%s.1' % i,
                     'gateway6': '2001:db%s::1' % i8,
                     'ip6s': 'DONTCARE',
                     'ips': 'DONTCARE',
                     'label': 'test%s' % i,
                     'mac': 'DE:AD:BE:EF:00:0%s' % i,
                     'rxtx_cap': 'DONTCARE',
                     'should_create_vlan': False,
                     'should_create_bridge': False}
            self.assertDictMatch(nw[1], check)

            check = [{'enabled': 'DONTCARE',
                      'ip': '2001:db%s::dcad:beff:feef:%s' % (i8, i),
                      'netmask': '64'}]
            self.assertDictListMatch(nw[1]['ip6s'], check)

            check = [{'enabled': '1',
                      'ip': '192.168.%s.100' % i,
                      'netmask': '255.255.255.0'}]
            self.assertDictListMatch(nw[1]['ips'], check)


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
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')

        db.fixed_ip_associate_pool(mox.IgnoreArg(),
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


class CommonNetworkTestCase(test.TestCase):

    class FakeNetworkManager(network_manager.NetworkManager):
        """This NetworkManager doesn't call the base class so we can bypass all
        inherited service cruft and just perform unit tests.
        """

        class FakeDB:
            def fixed_ip_get_by_instance(self, context, instance_id):
                return [dict(address='10.0.0.0'),  dict(address='10.0.0.1'),
                        dict(address='10.0.0.2')]

            def network_get_by_cidr(self, context, cidr):
                raise exception.NetworkNotFoundForCidr()

            def network_create_safe(self, context, net):
                fakenet = {}
                fakenet['id'] = 999
                return fakenet

            def network_get_all(self, context):
                raise exception.NoNetworksFound()

        def __init__(self):
            self.db = self.FakeDB()
            self.deallocate_called = None

        def deallocate_fixed_ip(self, context, address):
            self.deallocate_called = address

    def fake_create_fixed_ips(self, context, network_id):
        return None

    def test_remove_fixed_ip_from_instance(self):
        manager = self.FakeNetworkManager()
        manager.remove_fixed_ip_from_instance(None, 99, '10.0.0.1')

        self.assertEquals(manager.deallocate_called, '10.0.0.1')

    def test_remove_fixed_ip_from_instance_bad_input(self):
        manager = self.FakeNetworkManager()
        self.assertRaises(exception.FixedIpNotFoundForSpecificInstance,
                          manager.remove_fixed_ip_from_instance,
                          None, 99, 'bad input')

    def test__validate_cidrs(self):
        manager = self.FakeNetworkManager()
        nets = manager._validate_cidrs(None, '192.168.0.0/24', 1, 256)
        self.assertEqual(1, len(nets))
        cidrs = [str(net) for net in nets]
        self.assertTrue('192.168.0.0/24' in cidrs)

    def test__validate_cidrs_split_exact_in_half(self):
        manager = self.FakeNetworkManager()
        nets = manager._validate_cidrs(None, '192.168.0.0/24', 2, 128)
        self.assertEqual(2, len(nets))
        cidrs = [str(net) for net in nets]
        self.assertTrue('192.168.0.0/25' in cidrs)
        self.assertTrue('192.168.0.128/25' in cidrs)

    def test__validate_cidrs_split_cidr_in_use_middle_of_range(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/24'}])
        self.mox.ReplayAll()
        nets = manager._validate_cidrs(None, '192.168.0.0/16', 4, 256)
        self.assertEqual(4, len(nets))
        cidrs = [str(net) for net in nets]
        exp_cidrs = ['192.168.0.0', '192.168.1.0', '192.168.3.0',
                     '192.168.4.0']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr + '/24' in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test__validate_cidrs_split_cidr_smaller_subnet_in_use(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/25'}])
        self.mox.ReplayAll()
        nets = manager._validate_cidrs(None, '192.168.0.0/16', 4, 256)
        self.assertEqual(4, len(nets))
        cidrs = [str(net) for net in nets]
        exp_cidrs = ['192.168.0.0', '192.168.1.0', '192.168.3.0',
                     '192.168.4.0']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr + '/24' in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test__validate_cidrs_one_in_use(self):
        manager = self.FakeNetworkManager()
        args = [None, '192.168.0.0/24', 2, 256]
        # ValueError: network_size * num_networks exceeds cidr size
        self.assertRaises(ValueError, manager._validate_cidrs, *args)

    def test__validate_cidrs_already_used(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.0.0/24'}])
        self.mox.ReplayAll()
        # ValueError: cidr already in use
        args = [None, '192.168.0.0/24', 1, 256]
        self.assertRaises(ValueError, manager._validate_cidrs, *args)

    def test__validate_cidrs_too_many(self):
        manager = self.FakeNetworkManager()
        args = [None, '192.168.0.0/24', 200, 256]
        # ValueError: Not enough subnets avail to satisfy requested
        #             num_networks
        self.assertRaises(ValueError, manager._validate_cidrs, *args)

    def test__validate_cidrs_split_partial(self):
        manager = self.FakeNetworkManager()
        nets = manager._validate_cidrs(None, '192.168.0.0/16', 2, 256)
        returned_cidrs = [str(net) for net in nets]
        print returned_cidrs
        self.assertTrue('192.168.0.0/24' in returned_cidrs)
        self.assertTrue('192.168.1.0/24' in returned_cidrs)

    def test__validate_cidrs_conflict_existing_supernet(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        fakecidr = [{'id': 1, 'cidr': '192.168.0.0/8'}]
        manager.db.network_get_all(ctxt).AndReturn(fakecidr)
        self.mox.ReplayAll()
        args = [None, '192.168.0.0/24', 1, 256]
        # ValueError: requested cidr (192.168.0.0/24) conflicts
        #             with existing supernet
        self.assertRaises(ValueError, manager._validate_cidrs, *args)

    def test_create_networks(self):
        cidr = '192.168.0.0/24'
        manager = self.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [None, 'foo', cidr, None, 1, 256, 'fd00::/48', None, None,
                None]
        result = manager.create_networks(*args)
        self.assertEqual(manager.create_networks(*args), None)

    def test_create_networks_cidr_already_used(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        fakecidr = [{'id': 1, 'cidr': '192.168.0.0/24'}]
        manager.db.network_get_all(ctxt).AndReturn(fakecidr)
        self.mox.ReplayAll()
        args = [None, 'foo', '192.168.0.0/24', None, 1, 256,
                 'fd00::/48', None, None, None]
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_create_networks_many(self):
        cidr = '192.168.0.0/16'
        manager = self.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [None, 'foo', cidr, None, 10, 256, 'fd00::/48', None, None,
                None]
        self.assertEqual(manager.create_networks(*args), None)

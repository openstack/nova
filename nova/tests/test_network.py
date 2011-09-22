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

from nova import context
from nova import db
from nova import exception
from nova import log as logging
from nova import test
from nova.network import manager as network_manager


import mox


LOG = logging.getLogger('nova.tests.network')


HOST = "testhost"


class FakeModel(dict):
    """Represent a model from the db"""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)

        def __getattr__(self, name):
            return self[name]


networks = [{'id': 0,
             'uuid': "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
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
             'host': HOST,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2'},
            {'id': 1,
             'uuid': "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
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
             'host': HOST,
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
         'uuid': '00000000-0000-0000-0000-0000000000000000',
         'network_id': 0,
         'network': FakeModel(**networks[0]),
         'instance_id': 0},
        {'id': 1,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'network': FakeModel(**networks[1]),
         'instance_id': 0},
        {'id': 2,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 2,
         'network': None,
         'instance_id': 0}]


class FlatNetworkTestCase(test.TestCase):
    def setUp(self):
        super(FlatNetworkTestCase, self).setUp()
        self.network = network_manager.FlatManager(host=HOST)
        self.network.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=False)

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
                     'vif_uuid': ('00000000-0000-0000-0000-000000000000000%s' %
                                  i),
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

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        self.mox.StubOutWithMock(db, "fixed_ip_get_by_address")

        requested_networks = [("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                               "192.168.1.100")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)

        fixed_ips[1]['network'] = FakeModel(**networks[1])
        fixed_ips[1]['instance'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips[1])

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        requested_networks = [(1, "192.168.0.100.1")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, None,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [(1, "")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          None, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [(1, None)]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.network.validate_networks(None, requested_networks)

    def test_add_fixed_ip_instance_without_vpn_requested_networks(self):
        self.mox.StubOutWithMock(db, 'network_get')
        self.mox.StubOutWithMock(db, 'network_update')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db, 'instance_get')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn({'id': 0})

        db.instance_get(mox.IgnoreArg(),
                        mox.IgnoreArg()).AndReturn({'security_groups':
                                                             [{'id': 0}]})
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn('192.168.0.101')
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg()).AndReturn(networks[0])
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, 1, HOST,
                                              networks[0]['id'])


class VlanNetworkTestCase(test.TestCase):
    def setUp(self):
        super(VlanNetworkTestCase, self).setUp()
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=False)

    def test_vpn_allocate_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_associate')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')

        db.fixed_ip_associate(mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              reserved=True).AndReturn('192.168.0.1')
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
        self.mox.StubOutWithMock(db, 'instance_get')

        db.instance_get(mox.IgnoreArg(),
                        mox.IgnoreArg()).AndReturn({'security_groups':
                                                             [{'id': 0}]})
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
        self.network.allocate_fixed_ip(self.context, 0, network)

    def test_create_networks_too_big(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=4094, vlan_start=1)

    def test_create_networks_too_many(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=100, vlan_start=1,
                          cidr='192.168.0.1/24', network_size=100)

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        self.mox.StubOutWithMock(db, "fixed_ip_get_by_address")

        requested_networks = [("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                               "192.168.1.100")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)

        fixed_ips[1]['network'] = FakeModel(**networks[1])
        fixed_ips[1]['instance'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                    mox.IgnoreArg()).AndReturn(fixed_ips[1])

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        requested_networks = [(1, "192.168.0.100.1")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, self.context,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [(1, "")]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          self.context, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [(1, None)]
        db.network_get_all_by_uuids(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                mox.IgnoreArg()).AndReturn(networks)
        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_cant_associate_associated_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake_floating_ip_get_by_address(context, address):
            return {'address': '10.10.10.10',
                    'fixed_ip': {'address': '10.0.0.1'}}
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address',
                                fake_floating_ip_get_by_address)

        self.assertRaises(exception.FloatingIpAlreadyInUse,
                          self.network.associate_floating_ip,
                          ctxt,
                          mox.IgnoreArg(),
                          mox.IgnoreArg())

    def test_add_fixed_ip_instance_without_vpn_requested_networks(self):
        self.mox.StubOutWithMock(db, 'network_get')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db, 'instance_get')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn({'id': 0})

        db.instance_get(mox.IgnoreArg(),
                        mox.IgnoreArg()).AndReturn({'security_groups':
                                                             [{'id': 0}]})
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn('192.168.0.101')
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg()).AndReturn(networks[0])
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, 1, HOST,
                                              networks[0]['id'])

    def test_ip_association_and_allocation_of_other_project(self):
        """Makes sure that we cannot deallocaate or disassociate
        a public ip of other project"""

        context1 = context.RequestContext('user', 'project1')
        context2 = context.RequestContext('user', 'project2')

        address = '1.2.3.4'
        float_addr = db.floating_ip_create(context1.elevated(),
                {'address': address,
                 'project_id': context1.project_id})

        instance = db.instance_create(context1,
                {'project_id': 'project1'})

        fix_addr = db.fixed_ip_associate_pool(context1.elevated(),
                1, instance['id'])

        # Associate the IP with non-admin user context
        self.assertRaises(exception.NotAuthorized,
                          self.network.associate_floating_ip,
                          context2,
                          float_addr,
                          fix_addr)

        # Deallocate address from other project
        self.assertRaises(exception.NotAuthorized,
                          self.network.deallocate_floating_ip,
                          context2,
                          float_addr)

        # Now Associates the address to the actual project
        self.network.associate_floating_ip(context1, float_addr, fix_addr)

        # Now try dis-associating from other project
        self.assertRaises(exception.NotAuthorized,
                          self.network.disassociate_floating_ip,
                          context2,
                          float_addr)

        # Clean up the ip addresses
        self.network.deallocate_floating_ip(context1, float_addr)
        self.network.deallocate_fixed_ip(context1, fix_addr)
        db.floating_ip_destroy(context1.elevated(), float_addr)
        db.fixed_ip_disassociate(context1.elevated(), fix_addr)


class CommonNetworkTestCase(test.TestCase):

    class FakeNetworkManager(network_manager.NetworkManager):
        """This NetworkManager doesn't call the base class so we can bypass all
        inherited service cruft and just perform unit tests.
        """

        class FakeDB:
            def fixed_ip_get_by_instance(self, context, instance_id):
                return [dict(address='10.0.0.0'), dict(address='10.0.0.1'),
                        dict(address='10.0.0.2')]

            def network_get_by_cidr(self, context, cidr):
                raise exception.NetworkNotFoundForCidr()

            def network_create_safe(self, context, net):
                fakenet = dict(net)
                fakenet['id'] = 999
                return fakenet

            def network_get_all(self, context):
                raise exception.NoNetworksFound()

        def __init__(self):
            self.db = self.FakeDB()
            self.deallocate_called = None

        def deallocate_fixed_ip(self, context, address):
            self.deallocate_called = address

        def _create_fixed_ips(self, context, network_id):
            pass

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

    def test_validate_cidrs(self):
        manager = self.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/24',
                                       False, 1, 256, None, None, None,
                                       None)
        self.assertEqual(1, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/24' in cidrs)

    def test_validate_cidrs_split_exact_in_half(self):
        manager = self.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/24',
                                       False, 2, 128, None, None, None,
                                       None)
        self.assertEqual(2, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/25' in cidrs)
        self.assertTrue('192.168.0.128/25' in cidrs)

    def test_validate_cidrs_split_cidr_in_use_middle_of_range(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/24'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 4, 256, None, None, None,
                                       None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test_validate_cidrs_smaller_subnet_in_use(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.9/25'}])
        self.mox.ReplayAll()
        # ValueError: requested cidr (192.168.2.0/24) conflicts with
        #             existing smaller cidr
        args = (None, 'fake', '192.168.2.0/24', False, 1, 256, None, None,
                None, None)
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_smaller_cidr_in_use(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/25'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 4, 256, None, None, None, None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test_validate_cidrs_split_smaller_cidr_in_use2(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.9/29'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.2.0/24',
                                       False, 3, 32, None, None, None, None)
        self.assertEqual(3, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.2.32/27', '192.168.2.64/27', '192.168.2.96/27']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/27' in cidrs)

    def test_validate_cidrs_split_all_in_use(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        in_use = [{'id': 1, 'cidr': '192.168.2.9/29'},
                  {'id': 2, 'cidr': '192.168.2.64/26'},
                  {'id': 3, 'cidr': '192.168.2.128/26'}]
        manager.db.network_get_all(ctxt).AndReturn(in_use)
        self.mox.ReplayAll()
        args = (None, 'fake', '192.168.2.0/24', False, 3, 64, None, None,
                None, None)
        # ValueError: Not enough subnets avail to satisfy requested num_
        #             networks - some subnets in requested range already
        #             in use
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_one_in_use(self):
        manager = self.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 2, 256, None, None,
                None, None)
        # ValueError: network_size * num_networks exceeds cidr size
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_already_used(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.0.0/24'}])
        self.mox.ReplayAll()
        # ValueError: cidr already in use
        args = (None, 'fake', '192.168.0.0/24', False, 1, 256, None, None,
                None, None)
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_too_many(self):
        manager = self.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 200, 256, None, None,
                None, None)
        # ValueError: Not enough subnets avail to satisfy requested
        #             num_networks
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_partial(self):
        manager = self.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 2, 256, None, None, None, None)
        returned_cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/24' in returned_cidrs)
        self.assertTrue('192.168.1.0/24' in returned_cidrs)

    def test_validate_cidrs_conflict_existing_supernet(self):
        manager = self.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        fakecidr = [{'id': 1, 'cidr': '192.168.0.0/8'}]
        manager.db.network_get_all(ctxt).AndReturn(fakecidr)
        self.mox.ReplayAll()
        args = (None, 'fake', '192.168.0.0/24', False, 1, 256, None, None,
                None, None)
        # ValueError: requested cidr (192.168.0.0/24) conflicts
        #             with existing supernet
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_create_networks(self):
        cidr = '192.168.0.0/24'
        manager = self.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [None, 'foo', cidr, None, 1, 256, 'fd00::/48', None, None,
                None]
        result = manager.create_networks(*args)
        self.assertTrue(manager.create_networks(*args))

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
        self.assertTrue(manager.create_networks(*args))

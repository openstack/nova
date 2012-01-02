# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Rackspace
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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
import mox

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import test
from nova import utils
from nova.network import manager as network_manager
from nova.network import api as network_api
from nova.tests import fake_network


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
                      'pool': 'nova',
                      'interface': 'eth0',
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
        temp = utils.import_object('nova.network.minidns.MiniDNS')
        self.network.instance_dns_manager = temp
        self.network.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=False)

    def tearDown(self):
        super(FlatNetworkTestCase, self).tearDown()
        self.network.instance_dns_manager.delete_dns_file()

    def test_get_instance_nw_info(self):
        fake_get_instance_nw_info = fake_network.fake_get_instance_nw_info

        nw_info = fake_get_instance_nw_info(self.stubs, 0, 2)
        self.assertFalse(nw_info)

        for i, (nw, info) in enumerate(nw_info):
            check = {'bridge': 'fake_br%d' % i,
                     'cidr': '192.168.%s.0/24' % i,
                     'cidr_v6': '2001:db8:0:%x::/64' % i,
                     'id': i,
                     'multi_host': False,
                     'injected': False,
                     'bridge_interface': 'fake_eth%d' % i,
                     'vlan': None}

            self.assertDictMatch(nw, check)

            check = {'broadcast': '192.168.%d.255' % i,
                     'dhcp_server': '192.168.%d.1' % i,
                     'dns': ['192.168.%d.3' % n, '192.168.%d.4' % n],
                     'gateway': '192.168.%d.1' % i,
                     'gateway_v6': '2001:db8:0:%x::1' % i,
                     'ip6s': 'DONTCARE',
                     'ips': 'DONTCARE',
                     'label': 'test%d' % i,
                     'mac': 'DE:AD:BE:EF:00:%02x' % i,
                     'rxtx_cap': "%d" % i * 3,
                     'vif_uuid':
                        '00000000-0000-0000-0000-00000000000000%02d' % i,
                     'rxtx_cap': 3,
                     'should_create_vlan': False,
                     'should_create_bridge': False}
            self.assertDictMatch(info, check)

            check = [{'enabled': 'DONTCARE',
                      'ip': '2001:db8::dcad:beff:feef:%s' % i,
                      'netmask': '64'}]
            self.assertDictListMatch(info['ip6s'], check)

            num_fixed_ips = len(info['ips'])
            check = [{'enabled': 'DONTCARE',
                      'ip': '192.168.%d.1%02d' % (i, ip_num),
                      'netmask': '255.255.255.0'}
                      for ip_num in xrange(num_fixed_ips)]
            self.assertDictListMatch(info['ips'], check)

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

    def test_validate_reserved(self):
        context_admin = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)
        nets = self.network.create_networks(context_admin, 'fake',
                                       '192.168.0.0/24', False, 1,
                                       256, None, None, None, None, None)
        self.assertEqual(1, len(nets))
        network = nets[0]
        self.assertEqual(3, db.network_count_reserved_ips(context_admin,
                        network['id']))

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
        db.instance_get(self.context,
                        1).AndReturn({'display_name': HOST})
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn('192.168.0.101')
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg()).AndReturn(networks[0])
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, 1, HOST,
                                              networks[0]['id'])

    def test_mini_dns_driver(self):
        zone1 = "example.org"
        zone2 = "example.com"
        driver = self.network.instance_dns_manager
        driver.create_entry("hostone", "10.0.0.1", 0, zone1)
        driver.create_entry("hosttwo", "10.0.0.2", 0, zone1)
        driver.create_entry("hostthree", "10.0.0.3", 0, zone1)
        driver.create_entry("hostfour", "10.0.0.4", 0, zone1)
        driver.create_entry("hostfive", "10.0.0.5", 0, zone2)

        driver.delete_entry("hostone", zone1)
        driver.modify_address("hostfour", "10.0.0.1", zone1)
        driver.modify_address("hostthree", "10.0.0.1", zone1)
        names = driver.get_entries_by_address("10.0.0.1", zone1)
        self.assertEqual(len(names), 2)
        self.assertIn('hostthree', names)
        self.assertIn('hostfour', names)

        names = driver.get_entries_by_address("10.0.0.5", zone2)
        self.assertEqual(len(names), 1)
        self.assertIn('hostfive', names)

        addresses = driver.get_entries_by_name("hosttwo", zone1)
        self.assertEqual(len(addresses), 1)
        self.assertIn('10.0.0.2', addresses)

    def test_instance_dns(self):
        fixedip = '192.168.0.101'
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

        db.instance_get(self.context,
                        1).AndReturn({'display_name': HOST})
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   mox.IgnoreArg()).AndReturn(fixedip)
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg()).AndReturn(networks[0])
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, 1, HOST,
                                              networks[0]['id'])
        addresses = self.network.instance_dns_manager.get_entries_by_name(HOST)
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], fixedip)


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

    def test_vpn_allocate_fixed_ip_no_network_id(self):
        network = dict(networks[0])
        network['vpn_private_address'] = '192.168.0.2'
        network['id'] = None
        context_admin = context.RequestContext('testuser', 'testproject',
                is_admin=True)
        self.assertRaises(exception.FixedIpNotFoundForNetwork,
                self.network.allocate_fixed_ip,
                context_admin,
                0,
                network,
                vpn=True)

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

    def test_floating_ip_owned_by_project(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        # raises because floating_ip project_id is None
        floating_ip = {'address': '10.0.0.1',
                       'project_id': None}
        self.assertRaises(exception.NotAuthorized,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # raises because floating_ip project_id is not equal to ctxt project_id
        floating_ip = {'address': '10.0.0.1',
                       'project_id': ctxt.project_id + '1'}
        self.assertRaises(exception.NotAuthorized,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # does not raise (floating ip is owned by ctxt project)
        floating_ip = {'address': '10.0.0.1',
                       'project_id': ctxt.project_id}
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

    def test_allocate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            return {'address': '10.0.0.1'}

        def fake2(*args, **kwargs):
            return 25

        def fake3(*args, **kwargs):
            return 0

        self.stubs.Set(self.network.db, 'floating_ip_allocate_address', fake1)

        # this time should raise
        self.stubs.Set(self.network.db, 'floating_ip_count_by_project', fake2)
        self.assertRaises(exception.QuotaError,
                          self.network.allocate_floating_ip,
                          ctxt,
                          ctxt.project_id)

        # this time should not
        self.stubs.Set(self.network.db, 'floating_ip_count_by_project', fake3)
        self.network.allocate_floating_ip(ctxt, ctxt.project_id)

    def test_deallocate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        def fake2(*args, **kwargs):
            return {'address': '10.0.0.1', 'fixed_ip_id': 1}

        def fake3(*args, **kwargs):
            return {'address': '10.0.0.1', 'fixed_ip_id': None}

        self.stubs.Set(self.network.db, 'floating_ip_deallocate', fake1)
        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # this time should raise because floating ip is associated to fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.assertRaises(exception.FloatingIpAssociated,
                          self.network.deallocate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

        # this time should not raise
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)
        self.network.deallocate_floating_ip(ctxt, ctxt.project_id)

    def test_associate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        # floating ip that's already associated
        def fake2(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'fixed_ip_id': 1}

        # floating ip that isn't associated
        def fake3(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'fixed_ip_id': None}

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'network': {'multi_host': False, 'host': 'jibberjabber'}}

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'network': {'multi_host': False, 'host': 'testhost'}}

        def fake6(*args, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # raises because floating_ip is already associated to a fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.assertRaises(exception.FloatingIpAssociated,
                          self.network.associate_floating_ip,
                          ctxt,
                          mox.IgnoreArg(),
                          mox.IgnoreArg())

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)

        # does not raise and makes call remotely
        self.local = True
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake4)
        self.stubs.Set(rpc, 'cast', fake6)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake5)
        self.stubs.Set(self.network, '_associate_floating_ip', fake7)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertTrue(self.local)

    def test_disassociate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        # floating ip that isn't associated
        def fake2(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'fixed_ip_id': None}

        # floating ip that is associated
        def fake3(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'fixed_ip_id': 1}

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'network': {'multi_host': False, 'host': 'jibberjabber'}}

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return {'address': '10.0.0.1',
                    'pool': 'nova',
                    'interface': 'eth0',
                    'network': {'multi_host': False, 'host': 'testhost'}}

        def fake6(*args, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # raises because floating_ip is not associated to a fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.assertRaises(exception.FloatingIpNotAssociated,
                          self.network.disassociate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)

        # does not raise and makes call remotely
        self.local = True
        self.stubs.Set(self.network.db, 'fixed_ip_get', fake4)
        self.stubs.Set(rpc, 'cast', fake6)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get', fake5)
        self.stubs.Set(self.network, '_disassociate_floating_ip', fake7)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertTrue(self.local)

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
    def fake_create_fixed_ips(self, context, network_id):
        return None

    def test_remove_fixed_ip_from_instance(self):
        manager = fake_network.FakeNetworkManager()
        manager.remove_fixed_ip_from_instance(None, 99, '10.0.0.1')

        self.assertEquals(manager.deallocate_called, '10.0.0.1')

    def test_remove_fixed_ip_from_instance_bad_input(self):
        manager = fake_network.FakeNetworkManager()
        self.assertRaises(exception.FixedIpNotFoundForSpecificInstance,
                          manager.remove_fixed_ip_from_instance,
                          None, 99, 'bad input')

    def test_validate_cidrs(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/24',
                                       False, 1, 256, None, None, None,
                                       None, None)
        self.assertEqual(1, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/24' in cidrs)

    def test_validate_cidrs_split_exact_in_half(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/24',
                                       False, 2, 128, None, None, None,
                                       None, None)
        self.assertEqual(2, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/25' in cidrs)
        self.assertTrue('192.168.0.128/25' in cidrs)

    def test_validate_cidrs_split_cidr_in_use_middle_of_range(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/24'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 4, 256, None, None, None,
                                       None, None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test_validate_cidrs_smaller_subnet_in_use(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.9/25'}])
        self.mox.ReplayAll()
        # ValueError: requested cidr (192.168.2.0/24) conflicts with
        #             existing smaller cidr
        args = (None, 'fake', '192.168.2.0/24', False, 1, 256, None, None,
                None, None, None)
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_smaller_cidr_in_use(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.0/25'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 4, 256, None, None, None, None,
                                       None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/24' in cidrs)

    def test_validate_cidrs_split_smaller_cidr_in_use2(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.2.9/29'}])
        self.mox.ReplayAll()
        nets = manager.create_networks(None, 'fake', '192.168.2.0/24',
                                       False, 3, 32, None, None, None, None,
                                       None)
        self.assertEqual(3, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.2.32/27', '192.168.2.64/27', '192.168.2.96/27']
        for exp_cidr in exp_cidrs:
            self.assertTrue(exp_cidr in cidrs)
        self.assertFalse('192.168.2.0/27' in cidrs)

    def test_validate_cidrs_split_all_in_use(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        in_use = [{'id': 1, 'cidr': '192.168.2.9/29'},
                  {'id': 2, 'cidr': '192.168.2.64/26'},
                  {'id': 3, 'cidr': '192.168.2.128/26'}]
        manager.db.network_get_all(ctxt).AndReturn(in_use)
        self.mox.ReplayAll()
        args = (None, 'fake', '192.168.2.0/24', False, 3, 64, None, None,
                None, None, None)
        # ValueError: Not enough subnets avail to satisfy requested num_
        #             networks - some subnets in requested range already
        #             in use
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_one_in_use(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 2, 256, None, None,
                None, None, None)
        # ValueError: network_size * num_networks exceeds cidr size
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_already_used(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        manager.db.network_get_all(ctxt).AndReturn([{'id': 1,
                                     'cidr': '192.168.0.0/24'}])
        self.mox.ReplayAll()
        # ValueError: cidr already in use
        args = (None, 'fake', '192.168.0.0/24', False, 1, 256, None, None,
                None, None, None)
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_too_many(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 200, 256, None, None,
                None, None, None)
        # ValueError: Not enough subnets avail to satisfy requested
        #             num_networks
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_partial(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(None, 'fake', '192.168.0.0/16',
                                       False, 2, 256, None, None, None, None,
                                       None)
        returned_cidrs = [str(net['cidr']) for net in nets]
        self.assertTrue('192.168.0.0/24' in returned_cidrs)
        self.assertTrue('192.168.1.0/24' in returned_cidrs)

    def test_validate_cidrs_conflict_existing_supernet(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        fakecidr = [{'id': 1, 'cidr': '192.168.0.0/8'}]
        manager.db.network_get_all(ctxt).AndReturn(fakecidr)
        self.mox.ReplayAll()
        args = (None, 'fake', '192.168.0.0/24', False, 1, 256, None, None,
                None, None, None)
        # ValueError: requested cidr (192.168.0.0/24) conflicts
        #             with existing supernet
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_create_networks(self):
        cidr = '192.168.0.0/24'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [None, 'foo', cidr, None, 1, 256, 'fd00::/48', None, None,
                None, None, None]
        self.assertTrue(manager.create_networks(*args))

    def test_create_networks_cidr_already_used(self):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        ctxt = mox.IgnoreArg()
        fakecidr = [{'id': 1, 'cidr': '192.168.0.0/24'}]
        manager.db.network_get_all(ctxt).AndReturn(fakecidr)
        self.mox.ReplayAll()
        args = [None, 'foo', '192.168.0.0/24', None, 1, 256,
                 'fd00::/48', None, None, None, None, None]
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_create_networks_many(self):
        cidr = '192.168.0.0/16'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [None, 'foo', cidr, None, 10, 256, 'fd00::/48', None, None,
                None, None, None]
        self.assertTrue(manager.create_networks(*args))

    def test_get_instance_uuids_by_ip_regex(self):
        manager = fake_network.FakeNetworkManager()
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '.*'})
        self.assertEqual(len(res), len(_vifs))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '10.0.0.1'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[1]['instance_id'])

        # Get instance 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '173.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[2]['instance_id'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.*'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_id'], _vifs[0]['instance_id'])
        self.assertEqual(res[1]['instance_id'], _vifs[1]['instance_id'])

        # Get instance 1 and 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '17..16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_id'], _vifs[1]['instance_id'])
        self.assertEqual(res[1]['instance_id'], _vifs[2]['instance_id'])

    def test_get_instance_uuids_by_ipv6_regex(self):
        manager = fake_network.FakeNetworkManager()
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*'})
        self.assertEqual(len(res), len(_vifs))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*1034.*'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '2001:.*2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[1]['instance_id'])

        # Get instance 2
        ip6 = '2001:db8:69:1f:dead:beff:feff:ef03'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[2]['instance_id'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*ef0[1,2]'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_id'], _vifs[0]['instance_id'])
        self.assertEqual(res[1]['instance_id'], _vifs[1]['instance_id'])

        # Get instance 1 and 2
        ip6 = '2001:db8:69:1.:dead:beff:feff:ef0.'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_id'], _vifs[1]['instance_id'])
        self.assertEqual(res[1]['instance_id'], _vifs[2]['instance_id'])

    def test_get_instance_uuids_by_ip(self):
        manager = fake_network.FakeNetworkManager()
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')

        # No regex for you!
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': '.*'})
        self.assertFalse(res)

        # Doesn't exist
        ip = '10.0.0.1'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertFalse(res)

        # Get instance 1
        ip = '172.16.0.2'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[1]['instance_id'])

        # Get instance 2
        ip = '173.16.0.2'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_id'], _vifs[2]['instance_id'])


class TestRPCFixedManager(network_manager.RPCAllocateFixedIP,
        network_manager.NetworkManager):
    """Dummy manager that implements RPCAllocateFixedIP"""


class RPCAllocateTestCase(test.TestCase):
    """Tests nova.network.manager.RPCAllocateFixedIP"""
    def setUp(self):
        super(RPCAllocateTestCase, self).setUp()
        self.rpc_fixed = TestRPCFixedManager()
        self.context = context.RequestContext('fake', 'fake')

    def test_rpc_allocate(self):
        """Test to verify bug 855030 doesn't resurface.

        Mekes sure _rpc_allocate_fixed_ip returns a value so the call
        returns properly and the greenpool completes."""
        address = '10.10.10.10'

        def fake_allocate(*args, **kwargs):
            return address

        def fake_network_get(*args, **kwargs):
            return {}

        self.stubs.Set(self.rpc_fixed, 'allocate_fixed_ip', fake_allocate)
        self.stubs.Set(self.rpc_fixed.db, 'network_get', fake_network_get)
        rval = self.rpc_fixed._rpc_allocate_fixed_ip(self.context,
                                                     'fake_instance',
                                                     'fake_network')
        self.assertEqual(rval, address)


class TestFloatingIPManager(network_manager.FloatingIP,
        network_manager.NetworkManager):
    """Dummy manager that implements FloatingIP"""


class FloatingIPTestCase(test.TestCase):
    """Tests nova.network.manager.FloatingIP"""
    def setUp(self):
        super(FloatingIPTestCase, self).setUp()
        self.network = TestFloatingIPManager()
        temp = utils.import_object('nova.network.minidns.MiniDNS')
        self.network.floating_dns_manager = temp
        self.network.db = db
        self.project_id = 'testproject'
        self.context = context.RequestContext('testuser', self.project_id,
            is_admin=False)

    def tearDown(self):
        super(FloatingIPTestCase, self).tearDown()
        self.network.floating_dns_manager.delete_dns_file()

    def test_double_deallocation(self):
        instance_ref = db.api.instance_create(self.context,
                {"project_id": self.project_id})
        # Run it twice to make it fault if it does not handle
        # instances without fixed networks
        # If this fails in either, it does not handle having no addresses
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])

    def test_floating_dns_zones(self):
        zone1 = "example.org"
        zone2 = "example.com"
        flags.FLAGS.floating_ip_dns_zones = [zone1, zone2]

        zones = self.network.get_dns_zones(self.context)
        self.assertEqual(len(zones), 2)
        self.assertEqual(zones[0], zone1)
        self.assertEqual(zones[1], zone2)

    def test_floating_dns_create_conflict(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)

        self.assertRaises(exception.FloatingIpDNSExists,
                          self.network.add_dns_entry, self.context,
                          address1, name1, "A", zone)

    def test_floating_create_and_get(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"
        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertFalse(entries)

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)
        self.network.add_dns_entry(self.context, address1, name2, "A", zone)
        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertEquals(len(entries), 2)
        self.assertEquals(entries[0], name1)
        self.assertEquals(entries[1], name2)

        entries = self.network.get_dns_entries_by_name(self.context,
                                                       name1, zone)
        self.assertEquals(len(entries), 1)
        self.assertEquals(entries[0], address1)

    def test_floating_dns_delete(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)
        self.network.add_dns_entry(self.context, address1, name2, "A", zone)
        self.network.delete_dns_entry(self.context, name1, zone)

        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertEquals(len(entries), 1)
        self.assertEquals(entries[0], name2)

        self.assertRaises(exception.NotFound,
                          self.network.delete_dns_entry, self.context,
                          name1, zone)

# Copyright 2011 Rackspace
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2013 IBM Corp.
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

import fixtures
import mock
from mox3 import mox
import netaddr
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import importutils
from oslo_utils import netutils
import six
import testtools

from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova import ipv6
from nova.network import floating_ips
from nova.network import linux_net
from nova.network import manager as network_manager
from nova.network import model as net_model
from nova.network import rpcapi as network_rpcapi
from nova import objects
from nova.objects import network as network_obj
from nova.objects import virtual_interface as vif_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_ldap
from nova.tests.unit import fake_network
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_fixed_ip
from nova.tests.unit.objects import test_floating_ip
from nova.tests.unit.objects import test_network
from nova.tests.unit.objects import test_service
from nova.tests.unit import utils as test_utils
from nova.tests import uuidsentinel as uuids
from nova import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


HOST = "testhost"
FAKEUUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


fake_inst = fake_instance.fake_db_instance


networks = [{'id': 0,
             'uuid': FAKEUUID,
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
             'dhcp_server': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': HOST,
             'project_id': fakes.FAKE_PROJECT_ID,
             'vpn_public_address': '192.168.0.2',
             'vpn_public_port': '22',
             'vpn_private_address': '10.0.0.2'},
            {'id': 1,
             'uuid': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
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
             'dhcp_server': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': HOST,
             'project_id': fakes.FAKE_PROJECT_ID,
             'vpn_public_address': '192.168.1.2',
             'vpn_public_port': '22',
             'vpn_private_address': '10.0.0.2'}]

fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_uuid': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []},
             {'id': 0,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_uuid': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []},
             {'id': 0,
              'network_id': 1,
              'address': '2001:db9:0:1::10',
              'instance_uuid': 0,
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
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'uuid': uuids.vif1_uuid,
         'network_id': 0,
         'instance_uuid': uuids.instance,
         'tag': 'fake-tag1'},
        {'id': 1,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'instance_uuid': uuids.instance,
         'tag': 'fake-tag2'},
        {'id': 2,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 2,
         'instance_uuid': uuids.instance,
         'tag': 'fake-tag3'}]


class FlatNetworkTestCase(test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(FlatNetworkTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.network = network_manager.FlatManager(host=HOST)
        self.network.instance_dns_domain = ''
        self.network.db = db
        self.context = context.RequestContext('testuser',
                                              fakes.FAKE_PROJECT_ID,
                                              is_admin=False)

    @testtools.skipIf(test_utils.is_osx(),
                      'IPv6 pretty-printing broken on OSX, see bug 1409135')
    def test_get_instance_nw_info_fake(self):
        fake_get_instance_nw_info = fake_network.fake_get_instance_nw_info

        nw_info = fake_get_instance_nw_info(self, 0, 2)
        self.assertFalse(nw_info)

        nw_info = fake_get_instance_nw_info(self, 1, 2)

        for i, vif in enumerate(nw_info):
            nid = i + 1
            check = {'bridge': 'fake_br%d' % nid,
                     'cidr': '192.168.%s.0/24' % nid,
                     'cidr_v6': '2001:db8:0:%x::/64' % nid,
                     'id': getattr(uuids, 'vif%i' % nid),
                     'multi_host': False,
                     'injected': False,
                     'bridge_interface': None,
                     'vlan': None,
                     'broadcast': '192.168.%d.255' % nid,
                     'dhcp_server': '192.168.1.1',
                     'dns': ['192.168.%d.3' % nid, '192.168.%d.4' % nid],
                     'gateway': '192.168.%d.1' % nid,
                     'gateway_v6': '2001:db8:0:1::1',
                     'label': 'test%d' % nid,
                     'mac': 'DE:AD:BE:EF:00:%02x' % nid,
                     'rxtx_cap': 30,
                     'vif_type': net_model.VIF_TYPE_BRIDGE,
                     'vif_devname': None,
                     'vif_uuid': getattr(uuids, 'vif%i' % nid),
                     'ovs_interfaceid': None,
                     'qbh_params': None,
                     'qbg_params': None,
                     'should_create_vlan': False,
                     'should_create_bridge': False,
                     'ip': '192.168.%d.%03d' % (nid, nid + 99),
                     'ip_v6': '2001:db8:0:1:dcad:beff:feef:%x' % nid,
                     'netmask': '255.255.255.0',
                     'netmask_v6': 64,
                     'physical_network': None,
                      }

            network = vif['network']
            net_v4 = vif['network']['subnets'][0]
            net_v6 = vif['network']['subnets'][1]

            vif_dict = dict(bridge=network['bridge'],
                            cidr=net_v4['cidr'],
                            cidr_v6=net_v6['cidr'],
                            id=vif['id'],
                            multi_host=network.get_meta('multi_host', False),
                            injected=network.get_meta('injected', False),
                            bridge_interface=
                                network.get_meta('bridge_interface'),
                            vlan=network.get_meta('vlan'),
                            broadcast=str(net_v4.as_netaddr().broadcast),
                            dhcp_server=network.get_meta('dhcp_server',
                                net_v4['gateway']['address']),
                            dns=[ip['address'] for ip in net_v4['dns']],
                            gateway=net_v4['gateway']['address'],
                            gateway_v6=net_v6['gateway']['address'],
                            label=network['label'],
                            mac=vif['address'],
                            rxtx_cap=vif.get_meta('rxtx_cap'),
                            vif_type=vif['type'],
                            vif_devname=vif.get('devname'),
                            vif_uuid=vif['id'],
                            ovs_interfaceid=vif.get('ovs_interfaceid'),
                            qbh_params=vif.get('qbh_params'),
                            qbg_params=vif.get('qbg_params'),
                            should_create_vlan=
                                network.get_meta('should_create_vlan', False),
                            should_create_bridge=
                                network.get_meta('should_create_bridge',
                                                  False),
                            ip=net_v4['ips'][i]['address'],
                            ip_v6=net_v6['ips'][i]['address'],
                            netmask=str(net_v4.as_netaddr().netmask),
                            netmask_v6=net_v6.as_netaddr()._prefixlen,
                            physical_network=
                                network.get_meta('physical_network', None))

            self.assertThat(vif_dict, matchers.DictMatches(check))

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_address')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100')]

        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[1])
        ip['network'] = dict(test_network.fake_network,
                             **networks[1])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)
        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[0])
        ip['network'] = dict(test_network.fake_network,
                             **networks[0])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_valid_fixed_ipv6(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_address')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '2001:db9:0:1::10')]

        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[2])
        ip['network'] = dict(test_network.fake_network,
                             **networks[1])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_reserved(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        nets = self.network.create_networks(context_admin, 'fake',
                                       '192.168.0.0/24', False, 1,
                                       256, None, None, None, None, None)
        self.assertEqual(1, len(nets))
        network = nets[0]
        self.assertEqual(4, db.network_count_reserved_ips(context_admin,
                        network['id']))

    def test_validate_reserved_start_end(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        nets = self.network.create_networks(context_admin, 'fake',
                                       '192.168.0.0/24', False, 1,
                                       256, dhcp_server='192.168.0.11',
                                       allowed_start='192.168.0.10',
                                       allowed_end='192.168.0.245')
        self.assertEqual(1, len(nets))
        network = nets[0]
        # gateway defaults to beginning of allowed_start
        self.assertEqual('192.168.0.10', network['gateway'])
        # vpn_server doesn't conflict with dhcp_start
        self.assertEqual('192.168.0.12', network['vpn_private_address'])
        # dhcp_start doesn't conflict with dhcp_server
        self.assertEqual('192.168.0.13', network['dhcp_start'])
        # NOTE(vish): 10 from the beginning, 10 from the end, and
        #             1 for the gateway, 1 for the dhcp server,
        #             1 for the vpn server
        self.assertEqual(23, db.network_count_reserved_ips(context_admin,
                        network['id']))

    def test_validate_reserved_start_out_of_range(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        self.assertRaises(exception.AddressOutOfRange,
                          self.network.create_networks,
                          context_admin, 'fake', '192.168.0.0/24', False,
                          1, 256, allowed_start='192.168.1.10')

    def test_validate_reserved_end_invalid(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        self.assertRaises(exception.InvalidAddress,
                          self.network.create_networks,
                          context_admin, 'fake', '192.168.0.0/24', False,
                          1, 256, allowed_end='invalid')

    def test_validate_cidr_invalid(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        self.assertRaises(exception.InvalidCidr,
                          self.network.create_networks,
                          context_admin, 'fake', 'invalid', False,
                          1, 256)

    def test_validate_non_int_size(self):
        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)
        self.assertRaises(exception.InvalidIntValue,
                          self.network.create_networks,
                          context_admin, 'fake', '192.168.0.0/24', False,
                          1, 'invalid')

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100.1'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100.1')]
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, self.context,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               ''),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '')]
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          self.context, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               None),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               None)]
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    @mock.patch('nova.objects.fixed_ip.FixedIPList.get_by_instance_uuid')
    def test_get_instance_nw_info(self, get):

        def make_ip(index):
            vif = objects.VirtualInterface(uuid=uuids.vif1_uuid, address=index)
            network = objects.Network(uuid=uuids.network_1,
                                      bridge=index,
                                      label=index,
                                      project_id=fakes.FAKE_PROJECT_ID,
                                      injected=False,
                                      netmask='255.255.255.0',
                                      dns1=None,
                                      dns2=None,
                                      cidr_v6=None,
                                      gateway_v6=None,
                                      broadcast_v6=None,
                                      netmask_v6=None,
                                      rxtx_base=None,
                                      gateway='192.168.%s.1' % index,
                                      dhcp_server='192.168.%s.1' % index,
                                      broadcast='192.168.%s.255' % index,
                                      cidr='192.168.%s.0/24' % index)
            return objects.FixedIP(virtual_interface=vif,
                                   network=network,
                                   floating_ips=objects.FloatingIPList(),
                                   address='192.168.%s.2' % index)
        objs = [make_ip(index) for index in ('3', '1', '2')]
        get.return_value = objects.FixedIPList(objects=objs)
        nw_info = self.network.get_instance_nw_info(self.context, None,
                                                    None, None)
        for i, vif in enumerate(nw_info):
            self.assertEqual(objs[i].network.bridge, vif['network']['bridge'])

    @mock.patch.object(objects.Network, 'get_by_id')
    def test_add_fixed_ip_instance_using_id_without_vpn(self, get_by_id):
        # Allocate a fixed ip from a network and assign it to an instance.
        # Network is given by network id.

        network_id = networks[0]['id']

        with mock.patch.object(self.network,
                               'allocate_fixed_ip') as allocate_fixed_ip:
            self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                                  network_id)

        # Assert that we fetched the network by id, not uuid
        get_by_id.assert_called_once_with(self.context,
                network_id, project_only='allow_none')

        # Assert that we called allocate_fixed_ip for the given network and
        # instance. We should not have requested a specific address from the
        # network.
        allocate_fixed_ip.assert_called_once_with(self.context, FAKEUUID,
                                                  get_by_id.return_value,
                                                  address=None)

    @mock.patch.object(objects.Network, 'get_by_uuid')
    def test_add_fixed_ip_instance_using_uuid_without_vpn(self, get_by_uuid):
        # Allocate a fixed ip from a network and assign it to an instance.
        # Network is given by network uuid.

        network_uuid = networks[0]['uuid']

        with mock.patch.object(self.network,
                               'allocate_fixed_ip') as allocate_fixed_ip,\
             mock.patch.object(self.context, 'elevated',
                               return_value=mock.sentinel.elevated):
            self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                                  network_uuid)

        # Assert that we fetched the network by uuid, not id, and with elevated
        # context
        get_by_uuid.assert_called_once_with(mock.sentinel.elevated,
                                            network_uuid)

        # Assert that we called allocate_fixed_ip for the given network and
        # instance. We should not have requested a specific address from the
        # network.
        allocate_fixed_ip.assert_called_once_with(self.context,
                                                  FAKEUUID,
                                                  get_by_uuid.return_value,
                                                  address=None)

    def test_mini_dns_driver(self):
        zone1 = "example.org"
        zone2 = "example.com"
        driver = self.network.instance_dns_manager
        driver.create_entry("hostone", "10.0.0.1", "A", zone1)
        driver.create_entry("hosttwo", "10.0.0.2", "A", zone1)
        driver.create_entry("hostthree", "10.0.0.3", "A", zone1)
        driver.create_entry("hostfour", "10.0.0.4", "A", zone1)
        driver.create_entry("hostfive", "10.0.0.5", "A", zone2)

        driver.delete_entry("hostone", zone1)
        driver.modify_address("hostfour", "10.0.0.1", zone1)
        driver.modify_address("hostthree", "10.0.0.1", zone1)
        names = driver.get_entries_by_address("10.0.0.1", zone1)
        self.assertEqual(2, len(names))
        self.assertIn('hostthree', names)
        self.assertIn('hostfour', names)

        names = driver.get_entries_by_address("10.0.0.5", zone2)
        self.assertEqual(1, len(names))
        self.assertIn('hostfive', names)

        addresses = driver.get_entries_by_name("hosttwo", zone1)
        self.assertEqual(1, len(addresses))
        self.assertIn('10.0.0.2', addresses)

        self.assertRaises(exception.InvalidInput,
                driver.create_entry,
                "hostname",
                "10.10.10.10",
                "invalidtype",
                zone1)

    def test_mini_dns_driver_with_mixed_case(self):
        zone1 = "example.org"
        driver = self.network.instance_dns_manager
        driver.create_entry("HostTen", "10.0.0.10", "A", zone1)
        addresses = driver.get_entries_by_address("10.0.0.10", zone1)
        self.assertEqual(1, len(addresses))
        for n in addresses:
            driver.delete_entry(n, zone1)
        addresses = driver.get_entries_by_address("10.0.0.10", zone1)
        self.assertEqual(0, len(addresses))

    def test_allocate_fixed_ip_instance_dns(self):
        # Test DNS entries are created when allocating a fixed IP.
        # Allocate a fixed IP to an instance. Ensure that dns entries have been
        # created for the instance's name and uuid.

        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(), test_network.fake_network)
        network.save = mock.MagicMock()

        # Create a minimal instance object
        instance_params = {
            'display_name': HOST,
            'security_groups': []
        }
        instance = fake_instance.fake_instance_obj(
             context.RequestContext('ignore', 'ignore'),
             expected_attrs=instance_params.keys(), **instance_params)
        instance.save = mock.MagicMock()

        # We don't specify a specific address, so we should get a FixedIP
        # automatically allocated from the pool. Fix its value here.
        fip = objects.FixedIP(address='192.168.0.101')
        fip.save = mock.MagicMock()

        with mock.patch.object(objects.Instance, 'get_by_uuid',
                               return_value=instance),\
             mock.patch.object(objects.FixedIP, 'associate_pool',
                               return_value=fip):
            self.network.allocate_fixed_ip(self.context, FAKEUUID, network)

        instance_manager = self.network.instance_dns_manager
        expected_addresses = ['192.168.0.101']

        # Assert that we have a correct entry by instance display name
        addresses = instance_manager.get_entries_by_name(HOST,
                                             self.network.instance_dns_domain)
        self.assertEqual(expected_addresses, addresses)

        # Assert that we have a correct entry by instance uuid
        addresses = instance_manager.get_entries_by_name(FAKEUUID,
                                              self.network.instance_dns_domain)
        self.assertEqual(expected_addresses, addresses)

    def test_allocate_floating_ip(self):
        self.assertIsNone(self.network.allocate_floating_ip(self.context,
                                                            1, None))

    def test_deallocate_floating_ip(self):
        self.assertIsNone(self.network.deallocate_floating_ip(self.context,
                                                              1, None))

    def test_associate_floating_ip(self):
        self.assertIsNone(self.network.associate_floating_ip(self.context,
                                                             None, None))

    def test_disassociate_floating_ip(self):
        self.assertIsNone(self.network.disassociate_floating_ip(self.context,
                                                                None, None))

    def test_get_networks_by_uuids_ordering(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = ['bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        self.mox.ReplayAll()
        res = self.network._get_networks_by_uuids(self.context,
                                                  requested_networks)

        self.assertEqual(1, res[0]['id'])
        self.assertEqual(0, res[1]['id'])

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_allocate_calculates_quota_auth(self, util_method, check,
                                            get_by_uuid):
        inst = objects.Instance()
        inst['uuid'] = uuids.instance
        get_by_uuid.return_value = inst
        check.side_effect = exception.OverQuota(overs='testing',
                                                quotas={'fixed_ips': 10},
                                                usages={'fixed_ips': 10})
        util_method.return_value = ('foo', 'bar')
        self.assertRaises(exception.FixedIpLimitExceeded,
                          self.network.allocate_fixed_ip,
                          self.context, 123, {'uuid': uuids.instance})
        util_method.assert_called_once_with(self.context, inst)

    @mock.patch('nova.objects.fixed_ip.FixedIP.disassociate')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate_pool')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_allocate_over_quota_during_recheck(self, util_method, check,
                                                get_by_uuid, associate,
                                                disassociate):
        inst = objects.Instance()
        inst['uuid'] = uuids.instance
        get_by_uuid.return_value = inst

        # Simulate a race where the first check passes and the recheck fails.
        check.side_effect = [None, exception.OverQuota(
                                overs='fixed_ips', quotas={'fixed_ips': 10},
                                usages={'fixed_ips': 10})]

        util_method.return_value = ('foo', 'bar')
        address = netaddr.IPAddress('1.2.3.4')
        fip = objects.FixedIP(instance_uuid=inst.uuid,
                              address=address,
                              virtual_interface_id=1)
        associate.return_value = fip

        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(), test_network.fake_network)
        network.save = mock.MagicMock()
        self.assertRaises(exception.FixedIpLimitExceeded,
                          self.network.allocate_fixed_ip,
                          self.context, inst.uuid, network)

        self.assertEqual(2, check.call_count)
        call1 = mock.call(self.context, {'fixed_ips': 1}, 'foo')
        call2 = mock.call(self.context, {'fixed_ips': 0}, 'foo')
        check.assert_has_calls([call1, call2])

        # Verify we removed the fixed IP that was added after the first quota
        # check passed.
        disassociate.assert_called_once_with(self.context)

    @mock.patch('nova.objects.fixed_ip.FixedIP.associate_pool')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_allocate_no_quota_recheck(self, util_method, check, get_by_uuid,
                                       associate):
        # Disable recheck_quota.
        self.flags(recheck_quota=False, group='quota')

        inst = objects.Instance()
        inst['uuid'] = uuids.instance
        inst['display_name'] = 'test'
        get_by_uuid.return_value = inst

        util_method.return_value = ('foo', 'bar')
        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(), test_network.fake_network)
        network.save = mock.MagicMock()

        @mock.patch.object(self.network, '_setup_network_on_host')
        @mock.patch.object(self.network, 'instance_dns_manager')
        @mock.patch.object(self.network,
            '_do_trigger_security_group_members_refresh_for_instance')
        def _test(trigger, dns, setup):
            self.network.allocate_fixed_ip(self.context, inst.uuid, network)

        _test()

        # check_deltas should have been called only once.
        check.assert_called_once_with(self.context, {'fixed_ips': 1}, 'foo')

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate')
    def test_allocate_fixed_ip_passes_string_address(self, mock_associate,
                                                     mock_get):
        mock_associate.side_effect = test.TestingException
        instance = objects.Instance(context=self.context)
        instance.create()
        mock_get.return_value = instance
        self.assertRaises(test.TestingException,
                          self.network.allocate_fixed_ip,
                          self.context, instance.uuid,
                          {'cidr': '24', 'id': 1, 'uuid': uuids.instance},
                          address=netaddr.IPAddress('1.2.3.4'))
        mock_associate.assert_called_once_with(self.context,
                                               '1.2.3.4',
                                               instance.uuid,
                                               1,
                                               vif_id=1)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.virtual_interface.VirtualInterface'
                '.get_by_instance_and_network')
    @mock.patch('nova.objects.fixed_ip.FixedIP.disassociate')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate')
    @mock.patch('nova.objects.fixed_ip.FixedIP.save')
    def test_allocate_fixed_ip_cleanup(self,
                                       mock_fixedip_save,
                                       mock_fixedip_associate,
                                       mock_fixedip_disassociate,
                                       mock_vif_get,
                                       mock_instance_get):
        address = netaddr.IPAddress('1.2.3.4')

        fip = objects.FixedIP(instance_uuid=uuids.instance,
                              address=address,
                              virtual_interface_id=1)
        mock_fixedip_associate.return_value = fip

        instance = objects.Instance(context=self.context)
        instance.create()
        mock_instance_get.return_value = instance

        mock_vif_get.return_value = vif_obj.VirtualInterface(
            instance_uuid=uuids.instance, id=1)

        with test.nested(
            mock.patch.object(self.network, '_setup_network_on_host'),
            mock.patch.object(self.network, 'instance_dns_manager'),
            mock.patch.object(self.network,
                '_do_trigger_security_group_members_refresh_for_instance')
        ) as (mock_setup_network, mock_dns_manager, mock_ignored):
            mock_setup_network.side_effect = test.TestingException
            self.assertRaises(test.TestingException,
                              self.network.allocate_fixed_ip,
                              self.context, instance.uuid,
                              {'cidr': '24', 'id': 1,
                               'uuid': uuids.instance},
                              address=address)

            mock_dns_manager.delete_entry.assert_has_calls([
                mock.call(instance.display_name, ''),
                mock.call(instance.uuid, '')
            ])

        mock_fixedip_disassociate.assert_called_once_with(self.context)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.virtual_interface.VirtualInterface'
                '.get_by_instance_and_network')
    @mock.patch('nova.objects.fixed_ip.FixedIP.disassociate')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate_pool')
    @mock.patch('nova.network.manager.NetworkManager._add_virtual_interface')
    def test_allocate_fixed_ip_create_new_vifs(self,
                                               mock_add,
                                               mock_fixedip_associate,
                                               mock_fixedip_disassociate,
                                               mock_vif_get,
                                               mock_instance_get):
        address = netaddr.IPAddress('1.2.3.4')

        fip = objects.FixedIP(instance_uuid=uuids.instance,
                              address=address,
                              virtual_interface_id=1000)
        net = {'cidr': '24', 'id': 1, 'uuid': uuids.instance}
        instance = objects.Instance(context=self.context)
        instance.create()

        vif = objects.VirtualInterface(context,
                                       id=1000,
                                       address='00:00:00:00:00:00',
                                       instance_uuid=instance.uuid,
                                       network_id=net['id'],
                                       uuid=uuids.instance)
        mock_fixedip_associate.return_value = fip
        mock_add.return_value = vif
        mock_instance_get.return_value = instance
        mock_vif_get.return_value = None

        with test.nested(
            mock.patch.object(self.network, '_setup_network_on_host'),
            mock.patch.object(self.network, 'instance_dns_manager'),
            mock.patch.object(self.network,
                '_do_trigger_security_group_members_refresh_for_instance')
        ) as (mock_setup_network, mock_dns_manager, mock_ignored):
            self.network.allocate_fixed_ip(self.context, instance['uuid'],
                net)
            mock_add.assert_called_once_with(self.context, instance['uuid'],
                net['id'])
            self.assertEqual(fip.virtual_interface_id, vif.id)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch.object(db, 'virtual_interface_get_by_instance_and_network',
                       return_value=None)
    @mock.patch('nova.objects.fixed_ip.FixedIP')
    def test_allocate_fixed_ip_add_vif_fails(self, mock_fixedip,
                                             mock_get_vif, mock_instance_get):
        # Tests that we don't try to do anything with fixed IPs if
        # _add_virtual_interface fails.
        instance = fake_instance.fake_instance_obj(self.context)
        mock_instance_get.return_value = instance
        network = {'cidr': '24', 'id': 1,
                   'uuid': '398399b3-f696-4859-8695-a6560e14cb02'}
        vif_error = exception.VirtualInterfaceMacAddressException()
        # mock out quotas because we don't care in this test
        with mock.patch.object(self.network, 'quotas_cls', objects.QuotasNoOp):
            with mock.patch.object(self.network, '_add_virtual_interface',
                                   side_effect=vif_error):
                self.assertRaises(
                    exception.VirtualInterfaceMacAddressException,
                    self.network.allocate_fixed_ip, self.context,
                    '9d2ee1e3-ffad-4e5f-81ff-c96dd97b0ee0', network)
        self.assertFalse(mock_fixedip.called, str(mock_fixedip.mock_calls))


class FlatDHCPNetworkTestCase(test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(FlatDHCPNetworkTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.network = network_manager.FlatDHCPManager(host=HOST)
        self.network.db = db
        self.context = context.RequestContext('testuser',
                                              fakes.FAKE_PROJECT_ID,
                                              is_admin=False)
        self.context_admin = context.RequestContext('testuser',
                                                    fakes.FAKE_PROJECT_ID,
                                                    is_admin=True)

    @mock.patch('nova.objects.fixed_ip.FixedIP.get_by_id')
    @mock.patch('nova.objects.floating_ip.FloatingIPList.get_by_host')
    @mock.patch('nova.network.linux_net.iptables_manager._apply')
    def test_init_host_iptables_defer_apply(self, iptable_apply,
                                            floating_get_by_host,
                                            fixed_get_by_id):
        def get_by_id(context, fixed_ip_id, **kwargs):
            net = objects.Network(bridge='testbridge',
                                      cidr='192.168.1.0/24')
            if fixed_ip_id == 1:
                return objects.FixedIP(address='192.168.1.4',
                                            network=net)
            elif fixed_ip_id == 2:
                return objects.FixedIP(address='192.168.1.5',
                                            network=net)

        def fake_apply():
            fake_apply.count += 1

        fake_apply.count = 0
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=True)
        float1 = objects.FloatingIP(address='1.2.3.4', fixed_ip_id=1)
        float2 = objects.FloatingIP(address='1.2.3.5', fixed_ip_id=2)
        float1._context = ctxt
        float2._context = ctxt

        iptable_apply.side_effect = fake_apply
        floating_get_by_host.return_value = [float1, float2]
        fixed_get_by_id.side_effect = get_by_id

        self.network.init_host()
        self.assertEqual(1, fake_apply.count)


class VlanNetworkTestCase(test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(VlanNetworkTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db
        self.context = context.RequestContext('testuser',
                                              fakes.FAKE_PROJECT_ID,
                                              is_admin=False)
        self.context_admin = context.RequestContext('testuser',
                                                    fakes.FAKE_PROJECT_ID,
                                                    is_admin=True)

    def test_quota_driver_type(self):
        self.assertEqual(objects.QuotasNoOp,
                         self.network.quotas_cls)

    def test_vpn_allocate_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_associate')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.1')
        db.fixed_ip_associate(mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              network_id=mox.IgnoreArg(),
                              reserved=True,
                              virtual_interface_id=vifs[0]['id']
                              ).AndReturn(fixed)
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.mox.ReplayAll()

        network = objects.Network._from_db_object(
            self.context, objects.Network(),
            dict(test_network.fake_network, **networks[0]))
        network.vpn_private_address = '192.168.0.2'
        self.network.allocate_fixed_ip(self.context, FAKEUUID, network,
                                       vpn=True)

    def test_allocate_fixed_ip(self):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.1')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None,
                                   virtual_interface_id=vifs[0]['id']
                                   ).AndReturn(fixed)
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.mox.ReplayAll()

        network = objects.Network._from_db_object(
            self.context, objects.Network(),
            dict(test_network.fake_network, **networks[0]))
        network.vpn_private_address = '192.168.0.2'
        self.network.allocate_fixed_ip(self.context, FAKEUUID, network)

    @mock.patch('nova.objects.fixed_ip.FixedIP.associate_pool')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.QuotasNoOp.check_deltas')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_allocate_fixed_ip_super_call(self, mock_ids, mock_check, mock_get,
                                          mock_associate):
        # No code in the VlanManager actually calls
        # NetworkManager.allocate_fixed_ip() at this time. This is just to
        # test that if it did, it would call through the QuotasNoOp class.
        inst = objects.Instance()
        inst['uuid'] = uuids.instance
        inst['display_name'] = 'test'
        mock_get.return_value = inst

        mock_ids.return_value = ('foo', 'bar')

        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(), test_network.fake_network)
        network.save = mock.MagicMock()

        @mock.patch.object(self.network, '_setup_network_on_host')
        @mock.patch.object(self.network, 'instance_dns_manager')
        @mock.patch.object(self.network,
            '_do_trigger_security_group_members_refresh_for_instance')
        def _test(trigger, dns, setup):
            super(network_manager.VlanManager, self.network).allocate_fixed_ip(
                self.context, FAKEUUID, network)

        _test()

        # Make sure we called the QuotasNoOp.check_deltas() for VlanManager.
        self.assertEqual(2, mock_check.call_count)

    @mock.patch('nova.network.manager.VlanManager._setup_network_on_host')
    @mock.patch('nova.network.manager.VlanManager.'
                '_validate_instance_zone_for_dns_domain')
    @mock.patch('nova.network.manager.VlanManager.'
                '_do_trigger_security_group_members_refresh_for_instance')
    @mock.patch('nova.network.manager.VlanManager._add_virtual_interface')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate')
    @mock.patch('nova.objects.VirtualInterface.get_by_instance_and_network')
    def test_allocate_fixed_ip_return_none(self, mock_get,
            mock_associate, mock_get_uuid, mock_add, mock_trigger,
            mock_validate, mock_setup):
        net = {'cidr': '24', 'id': 1, 'uuid': uuids.instance}
        fip = objects.FixedIP(instance_uuid=uuids.instance,
                              address=netaddr.IPAddress('1.2.3.4'),
                              virtual_interface_id=1)

        instance = objects.Instance(context=self.context)
        instance.create()

        vif = objects.VirtualInterface(self.context,
                                       id=1000,
                                       address='00:00:00:00:00:00',
                                       instance_uuid=instance.uuid,
                                       network_id=net['id'],
                                       uuid=uuids.instance)
        mock_associate.return_value = fip
        mock_add.return_value = vif
        mock_get.return_value = None
        mock_get_uuid.return_value = instance
        mock_validate.return_value = False

        self.network.allocate_fixed_ip(self.context_admin, instance.uuid, net)

        mock_add.assert_called_once_with(self.context_admin, instance.uuid,
                                         net['id'])

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate')
    def test_allocate_fixed_ip_passes_string_address(self, mock_associate,
                                                     mock_get):
        mock_associate.side_effect = test.TestingException
        instance = objects.Instance(context=self.context)
        instance.create()
        mock_get.return_value = instance
        self.assertRaises(test.TestingException,
                          self.network.allocate_fixed_ip,
                          self.context, instance.uuid,
                          {'cidr': '24', 'id': 1, 'uuid': uuids.instance},
                          address=netaddr.IPAddress('1.2.3.4'))
        mock_associate.assert_called_once_with(self.context,
                                               '1.2.3.4',
                                               instance.uuid,
                                               1,
                                               vif_id=1)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.fixed_ip.FixedIP.associate')
    def test_allocate_fixed_ip_passes_string_address_vpn(self, mock_associate,
                                                         mock_get):
        mock_associate.side_effect = test.TestingException
        instance = objects.Instance(context=self.context)
        instance.create()
        mock_get.return_value = instance
        self.assertRaises(test.TestingException,
                          self.network.allocate_fixed_ip,
                          self.context, instance.uuid,
                          {'cidr': '24', 'id': 1, 'uuid': uuids.instance,
                           'vpn_private_address': netaddr.IPAddress('1.2.3.4')
                           }, vpn=1)
        mock_associate.assert_called_once_with(self.context,
                                               '1.2.3.4',
                                               instance.uuid,
                                               1, reserved=True,
                                               vif_id=1)

    @mock.patch.object(db, 'virtual_interface_get_by_instance_and_network',
                       return_value=None)
    @mock.patch('nova.objects.fixed_ip.FixedIP')
    def test_allocate_fixed_ip_add_vif_fails(self, mock_fixedip,
                                             mock_get_vif):
        # Tests that we don't try to do anything with fixed IPs if
        # _add_virtual_interface fails.
        vif_error = exception.VirtualInterfaceMacAddressException()
        with mock.patch.object(self.network, '_add_virtual_interface',
                               side_effect=vif_error):
            self.assertRaises(exception.VirtualInterfaceMacAddressException,
                              self.network.allocate_fixed_ip, self.context,
                              '9d2ee1e3-ffad-4e5f-81ff-c96dd97b0ee0',
                              networks[0])
        self.assertFalse(mock_fixedip.called, str(mock_fixedip.mock_calls))

    def test_create_networks_too_big(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=4094, vlan_start=1)

    def test_create_networks_too_many(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=100, vlan_start=1,
                          cidr='192.168.0.1/24', network_size=100)

    def test_duplicate_vlan_raises(self):
        # VLAN 100 is already used and we force the network to be created
        # in that vlan (vlan=100).
        self.assertRaises(exception.DuplicateVlan,
                          self.network.create_networks,
                          self.context_admin, label="fake", num_networks=1,
                          vlan=100, cidr='192.168.0.1/24', network_size=100)

    def test_vlan_start(self):
        # VLAN 100 and 101 are used, so this network shoud be created in 102
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=1,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(102, networks[0]["vlan"])

    def test_vlan_start_multiple(self):
        # VLAN 100 and 101 are used, so these networks shoud be created in 102
        # and 103
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=2,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(102, networks[0]["vlan"])
        self.assertEqual(103, networks[1]["vlan"])

    def test_vlan_start_used(self):
        # VLAN 100 and 101 are used, but vlan_start=99.
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=1,
                          vlan_start=99, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(102, networks[0]["vlan"])

    def test_vlan_parameter(self):
        # vlan parameter could not be greater than 4094
        exc = self.assertRaises(ValueError,
                                self.network.create_networks,
                                self.context_admin, label="fake",
                                num_networks=1,
                                vlan=4095, cidr='192.168.0.1/24')
        error_msg = 'The vlan number cannot be greater than 4094'
        self.assertIn(error_msg, six.text_type(exc))

        # vlan parameter could not be less than 1
        exc = self.assertRaises(ValueError,
                                self.network.create_networks,
                                self.context_admin, label="fake",
                                num_networks=1,
                                vlan=0, cidr='192.168.0.1/24')
        error_msg = 'The vlan number cannot be less than 1'
        self.assertIn(error_msg, six.text_type(exc))

    def test_vlan_be_integer(self):
        # vlan must be an integer
        exc = self.assertRaises(ValueError,
                                self.network.create_networks,
                                self.context_admin, label="fake",
                                num_networks=1,
                                vlan='fake', cidr='192.168.0.1/24')
        error_msg = 'vlan must be an integer'
        self.assertIn(error_msg, six.text_type(exc))

    def test_vlan_multiple_without_dhcp_server(self):
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=2,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual("192.168.3.1", networks[0]["dhcp_server"])
        self.assertEqual("192.168.3.129", networks[1]["dhcp_server"])

    def test_vlan_multiple_with_dhcp_server(self):
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=2,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100, dhcp_server='192.168.3.1')

        self.assertEqual("192.168.3.1", networks[0]["dhcp_server"])
        self.assertEqual("192.168.3.1", networks[1]["dhcp_server"])

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, "fixed_ip_get_by_address")

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100')]

        db_fixed1 = dict(test_fixed_ip.fake_fixed_ip,
                         network_id=networks[1]['id'],
                         network=dict(test_network.fake_network,
                                      **networks[1]),
                         instance_uuid=None)
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(db_fixed1)
        db_fixed2 = dict(test_fixed_ip.fake_fixed_ip,
                         network_id=networks[0]['id'],
                         network=dict(test_network.fake_network,
                                      **networks[0]),
                         instance_uuid=None)
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(db_fixed2)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100.1'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100.1')]
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, self.context,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', ''),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '')]
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          self.context, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', None),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', None)]
        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_floating_ip_owned_by_project(self):
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        # raises because floating_ip project_id is None
        floating_ip = objects.FloatingIP(address='10.0.0.1',
                                         project_id=None)
        self.assertRaises(exception.Forbidden,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # raises because floating_ip project_id is not equal to ctxt project_id
        floating_ip = objects.FloatingIP(address='10.0.0.1',
                                         project_id=uuids.non_existent_uuid)
        self.assertRaises(exception.Forbidden,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # does not raise (floating ip is owned by ctxt project)
        floating_ip = objects.FloatingIP(address='10.0.0.1',
                                         project_id=ctxt.project_id)
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

        ctxt = context.RequestContext(None, None,
                                      is_admin=True)

        # does not raise (ctxt is admin)
        floating_ip = objects.FloatingIP(address='10.0.0.1',
                                         project_id=None)
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

        # does not raise (ctxt is admin)
        floating_ip = objects.FloatingIP(address='10.0.0.1',
                                         project_id=fakes.FAKE_PROJECT_ID)
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

    def test_allocate_floating_ip(self):
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        self.stubs.Set(self.network, '_floating_ip_pool_exists',
                       lambda _x, _y: True)

        def fake_allocate_address(*args, **kwargs):
            return {'address': '10.0.0.1', 'project_id': ctxt.project_id}

        self.stubs.Set(self.network.db, 'floating_ip_allocate_address',
                       fake_allocate_address)

        self.network.allocate_floating_ip(ctxt, ctxt.project_id)

    @mock.patch('nova.objects.FloatingIP.deallocate')
    @mock.patch('nova.network.floating_ips.FloatingIP.'
                '_floating_ip_owned_by_project')
    @mock.patch('nova.objects.FloatingIP.get_by_address')
    def test_deallocate_floating_ip(self, mock_get, mock_owned, mock_dealloc):
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        def fake1(*args, **kwargs):
            params = dict(test_floating_ip.fake_floating_ip)
            return objects.FloatingIP(**params)

        def fake2(*args, **kwargs):
            params = dict(test_floating_ip.fake_floating_ip,
                          address='10.0.0.1', fixed_ip_id=1)
            return objects.FloatingIP(**params)

        def fake3(*args, **kwargs):
            params = dict(test_floating_ip.fake_floating_ip,
                          address='10.0.0.1', fixed_ip_id=None,
                          project_id=ctxt.project_id)
            return objects.FloatingIP(**params)

        mock_dealloc.side_effect = fake1
        mock_owned.side_effect = fake1
        mock_get.side_effect = fake2

        # this time should raise because floating ip is associated to
        # fixed_ip
        self.assertRaises(exception.FloatingIpAssociated,
                          self.network.deallocate_floating_ip,
                          ctxt,
                          'fake-address')
        mock_dealloc.assert_not_called()

        # this time should not raise
        mock_dealloc.reset_mock()
        mock_get.side_effect = fake3

        self.network.deallocate_floating_ip(ctxt, 'fake-address')
        mock_dealloc.assert_called_once_with(ctxt, 'fake-address')

    @mock.patch('nova.db.fixed_ip_get')
    def test_associate_floating_ip(self, fixed_get):
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        def fake1(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        network=test_network.fake_network)

        # floating ip that's already associated
        def fake2(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1)

        # floating ip that isn't associated
        def fake3(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=None)

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=123)

        def fake4_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='jibberjabber')

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=1234)

        def fake5_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='testhost')

        def fake6(ctxt, method, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        def fake8(*args, **kwargs):
            raise processutils.ProcessExecutionError('',
                    'Cannot find device "em0"\n')

        def fake9(*args, **kwargs):
            raise test.TestingException()

        # raises because interface doesn't exist
        self.stubs.Set(self.network.db,
                       'floating_ip_fixed_ip_associate',
                       fake1)
        self.stubs.Set(self.network.db, 'floating_ip_disassociate', fake1)
        self.stubs.Set(self.network.driver, 'ensure_floating_forward', fake8)
        self.assertRaises(exception.NoFloatingIpInterface,
                          self.network._associate_floating_ip,
                          ctxt,
                          '1.2.3.4',
                          '1.2.3.5',
                          mox.IgnoreArg(),
                          mox.IgnoreArg())

        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # raises because floating_ip is already associated to a fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.stubs.Set(self.network, 'disassociate_floating_ip', fake9)

        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address='1.2.3.4',
                                      instance_uuid=uuids.instance,
                                      network=test_network.fake_network)

        # doesn't raise because we exit early if the address is the same
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(), '1.2.3.4')

        # raises because we call disassociate which is mocked
        self.assertRaises(test.TestingException,
                          self.network.associate_floating_ip,
                          ctxt,
                          mox.IgnoreArg(),
                          'new')

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)

        # does not raise and makes call remotely
        self.local = True
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake4)
        self.stubs.Set(self.network.db, 'network_get', fake4_network)
        self.stubs.Set(self.network.network_rpcapi.client, 'prepare',
                       lambda **kw: self.network.network_rpcapi.client)
        self.stubs.Set(self.network.network_rpcapi.client, 'call', fake6)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake5)
        self.stubs.Set(self.network.db, 'network_get', fake5_network)
        self.stubs.Set(self.network, '_associate_floating_ip', fake7)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertTrue(self.local)

    def test_add_floating_ip_nat_before_bind(self):
        # Tried to verify order with documented mox record/verify
        # functionality, but it doesn't seem to work since I can't make it
        # fail.  I'm using stubs and a flag for now, but if this mox feature
        # can be made to work, it would be a better way to test this.
        #
        # self.mox.StubOutWithMock(self.network.driver,
        #                          'ensure_floating_forward')
        # self.mox.StubOutWithMock(self.network.driver, 'bind_floating_ip')
        #
        # self.network.driver.ensure_floating_forward(mox.IgnoreArg(),
        #                                             mox.IgnoreArg(),
        #                                             mox.IgnoreArg(),
        #                                             mox.IgnoreArg())
        # self.network.driver.bind_floating_ip(mox.IgnoreArg(),
        #                                      mox.IgnoreArg())
        # self.mox.ReplayAll()

        nat_called = [False]

        def fake_nat(*args, **kwargs):
            nat_called[0] = True

        def fake_bind(*args, **kwargs):
            self.assertTrue(nat_called[0])

        self.stubs.Set(self.network.driver,
                       'ensure_floating_forward',
                       fake_nat)
        self.stubs.Set(self.network.driver, 'bind_floating_ip', fake_bind)

        self.network.l3driver.add_floating_ip('fakefloat',
                                              'fakefixed',
                                              'fakeiface',
                                              'fakenet')

    @mock.patch('nova.db.floating_ip_get_all_by_host')
    @mock.patch('nova.db.fixed_ip_get')
    def _test_floating_ip_init_host(self, fixed_get, floating_get,
                                    public_interface, expected_arg):

        floating_get.return_value = [
            dict(test_floating_ip.fake_floating_ip,
                 interface='foo',
                 address='1.2.3.4'),
            dict(test_floating_ip.fake_floating_ip,
                 interface='fakeiface',
                 address='1.2.3.5',
                 fixed_ip_id=1),
            dict(test_floating_ip.fake_floating_ip,
                 interface='bar',
                 address='1.2.3.6',
                 fixed_ip_id=2),
            ]

        def fixed_ip_get(_context, fixed_ip_id, get_network):
            if fixed_ip_id == 1:
                return dict(test_fixed_ip.fake_fixed_ip,
                            address='1.2.3.4',
                            network=test_network.fake_network)
            raise exception.FixedIpNotFound(id=fixed_ip_id)
        fixed_get.side_effect = fixed_ip_get

        self.mox.StubOutWithMock(self.network.l3driver, 'add_floating_ip')
        self.flags(public_interface=public_interface)
        self.network.l3driver.add_floating_ip(netaddr.IPAddress('1.2.3.5'),
                                              netaddr.IPAddress('1.2.3.4'),
                                              expected_arg,
                                              mox.IsA(objects.Network))
        self.mox.ReplayAll()
        self.network.init_host_floating_ips()
        self.mox.UnsetStubs()
        self.mox.VerifyAll()

    def test_floating_ip_init_host_without_public_interface(self):
        self._test_floating_ip_init_host(public_interface='',
                                         expected_arg='fakeiface')

    def test_floating_ip_init_host_with_public_interface(self):
        self._test_floating_ip_init_host(public_interface='fooiface',
                                         expected_arg='fooiface')

    def test_disassociate_floating_ip(self):
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        # floating ip that isn't associated
        def fake2(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=None)

        # floating ip that is associated
        def fake3(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1,
                        project_id=ctxt.project_id)

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=123)

        def fake4_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False,
                        host='jibberjabber')

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=1234)

        def fake5_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='testhost')

        def fake6(ctxt, method, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        def fake8(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1,
                        auto_assigned=True,
                        project_id=ctxt.project_id)

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
        self.stubs.Set(self.network.db, 'network_get', fake4_network)
        self.stubs.Set(self.network.network_rpcapi.client, 'prepare',
                       lambda **kw: self.network.network_rpcapi.client)
        self.stubs.Set(self.network.network_rpcapi.client, 'call', fake6)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get', fake5)
        self.stubs.Set(self.network.db, 'network_get', fake5_network)
        self.stubs.Set(self.network, '_disassociate_floating_ip', fake7)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertTrue(self.local)

        # raises because auto_assigned floating IP cannot be disassociated
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake8)
        self.assertRaises(exception.CannotDisassociateAutoAssignedFloatingIP,
                          self.network.disassociate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

    def test_add_fixed_ip_instance_without_vpn_requested_networks(self):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'network_get')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.network, 'get_instance_nw_info')

        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.101')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None,
                                   virtual_interface_id=vifs[0]['id']
                                   ).AndReturn(fixed)
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg(),
                       project_only=mox.IgnoreArg()
                       ).AndReturn(dict(test_network.fake_network,
                                        **networks[0]))
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(),
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.network.get_instance_nw_info(mox.IgnoreArg(), mox.IgnoreArg(),
                                          mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                              networks[0]['id'])

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    def test_ip_association_and_allocation_of_other_project(self, net_get,
                                                            fixed_get):
        """Makes sure that we cannot deallocaate or disassociate
        a public IP of other project.
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)
        context2 = context.RequestContext('user', 'project2')

        float_ip = db.floating_ip_create(context1.elevated(),
                                         {'address': '1.2.3.4',
                                          'project_id': context1.project_id})

        float_addr = float_ip['address']

        instance = db.instance_create(context1,
                                      {'project_id': fakes.FAKE_PROJECT_ID})

        fix_addr = db.fixed_ip_associate_pool(context1.elevated(),
                                              1, instance['uuid']).address
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))

        # Associate the IP with non-admin user context
        self.assertRaises(exception.Forbidden,
                          self.network.associate_floating_ip,
                          context2,
                          float_addr,
                          fix_addr)

        # Deallocate address from other project
        self.assertRaises(exception.Forbidden,
                          self.network.deallocate_floating_ip,
                          context2,
                          float_addr)

        # Now Associates the address to the actual project
        self.network.associate_floating_ip(context1, float_addr, fix_addr)

        # Now try dis-associating from other project
        self.assertRaises(exception.Forbidden,
                          self.network.disassociate_floating_ip,
                          context2,
                          float_addr)

        # Clean up the ip addresses
        self.network.disassociate_floating_ip(context1, float_addr)
        self.network.deallocate_floating_ip(context1, float_addr)
        self.network.deallocate_fixed_ip(context1, fix_addr, 'fake')
        db.floating_ip_destroy(context1.elevated(), float_addr)
        db.fixed_ip_disassociate(context1.elevated(), fix_addr)

    @mock.patch('nova.network.rpcapi.NetworkAPI.release_dhcp')
    @mock.patch('nova.db.virtual_interface_get')
    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_deallocate_fixed(self, fixed_update, net_get, fixed_get,
                              vif_get, release_dhcp):
        """Verify that release is called properly.

        Ensures https://bugs.launchpad.net/nova/+bug/973442 doesn't return
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])
        vif_get.return_value = vifs[0]
        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)

        instance = db.instance_create(context1,
                {'project_id': fakes.FAKE_PROJECT_ID})

        elevated = context1.elevated()
        fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      instance_uuid=instance.uuid,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))

        self.flags(force_dhcp_release=True)
        self.network.deallocate_fixed_ip(context1, fix_addr.address, 'fake')
        fixed_update.assert_called_once_with(context1, fix_addr.address,
                                             {'allocated': False})
        release_dhcp.assert_called_once_with(context1, None,
                                             networks[1]['bridge'],
                                             fix_addr.address,
                                             'DE:AD:BE:EF:00:00')

    @mock.patch.object(linux_net, 'release_dhcp')
    @mock.patch('nova.network.rpcapi.NetworkAPI.release_dhcp')
    @mock.patch('nova.db.virtual_interface_get')
    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_deallocate_fixed_rpc_pinned(self, fixed_update, net_get,
                                         fixed_get, vif_get,
                                         release_dhcp,
                                         net_release_dhcp):
        """Ensure that if the RPC call to release_dhcp raises a
        RPCPinnedToOldVersion, we fall back to the previous behaviour of
        calling release_dhcp in the local linux_net driver. In the previous
        test, release_dhcp was mocked to call the driver, since this is what
        happens on a successful RPC call. In this test, we mock it to raise,
        but the expected behaviour is exactly the same - namely that
        release_dhcp is called in the linux_net driver, which is why the two
        tests are otherwise identical.
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])
        vif_get.return_value = vifs[0]
        release_dhcp.side_effect = exception.RPCPinnedToOldVersion()
        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)

        instance = db.instance_create(context1,
                {'project_id': fakes.FAKE_PROJECT_ID})

        elevated = context1.elevated()
        fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      instance_uuid=instance.uuid,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))

        self.flags(force_dhcp_release=True)
        self.network.deallocate_fixed_ip(context1, fix_addr.address, 'fake')
        net_release_dhcp.assert_called_once_with(networks[1]['bridge'],
                                                 fix_addr.address,
                                                 'DE:AD:BE:EF:00:00')
        fixed_update.assert_called_once_with(context1, fix_addr.address,
                                             {'allocated': False})

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def _deallocate_fixed_with_dhcp(self, mock_dev_exists, fixed_update,
                                    net_get, fixed_get):
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        def vif_get(_context, _vif_id):
            return vifs[0]

        def release_dhcp(self, context, instance, dev, address, vif_address):
            linux_net.release_dhcp(dev, address, vif_address)

        with test.nested(
            mock.patch.object(network_rpcapi.NetworkAPI, 'release_dhcp',
                              release_dhcp),
            mock.patch.object(db, 'virtual_interface_get', vif_get),
            mock.patch.object(
                utils, 'execute',
                side_effect=processutils.ProcessExecutionError()),
        ) as (release_dhcp, _vif_get, _execute):
            context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)

            instance = db.instance_create(context1,
                    {'project_id': fakes.FAKE_PROJECT_ID})

            elevated = context1.elevated()
            fix_addr = db.fixed_ip_associate_pool(elevated, 1,
                                                  instance['uuid'])
            fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                          address=fix_addr.address,
                                          instance_uuid=instance.uuid,
                                          allocated=True,
                                          virtual_interface_id=3,
                                          network=dict(
                                              test_network.fake_network,
                                              **networks[1]))
            self.flags(force_dhcp_release=True)
            self.network.deallocate_fixed_ip(context1, fix_addr.address,
                                             'fake')
            fixed_update.assert_called_once_with(context1, fix_addr.address,
                                                 {'allocated': False})
            mock_dev_exists.assert_called_once_with(networks[1]['bridge'])
            if mock_dev_exists.return_value:
                _execute.assert_called_once_with('dhcp_release',
                                                 networks[1]['bridge'],
                                                 fix_addr.address,
                                                 'DE:AD:BE:EF:00:00',
                                                 run_as_root=True)

    @mock.patch('nova.network.linux_net.device_exists', return_value=True)
    def test_deallocate_fixed_with_dhcp(self, mock_dev_exists):
        self._deallocate_fixed_with_dhcp(mock_dev_exists)

    @mock.patch('nova.network.linux_net.device_exists', return_value=False)
    def test_deallocate_fixed_without_dhcp(self, mock_dev_exists):
        self._deallocate_fixed_with_dhcp(mock_dev_exists)

    def test_deallocate_fixed_deleted(self):
        # Verify doesn't deallocate deleted fixed_ip from deleted network.

        def teardown_network_on_host(_context, network):
            if network['id'] == 0:
                raise test.TestingException()

        self.stubs.Set(self.network, '_teardown_network_on_host',
                       teardown_network_on_host)

        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)
        elevated = context1.elevated()

        instance = db.instance_create(context1,
                {'project_id': fakes.FAKE_PROJECT_ID})
        network = db.network_create_safe(elevated, networks[0])

        _fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fix_addr = _fix_addr.address
        db.fixed_ip_update(elevated, fix_addr, {'deleted': 1})
        elevated.read_deleted = 'yes'
        delfixed = db.fixed_ip_get_by_address(elevated, fix_addr)
        values = {'address': fix_addr,
                  'network_id': network.id,
                  'instance_uuid': delfixed['instance_uuid']}
        db.fixed_ip_create(elevated, values)
        elevated.read_deleted = 'no'
        elevated.read_deleted = 'yes'

        deallocate = self.network.deallocate_fixed_ip
        self.assertRaises(test.TestingException, deallocate, context1,
                          fix_addr, 'fake')

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_deallocate_fixed_no_vif(self, fixed_update, net_get, fixed_get):
        """Verify that deallocate doesn't raise when no vif is returned.

        Ensures https://bugs.launchpad.net/nova/+bug/968457 doesn't return
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        def vif_get(_context, _vif_id):
            return None

        self.stub_out('nova.db.virtual_interface_get', vif_get)
        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)

        instance = db.instance_create(context1,
                                      {'project_id': fakes.FAKE_PROJECT_ID})

        elevated = context1.elevated()
        fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))
        self.flags(force_dhcp_release=True)
        fixed_update.return_value = fixed_get.return_value
        self.network.deallocate_fixed_ip(context1, fix_addr.address, 'fake')
        fixed_update.assert_called_once_with(context1, fix_addr.address,
                                             {'allocated': False})

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_fixed_ip_cleanup_fail(self, fixed_update, net_get, fixed_get):
        # Verify IP is not deallocated if the security group refresh fails.
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])
        context1 = context.RequestContext('user', fakes.FAKE_PROJECT_ID)

        instance = db.instance_create(context1,
                {'project_id': fakes.FAKE_PROJECT_ID})

        elevated = context1.elevated()
        fix_addr = objects.FixedIP.associate_pool(elevated, 1,
                                                  instance['uuid'])

        def fake_refresh(instance_uuid):
            raise test.TestingException()
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                fake_refresh)
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))
        self.assertRaises(test.TestingException,
                          self.network.deallocate_fixed_ip,
                          context1, str(fix_addr.address), 'fake')
        self.assertFalse(fixed_update.called)

    def test_get_networks_by_uuids_ordering(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = ['bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        self.mox.ReplayAll()
        res = self.network._get_networks_by_uuids(self.context,
                                                  requested_networks)

        self.assertEqual(1, res[0]['id'])
        self.assertEqual(0, res[1]['id'])

    @mock.patch('nova.objects.fixed_ip.FixedIP.get_by_id')
    @mock.patch('nova.objects.floating_ip.FloatingIPList.get_by_host')
    @mock.patch('nova.network.linux_net.iptables_manager._apply')
    def test_init_host_iptables_defer_apply(self, iptable_apply,
                                            floating_get_by_host,
                                            fixed_get_by_id):
        def get_by_id(context, fixed_ip_id, **kwargs):
            net = objects.Network(bridge='testbridge',
                                      cidr='192.168.1.0/24')
            if fixed_ip_id == 1:
                return objects.FixedIP(address='192.168.1.4',
                                            network=net)
            elif fixed_ip_id == 2:
                return objects.FixedIP(address='192.168.1.5',
                                            network=net)

        def fake_apply():
            fake_apply.count += 1

        fake_apply.count = 0
        ctxt = context.RequestContext('testuser',
                                      fakes.FAKE_PROJECT_ID,
                                      is_admin=True)
        float1 = objects.FloatingIP(address='1.2.3.4', fixed_ip_id=1)
        float2 = objects.FloatingIP(address='1.2.3.5', fixed_ip_id=2)
        float1._context = ctxt
        float2._context = ctxt

        iptable_apply.side_effect = fake_apply
        floating_get_by_host.return_value = [float1, float2]
        fixed_get_by_id.side_effect = get_by_id

        self.network.init_host()
        self.assertEqual(1, fake_apply.count)


class _TestDomainObject(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            self.__setattr__(k, v)


class CommonNetworkTestCase(test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(CommonNetworkTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.flags(ipv6_backend='rfc2462', use_neutron=False)
        ipv6.reset_backend()

    def test_validate_instance_zone_for_dns_domain(self):
        domain = 'example.com'
        az = 'test_az'
        domains = {
            domain: _TestDomainObject(
                domain=domain,
                availability_zone=az)}

        def dnsdomain_get(context, instance_domain):
            return domains.get(instance_domain)

        self.stub_out('nova.db.dnsdomain_get', dnsdomain_get)
        fake_instance = {'uuid': FAKEUUID,
                         'availability_zone': az}

        manager = network_manager.NetworkManager()
        res = manager._validate_instance_zone_for_dns_domain(self.context,
                                                             fake_instance)
        self.assertTrue(res)

    def fake_create_fixed_ips(self, context, network_id, fixed_cidr=None,
                              extra_reserved=None, bottom_reserved=0,
                              top_reserved=0):
        return None

    def test_get_instance_nw_info_client_exceptions(self):
        manager = network_manager.NetworkManager()
        self.mox.StubOutWithMock(manager.db,
                                 'fixed_ip_get_by_instance')
        manager.db.fixed_ip_get_by_instance(
                self.context, FAKEUUID).AndRaise(exception.InstanceNotFound(
                                                 instance_id=FAKEUUID))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          manager.get_instance_nw_info,
                          self.context, FAKEUUID, 'fake_rxtx_factor', HOST)

    @mock.patch('nova.db.instance_get')
    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_deallocate_for_instance_passes_host_info(self, fixed_get,
                                                      instance_get):
        manager = fake_network.FakeNetworkManager()
        db = manager.db
        instance_get.return_value = fake_inst(uuid=uuids.non_existent_uuid)
        db.virtual_interface_delete_by_instance = lambda _x, _y: None
        ctx = context.RequestContext('igonre', 'igonre')

        fixed_get.return_value = [dict(test_fixed_ip.fake_fixed_ip,
                                       address='1.2.3.4',
                                       network_id=123)]

        manager.deallocate_for_instance(
            ctx, instance=objects.Instance._from_db_object(self.context,
                objects.Instance(), instance_get.return_value))

        self.assertEqual([
            (ctx, '1.2.3.4', 'fake-host')
        ], manager.deallocate_fixed_ip_calls)

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_deallocate_for_instance_passes_host_info_with_update_dns_entries(
            self, fixed_get):
        self.flags(update_dns_entries=True)
        manager = fake_network.FakeNetworkManager()
        db = manager.db
        db.virtual_interface_delete_by_instance = lambda _x, _y: None
        ctx = context.RequestContext('igonre', 'igonre')

        fixed_get.return_value = [dict(test_fixed_ip.fake_fixed_ip,
                                       address='1.2.3.4',
                                       network_id=123)]

        with mock.patch.object(manager.network_rpcapi,
                               'update_dns') as mock_update_dns:
            manager.deallocate_for_instance(
                ctx, instance=fake_instance.fake_instance_obj(ctx))
            mock_update_dns.assert_called_once_with(ctx, ['123'])

        self.assertEqual([
            (ctx, '1.2.3.4', 'fake-host')
        ], manager.deallocate_fixed_ip_calls)

    def test_deallocate_for_instance_with_requested_networks(self):
        manager = fake_network.FakeNetworkManager()
        db = manager.db
        db.virtual_interface_delete_by_instance = mock.Mock()
        ctx = context.RequestContext('igonre', 'igonre')
        requested_networks = objects.NetworkRequestList.from_tuples(
            [('123', '1.2.3.4'), ('123', '4.3.2.1'), ('123', None)])
        manager.deallocate_for_instance(
            ctx,
            instance=fake_instance.fake_instance_obj(ctx),
            requested_networks=requested_networks)

        self.assertEqual([
            (ctx, '1.2.3.4', 'fake-host'), (ctx, '4.3.2.1', 'fake-host')
        ], manager.deallocate_fixed_ip_calls)

    def test_deallocate_for_instance_with_update_dns_entries(self):
        self.flags(update_dns_entries=True)
        manager = fake_network.FakeNetworkManager()
        db = manager.db
        db.virtual_interface_delete_by_instance = mock.Mock()
        ctx = context.RequestContext('igonre', 'igonre')
        requested_networks = objects.NetworkRequestList.from_tuples(
            [('123', '1.2.3.4'), ('123', '4.3.2.1')])
        with mock.patch.object(manager.network_rpcapi,
                               'update_dns') as mock_update_dns:
            manager.deallocate_for_instance(
                ctx,
                instance=fake_instance.fake_instance_obj(ctx),
                requested_networks=requested_networks)
            mock_update_dns.assert_called_once_with(ctx, ['123'])

        self.assertEqual([
            (ctx, '1.2.3.4', 'fake-host'), (ctx, '4.3.2.1', 'fake-host')
        ], manager.deallocate_fixed_ip_calls)

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    @mock.patch('nova.db.fixed_ip_disassociate')
    def test_remove_fixed_ip_from_instance(self, disassociate, get):
        manager = fake_network.FakeNetworkManager()
        get.return_value = [
            dict(test_fixed_ip.fake_fixed_ip, **x)
            for x in manager.db.fixed_ip_get_by_instance(None,
                                                         FAKEUUID)]
        manager.remove_fixed_ip_from_instance(self.context, FAKEUUID,
                                              HOST,
                                              '10.0.0.1')

        self.assertEqual('10.0.0.1', manager.deallocate_called)
        disassociate.assert_called_once_with(self.context, '10.0.0.1')

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_remove_fixed_ip_from_instance_bad_input(self, get):
        manager = fake_network.FakeNetworkManager()
        get.return_value = []
        self.assertRaises(exception.FixedIpNotFoundForSpecificInstance,
                          manager.remove_fixed_ip_from_instance,
                          self.context, 99, HOST, 'bad input')

    def test_validate_cidrs(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/24',
                                       False, 1, 256, None, None, None,
                                       None, None)
        self.assertEqual(1, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/24', cidrs)

    def test_validate_cidrs_split_exact_in_half(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/24',
                                       False, 2, 128, None, None, None,
                                       None, None)
        self.assertEqual(2, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/25', cidrs)
        self.assertIn('192.168.0.128/25', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_cidr_in_use_middle_of_range(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.0/24')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 4, 256, None, None, None,
                                       None, None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/24', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_smaller_subnet_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.9/25')]
        # CidrConflict: requested cidr (192.168.2.0/24) conflicts with
        #               existing smaller cidr
        args = (self.context.elevated(), 'fake', '192.168.2.0/24', False,
                1, 256, None, None, None, None, None)
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_smaller_cidr_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.0/25')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 4, 256, None, None, None, None,
                                       None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/24', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_smaller_cidr_in_use2(self, get_all):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        get_all.return_value = [dict(test_network.fake_network, id=1,
                                     cidr='192.168.2.9/29')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.2.0/24',
                                       False, 3, 32, None, None, None, None,
                                       None)
        self.assertEqual(3, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.2.32/27', '192.168.2.64/27', '192.168.2.96/27']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/27', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_all_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        in_use = [dict(test_network.fake_network, **values) for values in
                  [{'id': 1, 'cidr': '192.168.2.9/29'},
                   {'id': 2, 'cidr': '192.168.2.64/26'},
                   {'id': 3, 'cidr': '192.168.2.128/26'}]]
        get_all.return_value = in_use
        args = (self.context.elevated(), 'fake', '192.168.2.0/24', False,
                3, 64, None, None, None, None, None)
        # CidrConflict: Not enough subnets avail to satisfy requested num_
        #               networks - some subnets in requested range already
        #               in use
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_validate_cidrs_one_in_use(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 2, 256, None, None,
                None, None, None)
        # ValueError: network_size * num_networks exceeds cidr size
        self.assertRaises(ValueError, manager.create_networks, *args)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_already_used(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     cidr='192.168.0.0/24')]
        # CidrConflict: cidr already in use
        args = (self.context.elevated(), 'fake', '192.168.0.0/24', False,
                1, 256, None, None, None, None, None)
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_validate_cidrs_too_many(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 200, 256, None, None,
                None, None, None)
        # ValueError: Not enough subnets avail to satisfy requested
        #             num_networks
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_partial(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 2, 256, None, None, None, None,
                                       None)
        returned_cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/24', returned_cidrs)
        self.assertIn('192.168.1.0/24', returned_cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_conflict_existing_supernet(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.0.0/8')]
        args = (self.context.elevated(), 'fake', '192.168.0.0/24', False,
                1, 256, None, None, None, None, None)
        # CidrConflict: requested cidr (192.168.0.0/24) conflicts
        #               with existing supernet
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_create_networks(self):
        cidr = '192.168.0.0/24'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [self.context.elevated(), 'foo', cidr, None, 1, 256,
                'fd00::/48', None, None, None, None, None]
        self.assertTrue(manager.create_networks(*args))

    def test_create_networks_with_uuid(self):
        cidr = '192.168.0.0/24'
        uuid = FAKEUUID
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [self.context.elevated(), 'foo', cidr, None, 1, 256,
                'fd00::/48', None, None, None, None, None]
        kwargs = {'uuid': uuid}
        nets = manager.create_networks(*args, **kwargs)
        self.assertEqual(1, len(nets))
        net = nets[0]
        self.assertEqual(uuid, net['uuid'])

    @mock.patch('nova.db.network_get_all')
    def test_create_networks_cidr_already_used(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.0.0/24')]
        args = [self.context.elevated(), 'foo', '192.168.0.0/24', None, 1, 256,
                 'fd00::/48', None, None, None, None, None]
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_create_networks_many(self):
        cidr = '192.168.0.0/16'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [self.context.elevated(), 'foo', cidr, None, 10, 256,
                'fd00::/48', None, None, None, None, None]
        self.assertTrue(manager.create_networks(*args))

    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ips_by_virtual_interface')
    def test_get_instance_uuids_by_ip_regex(self, fixed_get, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        fixed_get.side_effect = manager.db.fixed_ips_by_virtual_interface
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')
        network_get.return_value = dict(test_network.fake_network,
                                        **manager.db.network_get(None, 1))

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '.*'})
        self.assertEqual(len(_vifs), len(res))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '10.0.0.1'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[1]['instance_uuid'], res[0]['instance_uuid'])

        # Get instance 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '173.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[2]['instance_uuid'], res[0]['instance_uuid'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.*'})
        self.assertTrue(res)
        self.assertEqual(2, len(res))
        self.assertEqual(_vifs[0]['instance_uuid'], res[0]['instance_uuid'])
        self.assertEqual(_vifs[1]['instance_uuid'], res[1]['instance_uuid'])

        # Get instance 1 and 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '17..16.0.2'})
        self.assertTrue(res)
        self.assertEqual(2, len(res))
        self.assertEqual(_vifs[1]['instance_uuid'], res[0]['instance_uuid'])
        self.assertEqual(_vifs[2]['instance_uuid'], res[1]['instance_uuid'])

    @mock.patch('nova.db.network_get')
    def test_get_instance_uuids_by_ipv6_regex(self, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')

        def _network_get(context, network_id, **args):
            return dict(test_network.fake_network,
                        **manager.db.network_get(context, network_id))
        network_get.side_effect = _network_get

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*'})
        self.assertEqual(len(_vifs), len(res))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*1034.*'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '2001:.*2'})
        self.assertTrue(res)
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[1]['instance_uuid'], res[0]['instance_uuid'])

        # Get instance 2
        ip6 = '2001:db8:69:1f:dead:beff:feff:ef03'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[2]['instance_uuid'], res[0]['instance_uuid'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*ef0[1,2]'})
        self.assertTrue(res)
        self.assertEqual(2, len(res))
        self.assertEqual(_vifs[0]['instance_uuid'], res[0]['instance_uuid'])
        self.assertEqual(_vifs[1]['instance_uuid'], res[1]['instance_uuid'])

        # Get instance 1 and 2
        ip6 = '2001:db8:69:1.:dead:beff:feff:ef0.'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(2, len(res))
        self.assertEqual(_vifs[1]['instance_uuid'], res[0]['instance_uuid'])
        self.assertEqual(_vifs[2]['instance_uuid'], res[1]['instance_uuid'])

    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ips_by_virtual_interface')
    def test_get_instance_uuids_by_ip(self, fixed_get, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        fixed_get.side_effect = manager.db.fixed_ips_by_virtual_interface
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')
        network_get.return_value = dict(test_network.fake_network,
                                        **manager.db.network_get(None, 1))

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
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[1]['instance_uuid'], res[0]['instance_uuid'])

        # Get instance 2
        ip = '173.16.0.2'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertTrue(res)
        self.assertEqual(1, len(res))
        self.assertEqual(_vifs[2]['instance_uuid'], res[0]['instance_uuid'])

    @mock.patch('nova.db.network_get_by_uuid')
    def test_get_network(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.return_value = dict(test_network.fake_network, **networks[0])
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        network = manager.get_network(fake_context, uuid)
        self.assertEqual(uuid, network['uuid'])

    @mock.patch('nova.db.network_get_by_uuid')
    def test_get_network_not_found(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.side_effect = exception.NetworkNotFoundForUUID(uuid='foo')
        uuid = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.assertRaises(exception.NetworkNotFound,
                          manager.get_network, fake_context, uuid)

    @mock.patch('nova.db.network_get_all')
    def test_get_all_networks(self, get_all):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get_all.return_value = [dict(test_network.fake_network, **net)
                                for net in networks]
        output = manager.get_all_networks(fake_context)
        self.assertEqual(2, len(networks))
        self.assertEqual('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                         output[0]['uuid'])
        self.assertEqual('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                         output[1]['uuid'])

    @mock.patch('nova.db.network_get_by_uuid')
    @mock.patch('nova.db.network_disassociate')
    def test_disassociate_network(self, disassociate, get):
        manager = fake_network.FakeNetworkManager()
        disassociate.return_value = True
        fake_context = context.RequestContext('user', 'project')
        get.return_value = dict(test_network.fake_network,
                                **networks[0])
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        manager.disassociate_network(fake_context, uuid)

    @mock.patch('nova.db.network_get_by_uuid')
    def test_disassociate_network_not_found(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.side_effect = exception.NetworkNotFoundForUUID(uuid='fake')
        uuid = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.assertRaises(exception.NetworkNotFound,
                          manager.disassociate_network, fake_context, uuid)

    def _test_init_host_dynamic_fixed_range(self, net_manager):
        self.flags(fake_network=True,
                   routing_source_ip='172.16.0.1',
                   metadata_host='172.16.0.1',
                   public_interface='eth1',
                   dmz_cidr=['10.0.3.0/24'])
        binary_name = linux_net.get_binary_name()

        # Stub out calls we don't want to really run, mock the db
        self.stubs.Set(linux_net.iptables_manager, '_apply', lambda: None)
        self.stubs.Set(floating_ips.FloatingIP, 'init_host_floating_ips',
                                                lambda *args: None)
        self.stubs.Set(net_manager.l3driver, 'initialize_gateway',
                                             lambda *args: None)
        self.mox.StubOutWithMock(db, 'network_get_all_by_host')
        fake_networks = [dict(test_network.fake_network, **n)
                         for n in networks]
        db.network_get_all_by_host(mox.IgnoreArg(),
                                   mox.IgnoreArg()
                                   ).MultipleTimes().AndReturn(fake_networks)
        self.mox.ReplayAll()

        net_manager.init_host()

        # Get the iptables rules that got created
        current_lines = []
        new_lines = linux_net.iptables_manager._modify_rules(current_lines,
                                       linux_net.iptables_manager.ipv4['nat'],
                                       table_name='nat')

        expected_lines = ['[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                          '-j SNAT --to-source %s -o %s'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.routing_source_ip,
                                          CONF.public_interface),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.metadata_host),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.dmz_cidr[0]),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack ! '
                          '--ctstate DNAT -j ACCEPT' % (binary_name,
                                                        networks[0]['cidr'],
                                                        networks[0]['cidr']),
                          '[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                          '-j SNAT --to-source %s -o %s'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.routing_source_ip,
                                          CONF.public_interface),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.metadata_host),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.dmz_cidr[0]),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack ! '
                          '--ctstate DNAT -j ACCEPT' % (binary_name,
                                                        networks[1]['cidr'],
                                                        networks[1]['cidr'])]

        # Compare the expected rules against the actual ones
        for line in expected_lines:
            self.assertIn(line, new_lines)

        # Add an additional network and ensure the rules get configured
        new_network = {'id': 2,
                       'uuid': uuids.network_1,
                       'label': 'test2',
                       'injected': False,
                       'multi_host': False,
                       'cidr': '192.168.2.0/24',
                       'cidr_v6': '2001:dba::/64',
                       'gateway_v6': '2001:dba::1',
                       'netmask_v6': '64',
                       'netmask': '255.255.255.0',
                       'bridge': 'fa1',
                       'bridge_interface': 'fake_fa1',
                       'gateway': '192.168.2.1',
                       'dhcp_server': '192.168.2.1',
                       'broadcast': '192.168.2.255',
                       'dns1': '192.168.2.1',
                       'dns2': '192.168.2.2',
                       'vlan': None,
                       'host': HOST,
                       'project_id': fakes.FAKE_PROJECT_ID,
                       'vpn_public_address': '192.168.2.2',
                       'vpn_public_port': '22',
                       'vpn_private_address': '10.0.0.2'}
        new_network_obj = objects.Network._from_db_object(
            self.context, objects.Network(),
            dict(test_network.fake_network, **new_network))

        ctxt = context.get_admin_context()
        net_manager._setup_network_on_host(ctxt, new_network_obj)

        # Get the new iptables rules that got created from adding a new network
        current_lines = []
        new_lines = linux_net.iptables_manager._modify_rules(current_lines,
                                       linux_net.iptables_manager.ipv4['nat'],
                                       table_name='nat')

        # Add the new expected rules to the old ones
        expected_lines += ['[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                           '-j SNAT --to-source %s -o %s'
                           % (binary_name, new_network['cidr'],
                                           CONF.routing_source_ip,
                                           CONF.public_interface),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                           % (binary_name, new_network['cidr'],
                                           CONF.metadata_host),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                           % (binary_name, new_network['cidr'],
                                           CONF.dmz_cidr[0]),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack '
                           '! --ctstate DNAT -j ACCEPT' % (binary_name,
                                                       new_network['cidr'],
                                                       new_network['cidr'])]

        # Compare the expected rules (with new network) against the actual ones
        for line in expected_lines:
            self.assertIn(line, new_lines)

    def test_flatdhcpmanager_dynamic_fixed_range(self):
        """Test FlatDHCPManager NAT rules for fixed_range."""
        # Set the network manager
        self.network = network_manager.FlatDHCPManager(host=HOST)
        self.network.db = db

        # Test new behavior:
        #     CONF.fixed_range is not set, defaults to None
        #     Determine networks to NAT based on lookup
        self._test_init_host_dynamic_fixed_range(self.network)

    def test_vlanmanager_dynamic_fixed_range(self):
        """Test VlanManager NAT rules for fixed_range."""
        # Set the network manager
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db

        # Test new behavior:
        #     CONF.fixed_range is not set, defaults to None
        #     Determine networks to NAT based on lookup
        self._test_init_host_dynamic_fixed_range(self.network)

    def test_fixed_cidr_out_of_range(self):
        manager = network_manager.NetworkManager()
        ctxt = context.get_admin_context()
        self.assertRaises(exception.AddressOutOfRange,
                          manager.create_networks, ctxt, label="fake",
                          cidr='10.1.0.0/24', fixed_cidr='10.1.1.0/25')


class TestRPCFixedManager(network_manager.RPCAllocateFixedIP,
        network_manager.NetworkManager):
    """Dummy manager that implements RPCAllocateFixedIP."""


class RPCAllocateTestCase(test.NoDBTestCase):
    """Tests nova.network.manager.RPCAllocateFixedIP."""
    def setUp(self):
        super(RPCAllocateTestCase, self).setUp()
        self.rpc_fixed = TestRPCFixedManager()
        self.context = context.RequestContext('fake', 'fake')

    def test_rpc_allocate(self):
        """Test to verify bug 855030 doesn't resurface.

        Mekes sure _rpc_allocate_fixed_ip returns a value so the call
        returns properly and the greenpool completes.
        """
        address = '10.10.10.10'

        def fake_allocate(*args, **kwargs):
            return address

        def fake_network_get(*args, **kwargs):
            return test_network.fake_network

        self.stubs.Set(self.rpc_fixed, 'allocate_fixed_ip', fake_allocate)
        self.stubs.Set(self.rpc_fixed.db, 'network_get', fake_network_get)
        rval = self.rpc_fixed._rpc_allocate_fixed_ip(self.context,
                                                     'fake_instance',
                                                     'fake_network')
        self.assertEqual(address, rval)


class TestFloatingIPManager(floating_ips.FloatingIP,
        network_manager.NetworkManager):
    """Dummy manager that implements FloatingIP."""


class AllocateTestCase(test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(AllocateTestCase, self).setUp()
        dns = 'nova.network.noop_dns_driver.NoopDNSDriver'
        self.flags(instance_dns_manager=dns)
        self.useFixture(test.SampleNetworks())
        self.network = network_manager.VlanManager(host=HOST)

        self.user_id = fakes.FAKE_USER_ID
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)
        self.user_context = context.RequestContext('testuser',
                                                   fakes.FAKE_PROJECT_ID)

    def test_allocate_for_instance(self):
        address = "10.10.10.10"
        self.flags(auto_assign_floating_ip=True)

        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        inst = objects.Instance(context=self.context)
        inst.host = HOST
        inst.display_name = HOST
        inst.instance_type_id = 1
        inst.uuid = FAKEUUID
        inst.create()
        networks = db.network_get_all(self.context)
        reqnets = objects.NetworkRequestList(objects=[])
        index = 0
        project_id = self.user_context.project_id
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': HOST,
                               'project_id': project_id})
            if index == 0:
                reqnets.objects.append(objects.NetworkRequest(
                    network_id=network['uuid'],
                    tag='mynic'))
            index += 1
        nw_info = self.network.allocate_for_instance(self.user_context,
            instance_id=inst['id'], instance_uuid=inst['uuid'],
            host=inst['host'], vpn=None, rxtx_factor=3,
            project_id=project_id, macs=None, requested_networks=reqnets)
        self.assertEqual(1, len(nw_info))
        vifs = objects.VirtualInterfaceList.get_all(self.context)
        self.assertEqual(['mynic'], [vif.tag for vif in vifs])
        fixed_ip = nw_info.fixed_ips()[0]['address']
        self.assertTrue(netutils.is_valid_ipv4(fixed_ip))
        self.network.deallocate_for_instance(self.context,
                instance=inst)

    def test_allocate_for_instance_illegal_network(self):
        networks = db.network_get_all(self.context)
        requested_networks = []
        for network in networks:
            # set all networks to other projects
            db.network_update(self.context, network['id'],
                              {'host': HOST,
                               'project_id': 'otherid'})
            requested_networks.append((network['uuid'], None))
        # set the first network to our project
        db.network_update(self.context, networks[0]['id'],
                          {'project_id': self.user_context.project_id})

        inst = objects.Instance(context=self.context)
        inst.host = HOST
        inst.display_name = HOST
        inst.instance_type_id = 1
        inst.uuid = FAKEUUID
        inst.create()
        self.assertRaises(exception.NetworkNotFoundForProject,
            self.network.allocate_for_instance, self.user_context,
            instance_id=inst['id'], instance_uuid=inst['uuid'],
            host=inst['host'], vpn=None, rxtx_factor=3,
            project_id=self.context.project_id, macs=None,
            requested_networks=requested_networks)

    def test_allocate_for_instance_with_mac(self):
        available_macs = set(['ca:fe:de:ad:be:ef'])
        inst = db.instance_create(self.context, {'host': HOST,
                                                 'display_name': HOST,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': HOST})
        project_id = self.context.project_id
        nw_info = self.network.allocate_for_instance(self.user_context,
            instance_id=inst['id'], instance_uuid=inst['uuid'],
            host=inst['host'], vpn=None, rxtx_factor=3,
            project_id=project_id, macs=available_macs)
        assigned_macs = [vif['address'] for vif in nw_info]
        self.assertEqual(1, len(assigned_macs))
        self.assertEqual(available_macs.pop(), assigned_macs[0])
        self.network.deallocate_for_instance(self.context,
                                             instance_id=inst['id'],
                                             host=self.network.host,
                                             project_id=project_id)

    def test_allocate_for_instance_not_enough_macs(self):
        available_macs = set()
        inst = db.instance_create(self.context, {'host': HOST,
                                                 'display_name': HOST,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self.network.allocate_for_instance,
                          self.user_context,
                          instance_id=inst['id'], instance_uuid=inst['uuid'],
                          host=inst['host'], vpn=None, rxtx_factor=3,
                          project_id=project_id, macs=available_macs)


class FloatingIPTestCase(test.TestCase):
    """Tests nova.network.manager.FloatingIP."""

    REQUIRES_LOCKING = True

    def setUp(self):
        super(FloatingIPTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.network = TestFloatingIPManager()
        self.network.db = db
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = context.RequestContext('testuser', self.project_id,
            is_admin=False)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get_by_uuid')
    @mock.patch('nova.db.service_get_by_host_and_binary')
    @mock.patch('nova.db.floating_ip_get_by_address')
    def test_disassociate_floating_ip_multi_host_calls(self, floating_get,
                                                       service_get,
                                                       inst_get, net_get,
                                                       fixed_get):
        floating_ip = dict(test_floating_ip.fake_floating_ip,
                           fixed_ip_id=12)

        fixed_ip = dict(test_fixed_ip.fake_fixed_ip,
                        network_id=None,
                        instance_uuid=uuids.instance)

        network = dict(test_network.fake_network,
                       multi_host=True)

        instance = dict(fake_instance.fake_db_instance(host='some-other-host'))

        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        self.stubs.Set(self.network,
                       '_floating_ip_owned_by_project',
                       lambda _x, _y: True)

        floating_get.return_value = floating_ip
        fixed_get.return_value = fixed_ip
        net_get.return_value = network
        inst_get.return_value = instance
        service_get.return_value = test_service.fake_service

        self.stubs.Set(self.network.servicegroup_api,
                       'service_is_up',
                       lambda _x: True)

        self.mox.StubOutWithMock(
            self.network.network_rpcapi, '_disassociate_floating_ip')

        self.network.network_rpcapi._disassociate_floating_ip(
            ctxt, 'fl_ip', mox.IgnoreArg(), 'some-other-host',
            uuids.instance)
        self.mox.ReplayAll()

        self.network.disassociate_floating_ip(ctxt, 'fl_ip', True)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get_by_uuid')
    @mock.patch('nova.db.floating_ip_get_by_address')
    def test_associate_floating_ip_multi_host_calls(self, floating_get,
                                                    inst_get, net_get,
                                                    fixed_get):
        floating_ip = dict(test_floating_ip.fake_floating_ip,
                           fixed_ip_id=None)

        fixed_ip = dict(test_fixed_ip.fake_fixed_ip,
                        network_id=None,
                        instance_uuid=uuids.instance)

        network = dict(test_network.fake_network,
                       multi_host=True)

        instance = dict(fake_instance.fake_db_instance(host='some-other-host'))

        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=False)

        self.stubs.Set(self.network,
                       '_floating_ip_owned_by_project',
                       lambda _x, _y: True)

        floating_get.return_value = floating_ip
        fixed_get.return_value = fixed_ip
        net_get.return_value = network
        inst_get.return_value = instance

        self.mox.StubOutWithMock(
            self.network.network_rpcapi, '_associate_floating_ip')

        self.network.network_rpcapi._associate_floating_ip(
            ctxt, 'fl_ip', 'fix_ip', mox.IgnoreArg(), 'some-other-host',
            uuids.instance)
        self.mox.ReplayAll()

        self.network.associate_floating_ip(ctxt, 'fl_ip', 'fix_ip', True)

    def test_double_deallocation(self):
        instance_ref = db.instance_create(self.context,
                {"project_id": self.project_id})
        # Run it twice to make it fault if it does not handle
        # instances without fixed networks
        # If this fails in either, it does not handle having no addresses
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])

    def test_deallocation_deleted_instance(self):
        self.stubs.Set(self.network, '_teardown_network_on_host',
                       lambda *args, **kwargs: None)
        instance = objects.Instance(context=self.context)
        instance.project_id = self.project_id
        instance.create()
        instance.destroy()
        network = db.network_create_safe(self.context.elevated(), {
                'project_id': self.project_id,
                'host': CONF.host,
                'label': 'foo'})
        fixed = db.fixed_ip_create(self.context, {'allocated': True,
                'instance_uuid': instance.uuid, 'address': '10.1.1.1',
                'network_id': network['id']})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10', 'instance_uuid': instance.uuid,
                'fixed_ip_id': fixed['id'],
                'project_id': self.project_id})
        self.network.deallocate_for_instance(self.context, instance=instance)

    def test_deallocation_duplicate_floating_ip(self):
        self.stubs.Set(self.network, '_teardown_network_on_host',
                       lambda *args, **kwargs: None)
        instance = objects.Instance(context=self.context)
        instance.project_id = self.project_id
        instance.create()
        network = db.network_create_safe(self.context.elevated(), {
                'project_id': self.project_id,
                'host': CONF.host,
                'label': 'foo'})
        fixed = db.fixed_ip_create(self.context, {'allocated': True,
                'instance_uuid': instance.uuid, 'address': '10.1.1.1',
                'network_id': network['id']})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10',
                'deleted': True})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10', 'instance_uuid': instance.uuid,
                'fixed_ip_id': fixed['id'],
                'project_id': self.project_id})
        self.network.deallocate_for_instance(self.context, instance=instance)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.floating_ip_get_by_address')
    @mock.patch('nova.db.floating_ip_update')
    def test_migrate_instance_start(self, floating_update, floating_get,
                                    fixed_get):
        called = {'count': 0}

        def fake_floating_ip_get_by_address(context, address):
            return dict(test_floating_ip.fake_floating_ip,
                        address=address,
                        fixed_ip_id=0)

        def fake_is_stale_floating_ip_address(context, floating_ip):
            return str(floating_ip.address) == '172.24.4.23'

        floating_get.side_effect = fake_floating_ip_get_by_address
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      instance_uuid=uuids.instance,
                                      address='10.0.0.2',
                                      network=test_network.fake_network)
        floating_update.return_value = fake_floating_ip_get_by_address(
            None, '1.2.3.4')

        def fake_remove_floating_ip(floating_addr, fixed_addr, interface,
                                    network):
            called['count'] += 1

        def fake_clean_conntrack(fixed_ip):
            if not str(fixed_ip) == "10.0.0.2":
                raise exception.FixedIpInvalid(address=fixed_ip)

        self.stubs.Set(self.network, '_is_stale_floating_ip_address',
                                 fake_is_stale_floating_ip_address)
        self.stubs.Set(self.network.l3driver, 'remove_floating_ip',
                       fake_remove_floating_ip)
        self.stubs.Set(self.network.driver, 'clean_conntrack',
                       fake_clean_conntrack)
        self.mox.ReplayAll()
        addresses = ['172.24.4.23', '172.24.4.24', '172.24.4.25']
        self.network.migrate_instance_start(self.context,
                                            instance_uuid=FAKEUUID,
                                            floating_addresses=addresses,
                                            rxtx_factor=3,
                                            project_id=self.project_id,
                                            source='fake_source',
                                            dest='fake_dest')

        self.assertEqual(2, called['count'])

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.floating_ip_update')
    def test_migrate_instance_finish(self, floating_update, fixed_get):
        called = {'count': 0}

        def fake_floating_ip_get_by_address(context, address):
            return dict(test_floating_ip.fake_floating_ip,
                        address=address,
                        fixed_ip_id=0)

        def fake_is_stale_floating_ip_address(context, floating_ip):
            return str(floating_ip.address) == '172.24.4.23'

        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      instance_uuid=uuids.instance,
                                      address='10.0.0.2',
                                      network=test_network.fake_network)
        floating_update.return_value = fake_floating_ip_get_by_address(
            None, '1.2.3.4')

        def fake_add_floating_ip(floating_addr, fixed_addr, interface,
                                 network):
            called['count'] += 1

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address',
                       fake_floating_ip_get_by_address)
        self.stubs.Set(self.network, '_is_stale_floating_ip_address',
                                 fake_is_stale_floating_ip_address)
        self.stubs.Set(self.network.l3driver, 'add_floating_ip',
                       fake_add_floating_ip)
        self.mox.ReplayAll()
        addresses = ['172.24.4.23', '172.24.4.24', '172.24.4.25']
        self.network.migrate_instance_finish(self.context,
                                             instance_uuid=FAKEUUID,
                                             floating_addresses=addresses,
                                             host='fake_dest',
                                             rxtx_factor=3,
                                             project_id=self.project_id,
                                             source='fake_source')

        self.assertEqual(2, called['count'])

    def test_floating_dns_create_conflict(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"

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
        self.assertEqual(2, len(entries))
        self.assertEqual(name1, entries[0])
        self.assertEqual(name2, entries[1])

        entries = self.network.get_dns_entries_by_name(self.context,
                                                       name1, zone)
        self.assertEqual(1, len(entries))
        self.assertEqual(address1, entries[0])

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
        self.assertEqual(1, len(entries))
        self.assertEqual(name2, entries[0])

        self.assertRaises(exception.NotFound,
                          self.network.delete_dns_entry, self.context,
                          name1, zone)

    def test_floating_dns_domains_public(self):
        domain1 = "example.org"
        domain2 = "example.com"
        address1 = '10.10.10.10'
        entryname = 'testentry'

        self.network.create_public_dns_domain(self.context, domain1,
                                              fakes.FAKE_PROJECT_ID)
        self.network.create_public_dns_domain(self.context, domain2,
                                              'fakeproject')

        domains = self.network.get_dns_domains(self.context)
        self.assertEqual(2, len(domains))
        self.assertEqual(domain1, domains[0]['domain'])
        self.assertEqual(domain2, domains[1]['domain'])
        self.assertEqual(fakes.FAKE_PROJECT_ID, domains[0]['project'])
        self.assertEqual('fakeproject', domains[1]['project'])

        self.network.add_dns_entry(self.context, address1, entryname,
                                   'A', domain1)
        entries = self.network.get_dns_entries_by_name(self.context,
                                                       entryname, domain1)
        self.assertEqual(1, len(entries))
        self.assertEqual(address1, entries[0])

        self.network.delete_dns_domain(self.context, domain1)
        self.network.delete_dns_domain(self.context, domain2)

        # Verify that deleting the domain deleted the associated entry
        entries = self.network.get_dns_entries_by_name(self.context,
                                                       entryname, domain1)
        self.assertFalse(entries)

    def test_delete_all_by_ip(self):
        domain1 = "example.org"
        domain2 = "example.com"
        address = "10.10.10.10"
        name1 = "foo"
        name2 = "bar"

        def fake_domains(context):
            return [{'domain': 'example.org', 'scope': 'public'},
                    {'domain': 'example.com', 'scope': 'public'},
                    {'domain': 'test.example.org', 'scope': 'public'}]

        self.stubs.Set(self.network, 'get_dns_domains', fake_domains)

        context_admin = context.RequestContext('testuser',
                                               fakes.FAKE_PROJECT_ID,
                                               is_admin=True)

        self.network.create_public_dns_domain(context_admin, domain1,
                                              fakes.FAKE_PROJECT_ID)
        self.network.create_public_dns_domain(context_admin, domain2,
                                              'fakeproject')

        domains = self.network.get_dns_domains(self.context)
        for domain in domains:
            self.network.add_dns_entry(self.context, address,
                                       name1, "A", domain['domain'])
            self.network.add_dns_entry(self.context, address,
                                       name2, "A", domain['domain'])
            entries = self.network.get_dns_entries_by_address(self.context,
                                                              address,
                                                              domain['domain'])
            self.assertEqual(2, len(entries))

        self.network._delete_all_entries_for_ip(self.context, address)

        for domain in domains:
            entries = self.network.get_dns_entries_by_address(self.context,
                                                              address,
                                                              domain['domain'])
            self.assertFalse(entries)

        self.network.delete_dns_domain(context_admin, domain1)
        self.network.delete_dns_domain(context_admin, domain2)

    def test_mac_conflicts(self):
        # Make sure MAC collisions are retried.
        self.flags(create_unique_mac_address_attempts=3)
        ctxt = context.RequestContext('testuser', fakes.FAKE_PROJECT_ID,
                                      is_admin=True)
        macs = ['bb:bb:bb:bb:bb:bb', 'aa:aa:aa:aa:aa:aa']

        # Create a VIF with aa:aa:aa:aa:aa:aa
        crash_test_dummy_vif = {
            'address': macs[1],
            'instance_uuid': uuids.instance,
            'network_id': 123,
            'uuid': 'fake_uuid',
            }
        self.network.db.virtual_interface_create(ctxt, crash_test_dummy_vif)

        # Hand out a collision first, then a legit MAC
        def fake_gen_mac():
            return macs.pop()
        self.stubs.Set(utils, 'generate_mac_address', fake_gen_mac)

        # SQLite doesn't seem to honor the uniqueness constraint on the
        # address column, so fake the collision-avoidance here
        def fake_vif_save(vif, session=None):
            if vif.address == crash_test_dummy_vif['address']:
                raise db_exc.DBError("If you're smart, you'll retry!")
            # NOTE(russellb) The VirtualInterface object requires an ID to be
            # set, and we expect it to get set automatically when we do the
            # save.
            vif.id = 1
        self.stubs.Set(models.VirtualInterface, 'save', fake_vif_save)

        # Attempt to add another and make sure that both MACs are consumed
        # by the retry loop
        self.network._add_virtual_interface(ctxt, uuids.instance, 123)
        self.assertEqual([], macs)

    def test_deallocate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.deallocate_floating_ip,
                          self.context, '1.2.3.4')

    def test_associate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.associate_floating_ip,
                          self.context, '1.2.3.4', '10.0.0.1')

    def test_disassociate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.disassociate_floating_ip,
                          self.context, '1.2.3.4')

    def test_get_floating_ip_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get')
        self.network.db.floating_ip_get(self.context, 'fake-id').AndRaise(
            exception.FloatingIpNotFound(id='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.get_floating_ip,
                          self.context, 'fake-id')

    def _test_associate_floating_ip_failure(self, stdout, expected_exception):
        def _fake_catchall(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        network=test_network.fake_network)

        def _fake_add_floating_ip(*args, **kwargs):
            raise processutils.ProcessExecutionError(stdout)

        self.stubs.Set(self.network.db, 'floating_ip_fixed_ip_associate',
                _fake_catchall)
        self.stubs.Set(self.network.db, 'floating_ip_disassociate',
                _fake_catchall)
        self.stubs.Set(self.network.l3driver, 'add_floating_ip',
                _fake_add_floating_ip)

        self.assertRaises(expected_exception,
                          self.network._associate_floating_ip, self.context,
                          '1.2.3.4', '1.2.3.5', '', '')

    def test_associate_floating_ip_failure(self):
        self._test_associate_floating_ip_failure(None,
                processutils.ProcessExecutionError)

    def test_associate_floating_ip_failure_interface_not_found(self):
        self._test_associate_floating_ip_failure('Cannot find device',
                exception.NoFloatingIpInterface)

    @mock.patch('nova.objects.FloatingIP.get_by_address')
    def test_get_floating_ip_by_address(self, mock_get):
        mock_get.return_value = mock.sentinel.floating
        self.assertEqual(mock.sentinel.floating,
                         self.network.get_floating_ip_by_address(
                             self.context,
                             mock.sentinel.address))
        mock_get.assert_called_once_with(self.context, mock.sentinel.address)

    @mock.patch('nova.objects.FloatingIPList.get_by_project')
    def test_get_floating_ips_by_project(self, mock_get):
        mock_get.return_value = mock.sentinel.floatings
        self.assertEqual(mock.sentinel.floatings,
                         self.network.get_floating_ips_by_project(
                             self.context))
        mock_get.assert_called_once_with(self.context, self.context.project_id)

    @mock.patch('nova.objects.FloatingIPList.get_by_fixed_address')
    def test_get_floating_ips_by_fixed_address(self, mock_get):
        mock_get.return_value = [objects.FloatingIP(address='1.2.3.4'),
                                 objects.FloatingIP(address='5.6.7.8')]
        self.assertEqual(['1.2.3.4', '5.6.7.8'],
                         self.network.get_floating_ips_by_fixed_address(
                             self.context, mock.sentinel.address))
        mock_get.assert_called_once_with(self.context, mock.sentinel.address)

    @mock.patch('nova.db.floating_ip_get_pools')
    def test_floating_ip_pool_exists(self, floating_ip_get_pools):
        floating_ip_get_pools.return_value = [{'name': 'public'}]
        self.assertTrue(self.network._floating_ip_pool_exists(self.context,
                                                              'public'))

    @mock.patch('nova.db.floating_ip_get_pools')
    def test_floating_ip_pool_does_not_exist(self, floating_ip_get_pools):
        floating_ip_get_pools.return_value = []
        self.assertFalse(self.network._floating_ip_pool_exists(self.context,
                                                               'public'))


class InstanceDNSTestCase(test.TestCase):
    """Tests nova.network.manager instance DNS."""
    def setUp(self):
        super(InstanceDNSTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.network = TestFloatingIPManager()
        self.network.db = db
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = context.RequestContext('testuser', self.project_id,
            is_admin=False)

    def test_dns_domains_private(self):
        zone1 = 'testzone'
        domain1 = 'example.org'

        self.network.create_private_dns_domain(self.context, domain1, zone1)
        domains = self.network.get_dns_domains(self.context)
        self.assertEqual(1, len(domains))
        self.assertEqual(domain1, domains[0]['domain'])
        self.assertEqual(zone1, domains[0]['availability_zone'])

        self.network.delete_dns_domain(self.context, domain1)


domain1 = "example.org"
domain2 = "example.com"


@testtools.skipIf(six.PY3, 'python-ldap is not compatible for Python 3.')
class LdapDNSTestCase(test.NoDBTestCase):
    """Tests nova.network.ldapdns.LdapDNS."""
    def setUp(self):
        super(LdapDNSTestCase, self).setUp()

        self.useFixture(fixtures.MonkeyPatch(
            'nova.network.ldapdns.ldap',
            fake_ldap))
        dns_class = 'nova.network.ldapdns.LdapDNS'
        self.driver = importutils.import_object(dns_class)

        attrs = {'objectClass': ['domainrelatedobject', 'dnsdomain',
                                 'domain', 'dcobject', 'top'],
                 'associateddomain': ['root'],
                 'dc': ['root']}
        self.driver.lobj.add_s("ou=hosts,dc=example,dc=org", attrs.items())
        self.driver.create_domain(domain1)
        self.driver.create_domain(domain2)

    def tearDown(self):
        self.driver.delete_domain(domain1)
        self.driver.delete_domain(domain2)
        super(LdapDNSTestCase, self).tearDown()

    def test_ldap_dns_domains(self):
        domains = self.driver.get_domains()
        self.assertEqual(2, len(domains))
        self.assertIn(domain1, domains)
        self.assertIn(domain2, domains)

    def test_ldap_dns_create_conflict(self):
        address1 = "10.10.10.11"
        name1 = "foo"

        self.driver.create_entry(name1, address1, "A", domain1)

        self.assertRaises(exception.FloatingIpDNSExists,
                          self.driver.create_entry,
                          name1, address1, "A", domain1)

    def test_ldap_dns_create_and_get(self):
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertFalse(entries)

        self.driver.create_entry(name1, address1, "A", domain1)
        self.driver.create_entry(name2, address1, "A", domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertEqual(2, len(entries))
        self.assertEqual(name1, entries[0])
        self.assertEqual(name2, entries[1])

        entries = self.driver.get_entries_by_name(name1, domain1)
        self.assertEqual(1, len(entries))
        self.assertEqual(address1, entries[0])

    def test_ldap_dns_delete(self):
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"

        self.driver.create_entry(name1, address1, "A", domain1)
        self.driver.create_entry(name2, address1, "A", domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertEqual(2, len(entries))

        self.driver.delete_entry(name1, domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        LOG.debug("entries: %s", entries)
        self.assertEqual(1, len(entries))
        self.assertEqual(name2, entries[0])

        self.assertRaises(exception.NotFound,
                          self.driver.delete_entry,
                          name1, domain1)


class NetworkManagerNoDBTestCase(test.NoDBTestCase):
    """Tests nova.network.manager.NetworkManager without a database."""

    def setUp(self):
        super(NetworkManagerNoDBTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.manager = network_manager.NetworkManager()

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    def test_release_fixed_ip_not_associated(self, mock_fip_get_by_addr):
        # Tests that the method is a no-op when the fixed IP is not associated
        # to an instance.
        fip = objects.FixedIP._from_db_object(
            self.context, objects.FixedIP(), fake_network.next_fixed_ip(1))
        fip.instance_uuid = None
        with mock.patch.object(fip, 'disassociate') as mock_disassociate:
            self.manager.release_fixed_ip(self.context, fip.address)

        self.assertFalse(mock_disassociate.called,
                         str(mock_disassociate.mock_calls))

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    def test_release_fixed_ip_allocated(self, mock_fip_get_by_addr):
        # Tests that the fixed IP is not disassociated if it's allocated.
        fip = objects.FixedIP._from_db_object(
            self.context, objects.FixedIP(), fake_network.next_fixed_ip(1))
        fip.leased = False
        fip.allocated = True
        with mock.patch.object(fip, 'disassociate') as mock_disassociate:
            self.manager.release_fixed_ip(self.context, fip.address)

        self.assertFalse(mock_disassociate.called,
                         str(mock_disassociate.mock_calls))

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    @mock.patch.object(objects.VirtualInterface, 'get_by_address')
    def test_release_fixed_ip_mac_matches_associated_instance(self,
                                                        mock_vif_get_by_addr,
                                                        mock_fip_get_by_addr):
        # Tests that the fixed IP is disassociated when the mac passed to
        # release_fixed_ip matches the VIF which has the same instance_uuid
        # as the instance associated to the FixedIP object. Also tests
        # that the fixed IP is marked as not leased in the database if it was
        # currently leased.
        instance = fake_instance.fake_instance_obj(self.context)
        fip = fake_network.next_fixed_ip(1)
        fip['instance_uuid'] = instance.uuid
        fip['leased'] = True
        vif = fip['virtual_interface']
        vif['instance_uuid'] = instance.uuid
        vif = objects.VirtualInterface._from_db_object(
                    self.context, objects.VirtualInterface(), vif)
        fip = objects.FixedIP._from_db_object(
                    self.context, objects.FixedIP(), fip)
        mock_fip_get_by_addr.return_value = fip
        mock_vif_get_by_addr.return_value = vif

        with mock.patch.object(fip, 'save') as mock_fip_save:
            with mock.patch.object(fip, 'disassociate') as mock_disassociate:
                self.manager.release_fixed_ip(
                    self.context, fip.address, vif.address)

        mock_fip_save.assert_called_once_with()
        self.assertFalse(fip.leased)
        mock_vif_get_by_addr.assert_called_once_with(self.context, vif.address)
        mock_disassociate.assert_called_once_with()

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    @mock.patch.object(objects.VirtualInterface, 'get_by_address',
                       return_value=None)
    def test_release_fixed_ip_vif_not_found_for_mac(self, mock_vif_get_by_addr,
                                                    mock_fip_get_by_addr):
        # Tests that the fixed IP is disassociated when the fixed IP is marked
        # as deallocated and there is no VIF found in the database for the mac
        # passed in.
        fip = fake_network.next_fixed_ip(1)
        fip['leased'] = False
        mac = fip['virtual_interface']['address']
        fip = objects.FixedIP._from_db_object(
                    self.context, objects.FixedIP(), fip)
        mock_fip_get_by_addr.return_value = fip

        with mock.patch.object(fip, 'disassociate') as mock_disassociate:
            self.manager.release_fixed_ip(self.context, fip.address, mac)

        mock_vif_get_by_addr.assert_called_once_with(self.context, mac)
        mock_disassociate.assert_called_once_with()

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    def test_release_fixed_ip_no_mac(self, mock_fip_get_by_addr):
        # Tests that the fixed IP is disassociated when the fixed IP is
        # deallocated and there is no mac address passed in (like before
        # the network rpc api version bump to pass it in).
        fip = fake_network.next_fixed_ip(1)
        fip['leased'] = False
        fip = objects.FixedIP._from_db_object(
                    self.context, objects.FixedIP(), fip)
        mock_fip_get_by_addr.return_value = fip

        with mock.patch.object(fip, 'disassociate') as mock_disassociate:
            self.manager.release_fixed_ip(self.context, fip.address)

        mock_disassociate.assert_called_once_with()

    @mock.patch.object(objects.FixedIP, 'get_by_address')
    @mock.patch.object(objects.VirtualInterface, 'get_by_address')
    def test_release_fixed_ip_mac_mismatch_associated_instance(self,
                                                        mock_vif_get_by_addr,
                                                        mock_fip_get_by_addr):
        # Tests that the fixed IP is not disassociated when the VIF for the mac
        # passed to release_fixed_ip does not have an instance_uuid that
        # matches fixed_ip.instance_uuid.
        old_instance = fake_instance.fake_instance_obj(self.context)
        new_instance = fake_instance.fake_instance_obj(self.context)
        fip = fake_network.next_fixed_ip(1)
        fip['instance_uuid'] = new_instance.uuid
        fip['leased'] = False
        vif = fip['virtual_interface']
        vif['instance_uuid'] = old_instance.uuid
        vif = objects.VirtualInterface._from_db_object(
                    self.context, objects.VirtualInterface(), vif)
        fip = objects.FixedIP._from_db_object(
                    self.context, objects.FixedIP(), fip)
        mock_fip_get_by_addr.return_value = fip
        mock_vif_get_by_addr.return_value = vif

        with mock.patch.object(fip, 'disassociate') as mock_disassociate:
            self.manager.release_fixed_ip(
                self.context, fip.address, vif.address)

        mock_vif_get_by_addr.assert_called_once_with(self.context, vif.address)
        self.assertFalse(mock_disassociate.called,
                         str(mock_disassociate.mock_calls))

    @mock.patch.object(network_rpcapi.NetworkAPI, 'release_dhcp')
    @mock.patch.object(objects.FixedIP, 'get_by_address')
    @mock.patch.object(objects.VirtualInterface, 'get_by_id')
    @mock.patch.object(objects.Quotas, 'reserve')
    def test_deallocate_fixed_ip_explicit_disassociate(self,
                                                       mock_quota_reserve,
                                                       mock_vif_get_by_id,
                                                       mock_fip_get_by_addr,
                                                       mock_release_dhcp):
        # Tests that we explicitly call FixedIP.disassociate when the fixed IP
        # is not leased and has an associated instance (race with dnsmasq).
        self.flags(force_dhcp_release=True)
        fake_inst = fake_instance.fake_instance_obj(self.context)
        fip = fake_network.next_fixed_ip(1)
        fip['instance_uuid'] = fake_inst.uuid
        fip['leased'] = False
        vif = fip['virtual_interface']
        vif['instance_uuid'] = fake_inst.uuid
        vif = objects.VirtualInterface._from_db_object(
                    self.context, objects.VirtualInterface(), vif)
        fip = objects.FixedIP._from_db_object(
                    self.context, objects.FixedIP(), fip)
        fip.network = fake_network.fake_network_obj(self.context,
                                                    fip.network_id)
        mock_fip_get_by_addr.return_value = fip
        mock_vif_get_by_id.return_value = vif

        @mock.patch.object(self.manager,
                '_do_trigger_security_group_members_refresh_for_instance')
        @mock.patch.object(self.manager,
                           '_validate_instance_zone_for_dns_domain',
                           return_value=False)
        @mock.patch.object(self.manager, '_teardown_network_on_host')
        @mock.patch.object(fip, 'save')
        @mock.patch.object(fip, 'disassociate')
        def do_test(mock_disassociate, mock_fip_save,
                    mock_teardown_network_on_host, mock_validate_zone,
                    mock_trigger_secgroup_refresh):
            self.assertEqual(fake_inst.uuid, fip.instance_uuid)
            self.assertFalse(fip.leased)
            self.manager.deallocate_fixed_ip(
                self.context, fip['address'], instance=fake_inst)

            mock_trigger_secgroup_refresh.assert_called_once_with(
                                                                fake_inst.uuid)
            mock_teardown_network_on_host.assert_called_once_with(self.context,
                                                                  fip.network)
            mock_disassociate.assert_called_once_with()

        do_test()

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 NTT
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

import calendar
import os

import mox

from nova import context
from nova import db
from nova import flags
from nova.network import linux_net
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test
from nova import utils


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


HOST = "testhost"

instances = {'00000000-0000-0000-0000-0000000000000000':
                 {'id': 0,
                  'uuid': '00000000-0000-0000-0000-0000000000000000',
                  'host': 'fake_instance00',
                  'created_at': 'fakedate',
                  'updated_at': 'fakedate',
                  'hostname': 'fake_instance00'},
             '00000000-0000-0000-0000-0000000000000001':
                 {'id': 1,
                  'uuid': '00000000-0000-0000-0000-0000000000000001',
                  'host': 'fake_instance01',
                  'created_at': 'fakedate',
                  'updated_at': 'fakedate',
                  'hostname': 'fake_instance01'}}


addresses = [{"address": "10.0.0.1"},
             {"address": "10.0.0.2"},
             {"address": "10.0.0.3"},
             {"address": "10.0.0.4"},
             {"address": "10.0.0.5"},
             {"address": "10.0.0.6"}]


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
             'dhcp_server': '0.0.0.0',
             'dhcp_start': '192.168.100.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2'},
            {'id': 1,
             'uuid': "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
             'label': 'test1',
             'injected': False,
             'multi_host': True,
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
             'dhcp_server': '0.0.0.0',
             'dhcp_start': '192.168.100.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.1.2'}]


fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_id': 0,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 0,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000000',
              'floating_ips': []},
             {'id': 1,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_id': 0,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 1,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000000',
              'floating_ips': []},
             {'id': 2,
              'network_id': 1,
              'address': '192.168.0.101',
              'instance_id': 1,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 2,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000001',
              'floating_ips': []},
             {'id': 3,
              'network_id': 0,
              'address': '192.168.1.101',
              'instance_id': 1,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 3,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000001',
              'floating_ips': []},
             {'id': 4,
              'network_id': 0,
              'address': '192.168.0.102',
              'instance_id': 0,
              'allocated': True,
              'leased': False,
              'virtual_interface_id': 4,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000000',
              'floating_ips': []},
             {'id': 5,
              'network_id': 1,
              'address': '192.168.1.102',
              'instance_id': 1,
              'allocated': True,
              'leased': False,
              'virtual_interface_id': 5,
              'instance_uuid': '00000000-0000-0000-0000-0000000000000001',
              'floating_ips': []}]


vifs = [{'id': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'uuid': '00000000-0000-0000-0000-0000000000000000',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 1,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 2,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 3,
         'address': 'DE:AD:BE:EF:00:03',
         'uuid': '00000000-0000-0000-0000-0000000000000003',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 4,
         'address': 'DE:AD:BE:EF:00:04',
         'uuid': '00000000-0000-0000-0000-0000000000000004',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 5,
         'address': 'DE:AD:BE:EF:00:05',
         'uuid': '00000000-0000-0000-0000-0000000000000005',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'}]


def get_associated(context, network_id, host=None, address=None):
    result = []
    for datum in fixed_ips:
        if (datum['network_id'] == network_id and datum['allocated']
            and datum['instance_uuid'] is not None
            and datum['virtual_interface_id'] is not None):
            instance = instances[datum['instance_uuid']]
            if host and host != instance['host']:
                continue
            if address and address != datum['address']:
                continue
            cleaned = {}
            cleaned['address'] = datum['address']
            cleaned['instance_uuid'] = datum['instance_uuid']
            cleaned['network_id'] = datum['network_id']
            cleaned['vif_id'] = datum['virtual_interface_id']
            vif = vifs[datum['virtual_interface_id']]
            cleaned['vif_address'] = vif['address']
            cleaned['instance_hostname'] = instance['hostname']
            cleaned['instance_updated'] = instance['updated_at']
            cleaned['instance_created'] = instance['created_at']
            cleaned['allocated'] = datum['allocated']
            cleaned['leased'] = datum['leased']
            result.append(cleaned)
    return result


class LinuxNetworkTestCase(test.TestCase):

    def setUp(self):
        super(LinuxNetworkTestCase, self).setUp()
        network_driver = FLAGS.network_driver
        self.driver = importutils.import_module(network_driver)
        self.driver.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)

        def get_vifs(_context, instance_uuid):
            return [vif for vif in vifs if vif['instance_uuid'] == \
                        instance_uuid]

        def get_instance(_context, instance_id):
            return instances[instance_id]

        self.stubs.Set(db, 'virtual_interface_get_by_instance', get_vifs)
        self.stubs.Set(db, 'instance_get', get_instance)
        self.stubs.Set(db, 'network_get_associated_fixed_ips', get_associated)

    def test_update_dhcp_for_nw00(self):
        self.flags(use_single_default_gateway=True)

        self.mox.StubOutWithMock(self.driver, 'write_to_file')
        self.mox.StubOutWithMock(utils, 'ensure_tree')
        self.mox.StubOutWithMock(os, 'chmod')

        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())

        self.mox.ReplayAll()

        self.driver.update_dhcp(self.context, "eth0", networks[0])

    def test_update_dhcp_for_nw01(self):
        self.flags(use_single_default_gateway=True)

        self.mox.StubOutWithMock(self.driver, 'write_to_file')
        self.mox.StubOutWithMock(utils, 'ensure_tree')
        self.mox.StubOutWithMock(os, 'chmod')

        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        utils.ensure_tree(mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())

        self.mox.ReplayAll()

        self.driver.update_dhcp(self.context, "eth0", networks[0])

    def test_get_dhcp_hosts_for_nw00(self):
        self.flags(use_single_default_gateway=True)

        expected = (
                "DE:AD:BE:EF:00:00,fake_instance00.novalocal,"
                "192.168.0.100,net:NW-0\n"
                "DE:AD:BE:EF:00:03,fake_instance01.novalocal,"
                "192.168.1.101,net:NW-3\n"
                "DE:AD:BE:EF:00:04,fake_instance00.novalocal,"
                "192.168.0.102,net:NW-4"
        )
        actual_hosts = self.driver.get_dhcp_hosts(self.context, networks[0])

        self.assertEquals(actual_hosts, expected)

    def test_get_dhcp_hosts_for_nw01(self):
        self.flags(use_single_default_gateway=True)
        self.flags(host='fake_instance01')

        expected = (
                "DE:AD:BE:EF:00:02,fake_instance01.novalocal,"
                "192.168.0.101,net:NW-2\n"
                "DE:AD:BE:EF:00:05,fake_instance01.novalocal,"
                "192.168.1.102,net:NW-5"
        )
        actual_hosts = self.driver.get_dhcp_hosts(self.context, networks[1])
        self.assertEquals(actual_hosts, expected)

    def test_get_dhcp_opts_for_nw00(self):
        expected_opts = 'NW-3,3\nNW-4,3'
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[0])

        self.assertEquals(actual_opts, expected_opts)

    def test_get_dhcp_opts_for_nw01(self):
        self.flags(host='fake_instance01')
        expected_opts = "NW-5,3"
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[1])

        self.assertEquals(actual_opts, expected_opts)

    def test_get_dhcp_leases_for_nw00(self):
        timestamp = timeutils.utcnow()
        seconds_since_epoch = calendar.timegm(timestamp.utctimetuple())

        leases = self.driver.get_dhcp_leases(self.context, networks[0])
        leases = leases.split('\n')
        for lease in leases:
            lease = lease.split(' ')
            data = get_associated(self.context, 0, address=lease[2])[0]
            self.assertTrue(data['allocated'])
            self.assertTrue(data['leased'])
            self.assertTrue(lease[0] > seconds_since_epoch)
            self.assertTrue(lease[1] == data['vif_address'])
            self.assertTrue(lease[2] == data['address'])
            self.assertTrue(lease[3] == data['instance_hostname'])
            self.assertTrue(lease[4] == '*')

    def test_get_dhcp_leases_for_nw01(self):
        self.flags(host='fake_instance01')
        timestamp = timeutils.utcnow()
        seconds_since_epoch = calendar.timegm(timestamp.utctimetuple())

        leases = self.driver.get_dhcp_leases(self.context, networks[1])
        leases = leases.split('\n')
        for lease in leases:
            lease = lease.split(' ')
            data = get_associated(self.context, 1, address=lease[2])[0]
            self.assertTrue(data['allocated'])
            self.assertTrue(data['leased'])
            self.assertTrue(lease[0] > seconds_since_epoch)
            self.assertTrue(lease[1] == data['vif_address'])
            self.assertTrue(lease[2] == data['address'])
            self.assertTrue(lease[3] == data['instance_hostname'])
            self.assertTrue(lease[4] == '*')

    def test_dhcp_opts_not_default_gateway_network(self):
        expected = "NW-0,3"
        data = get_associated(self.context, 0)[0]
        actual = self.driver._host_dhcp_opts(data)
        self.assertEquals(actual, expected)

    def test_host_dhcp_without_default_gateway_network(self):
        expected = ','.join(['DE:AD:BE:EF:00:00',
                             'fake_instance00.novalocal',
                             '192.168.0.100'])
        data = get_associated(self.context, 0)[0]
        actual = self.driver._host_dhcp(data)
        self.assertEquals(actual, expected)

    def test_linux_bridge_driver_plug(self):
        """Makes sure plug doesn't drop FORWARD by default.

        Ensures bug 890195 doesn't reappear."""

        def fake_execute(*args, **kwargs):
            return "", ""
        self.stubs.Set(utils, 'execute', fake_execute)

        def verify_add_rule(chain, rule):
            self.assertEqual(chain, 'FORWARD')
            self.assertIn('ACCEPT', rule)
        self.stubs.Set(linux_net.iptables_manager.ipv4['filter'],
                       'add_rule', verify_add_rule)
        driver = linux_net.LinuxBridgeInterfaceDriver()
        driver.plug({"bridge": "br100", "bridge_interface": "eth0"},
                    "fakemac")

    def test_vlan_override(self):
        """Makes sure vlan_interface flag overrides network bridge_interface.

        Allows heterogeneous networks a la bug 833426"""

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        @classmethod
        def test_ensure(_self, vlan, bridge, interface, network, mac_address):
            info['passed_interface'] = interface

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'ensure_vlan_bridge', test_ensure)

        network = {
                "bridge": "br100",
                "bridge_interface": "base_interface",
                "vlan": "fake"
        }
        self.flags(vlan_interface="")
        driver.plug(network, "fakemac")
        self.assertEqual(info['passed_interface'], "base_interface")
        self.flags(vlan_interface="override_interface")
        driver.plug(network, "fakemac")
        self.assertEqual(info['passed_interface'], "override_interface")
        driver.plug(network, "fakemac")

    def test_flat_override(self):
        """Makes sure flat_interface flag overrides network bridge_interface.

        Allows heterogeneous networks a la bug 833426"""

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        @classmethod
        def test_ensure(_self, bridge, interface, network, gateway):
            info['passed_interface'] = interface

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'ensure_bridge', test_ensure)

        network = {
                "bridge": "br100",
                "bridge_interface": "base_interface",
        }
        driver.plug(network, "fakemac")
        self.assertEqual(info['passed_interface'], "base_interface")
        self.flags(flat_interface="override_interface")
        driver.plug(network, "fakemac")
        self.assertEqual(info['passed_interface'], "override_interface")

    def _test_initialize_gateway(self, existing, expected, routes=''):
        self.flags(fake_network=False)
        executes = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            if args[0] == 'ip' and args[1] == 'addr' and args[2] == 'show':
                return existing, ""
            if args[0] == 'ip' and args[1] == 'route' and args[2] == 'show':
                return routes, ""
        self.stubs.Set(utils, 'execute', fake_execute)
        network = {'dhcp_server': '192.168.1.1',
                   'cidr': '192.168.1.0/24',
                   'broadcast': '192.168.1.255',
                   'cidr_v6': '2001:db8::/64'}
        self.driver.initialize_gateway_device('eth0', network)
        self.assertEqual(executes, expected)

    def test_initialize_gateway_moves_wrong_ip(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-w', 'net.ipv4.ip_forward=1'),
            ('ip', 'addr', 'show', 'dev', 'eth0', 'scope', 'global'),
            ('ip', 'route', 'show', 'dev', 'eth0'),
            ('ip', 'addr', 'del', '192.168.0.1/24',
             'brd', '192.168.0.255', 'scope', 'global', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.1.1/24',
             'brd', '192.168.1.255', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.0.1/24',
             'brd', '192.168.0.255', 'scope', 'global', 'dev', 'eth0'),
            ('ip', '-f', 'inet6', 'addr', 'change',
             '2001:db8::/64', 'dev', 'eth0'),
        ]
        self._test_initialize_gateway(existing, expected)

    def test_initialize_gateway_resets_route(self):
        routes = ("default via 192.168.0.1 dev eth0\n"
                  "192.168.100.0/24 via 192.168.0.254 dev eth0 proto static\n")
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-w', 'net.ipv4.ip_forward=1'),
            ('ip', 'addr', 'show', 'dev', 'eth0', 'scope', 'global'),
            ('ip', 'route', 'show', 'dev', 'eth0'),
            ('ip', 'route', 'del', 'default', 'dev', 'eth0'),
            ('ip', 'route', 'del', '192.168.100.0/24', 'dev', 'eth0'),
            ('ip', 'addr', 'del', '192.168.0.1/24',
             'brd', '192.168.0.255', 'scope', 'global', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.1.1/24',
             'brd', '192.168.1.255', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.0.1/24',
             'brd', '192.168.0.255', 'scope', 'global', 'dev', 'eth0'),
            ('ip', 'route', 'add', 'default', 'via', '192.168.0.1',
             'dev', 'eth0'),
            ('ip', 'route', 'add', '192.168.100.0/24', 'via', '192.168.0.254',
             'dev', 'eth0', 'proto', 'static'),
            ('ip', '-f', 'inet6', 'addr', 'change',
             '2001:db8::/64', 'dev', 'eth0'),
        ]
        self._test_initialize_gateway(existing, expected, routes)

    def test_initialize_gateway_no_move_right_ip(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.1.1/24 brd 192.168.1.255 scope global eth0\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-w', 'net.ipv4.ip_forward=1'),
            ('ip', 'addr', 'show', 'dev', 'eth0', 'scope', 'global'),
            ('ip', '-f', 'inet6', 'addr', 'change',
             '2001:db8::/64', 'dev', 'eth0'),
        ]
        self._test_initialize_gateway(existing, expected)

    def test_initialize_gateway_add_if_blank(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-w', 'net.ipv4.ip_forward=1'),
            ('ip', 'addr', 'show', 'dev', 'eth0', 'scope', 'global'),
            ('ip', 'route', 'show', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.1.1/24',
             'brd', '192.168.1.255', 'dev', 'eth0'),
            ('ip', '-f', 'inet6', 'addr', 'change',
             '2001:db8::/64', 'dev', 'eth0'),
        ]
        self._test_initialize_gateway(existing, expected)

    def test_apply_ran(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = False
        self.mox.StubOutWithMock(manager, '_apply')
        manager._apply()
        self.mox.ReplayAll()
        empty_ret = manager.apply()
        self.assertEqual(empty_ret, None)

    def test_apply_not_run(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = True
        self.mox.StubOutWithMock(manager, '_apply')
        self.mox.ReplayAll()
        manager.apply()

    def test_deferred_unset_apply_ran(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = True
        self.mox.StubOutWithMock(manager, '_apply')
        manager._apply()
        self.mox.ReplayAll()
        manager.defer_apply_off()
        self.assertFalse(manager.iptables_apply_deferred)

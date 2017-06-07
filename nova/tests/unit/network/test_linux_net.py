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
import datetime
import os
import re
import time

import mock
import netifaces
from oslo_concurrency import processutils
from oslo_serialization import jsonutils
from oslo_utils import fileutils
from oslo_utils import timeutils

import nova.conf
from nova import context
from nova import db
from nova import exception
from nova.network import driver
from nova.network import linux_net
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests import uuidsentinel as uuids
from nova import utils

CONF = nova.conf.CONF

HOST = "testhost"

instances = {uuids.instance_1:
                 {'id': 0,
                  'uuid': uuids.instance_1,
                  'host': 'fake_instance00',
                  'created_at': datetime.datetime(1955, 11, 5, 0, 0, 0),
                  'updated_at': datetime.datetime(1985, 10, 26, 1, 35, 0),
                  'hostname': 'fake_instance00'},
             uuids.instance_2:
                 {'id': 1,
                  'uuid': uuids.instance_2,
                  'host': 'fake_instance01',
                  'created_at': datetime.datetime(1955, 11, 5, 0, 0, 0),
                  'updated_at': datetime.datetime(1985, 10, 26, 1, 35, 0),
                  'hostname': 'fake_instance01'},
             uuids.instance_3:
                 {'id': 2,
                  'uuid': uuids.instance_3,
                  'host': 'fake_instance02',
                  'created_at': datetime.datetime(1955, 11, 5, 0, 0, 0),
                  'updated_at': datetime.datetime(1985, 10, 26, 1, 35, 0),
                  'hostname': 'really_long_fake_instance02_to_test_hostname_'
                              'truncation_when_too_long'}}


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
             'dhcp_server': '192.168.0.1',
             'dhcp_start': '192.168.100.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2',
             'mtu': None,
             'enable_dhcp': True,
             'share_address': False},
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
             'dhcp_server': '192.168.1.1',
             'dhcp_start': '192.168.100.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.1.2',
             'mtu': None,
             'enable_dhcp': True,
             'share_address': False},
            {'id': 2,
             'uuid': "cccccccc-cccc-cccc-cccc-cccccccccccc",
             'label': 'test2',
             'injected': False,
             'multi_host': True,
             'cidr': '192.168.2.0/24',
             'cidr_v6': '2001:db10::/64',
             'gateway_v6': '2001:db10::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa2',
             'bridge_interface': 'fake_fa2',
             'gateway': '192.168.2.1',
             'broadcast': '192.168.2.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'dhcp_server': '192.168.2.1',
             'dhcp_start': '192.168.100.1',
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.2.2',
             'mtu': None,
             'enable_dhcp': True,
             'share_address': False}]


fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_id': 0,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 0,
              'default_route': True,
              'instance_uuid': uuids.instance_1,
              'floating_ips': []},
             {'id': 1,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_id': 0,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 1,
              'default_route': False,
              'instance_uuid': uuids.instance_1,
              'floating_ips': []},
             {'id': 2,
              'network_id': 1,
              'address': '192.168.0.101',
              'instance_id': 1,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 2,
              'default_route': True,
              'instance_uuid': uuids.instance_2,
              'floating_ips': []},
             {'id': 3,
              'network_id': 0,
              'address': '192.168.1.101',
              'instance_id': 1,
              'allocated': True,
              'leased': True,
              'virtual_interface_id': 3,
              'default_route': False,
              'instance_uuid': uuids.instance_2,
              'floating_ips': []},
             {'id': 4,
              'network_id': 0,
              'address': '192.168.0.102',
              'instance_id': 0,
              'allocated': True,
              'leased': False,
              'virtual_interface_id': 4,
              'default_route': False,
              'instance_uuid': uuids.instance_1,
              'floating_ips': []},
             {'id': 5,
              'network_id': 1,
              'address': '192.168.1.102',
              'instance_id': 1,
              'allocated': True,
              'leased': False,
              'virtual_interface_id': 5,
              'default_route': False,
              'instance_uuid': uuids.instance_2,
              'floating_ips': []},
             {'id': 6,
              'network_id': 1,
              'address': '192.168.1.103',
              'instance_id': 1,
              'allocated': False,
              'leased': True,
              'virtual_interface_id': 6,
              'default_route': False,
              'instance_uuid': uuids.instance_2,
              'floating_ips': []},
             {'id': 7,
              'network_id': 2,
              'address': '192.168.2.100',
              'instance_id': 2,
              'allocated': True,
              'leased': False,
              'virtual_interface_id': 7,
              'default_route': False,
              'instance_uuid': uuids.instance_3,
              'floating_ips': []}]


vifs = [{'id': 0,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'uuid': '00000000-0000-0000-0000-0000000000000000',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 1,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 2,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 3,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:03',
         'uuid': '00000000-0000-0000-0000-0000000000000003',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 4,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:04',
         'uuid': '00000000-0000-0000-0000-0000000000000004',
         'network_id': 0,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000000'},
        {'id': 5,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:05',
         'uuid': '00000000-0000-0000-0000-0000000000000005',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 6,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:06',
         'uuid': '00000000-0000-0000-0000-0000000000000006',
         'network_id': 1,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000001'},
        {'id': 7,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:07',
         'uuid': '00000000-0000-0000-0000-0000000000000007',
         'network_id': 2,
         'instance_uuid': '00000000-0000-0000-0000-0000000000000002'}]


def get_associated(context, network_id, host=None, address=None):
    result = []
    for datum in fixed_ips:
        if (datum['network_id'] == network_id
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
            cleaned['default_route'] = datum['default_route']
            result.append(cleaned)
    return result


class LinuxNetworkUtilsTestCase(test.NoDBTestCase):
    def test_is_pid_cmdline_correct(self):
        # Negative general case
        fake_open = mock.mock_open(read_data='no-such-process')
        with mock.patch.object(linux_net, 'open', fake_open, create=True):
            self.assertFalse(linux_net.is_pid_cmdline_correct(1, "foo"),
                             "foo should not be in 'no-such-process'")

        # Negative case that would be a thing we would want to skip
        fake_open = mock.mock_open(
            read_data=('/usr/sbin/dnsmasq '
                       '--conf-file=/var/run/NetworkManager/dnsmasq.conf'))
        with mock.patch.object(linux_net, 'open', fake_open, create=True):
            self.assertFalse(
                linux_net.is_pid_cmdline_correct(1, "nova-br100.conf"),
                "nova-br100.conf should not have been found")

        # Positive matching case
        fake_open = mock.mock_open(
            read_data=('/usr/sbin/dnsmasq '
                       '--dhcp-hostsfile='
                       '/opt/stack/data/nova/networks/nova-br100.conf'))
        with mock.patch.object(linux_net, 'open', fake_open, create=True):
            self.assertTrue(
                linux_net.is_pid_cmdline_correct(1, "nova-br100.conf"),
                'nova-br100.conf should have been found')

        # Negative case. This would match except we throw an IOError/OSError
        # because the file couldn't be read or opened, this should then fail.
        for err in (IOError, OSError):
            fake_open = mock.mock_open(
                read_data=('/usr/sbin/dnsmasq '
                           '--dhcp-hostsfile='
                           '/opt/stack/data/nova/networks/nova-br100.conf'))
            fake_open.side_effect = err
            with mock.patch.object(linux_net, 'open', fake_open, create=True):
                self.assertFalse(
                    linux_net.is_pid_cmdline_correct(1, "nova-br100.conf"),
                    'nova-br100.conf should not have been found')


class LinuxNetworkTestCase(test.NoDBTestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(LinuxNetworkTestCase, self).setUp()
        self.driver = driver.load_network_driver()
        self.driver.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)

        def get_vifs(_context, instance_uuid, use_slave):
            return [vif for vif in vifs if vif['instance_uuid'] ==
                        instance_uuid]

        def get_instance(_context, instance_id):
            return instances[instance_id]

        self.stub_out('nova.db.virtual_interface_get_by_instance', get_vifs)
        self.stub_out('nova.db.instance_get', get_instance)
        self.stub_out('nova.db.network_get_associated_fixed_ips',
                      get_associated)

    @mock.patch.object(linux_net.iptables_manager.ipv4['nat'], 'add_rule')
    def _test_add_snat_rule(self, expected, is_external, mock_add_rule):

        def verify_add_rule(chain, rule):
            self.assertEqual('snat', chain)
            self.assertEqual(expected, rule)
            self.called = True

        mock_add_rule.side_effect = verify_add_rule

        self.called = False
        linux_net.add_snat_rule('10.0.0.0/24', is_external)
        if expected:
            mock_add_rule.assert_called_once_with('snat', expected)
            self.assertTrue(self.called)

    def test_add_snat_rule_no_ext(self):
        self.flags(routing_source_ip='10.10.10.1')
        expected = ('-s 10.0.0.0/24 -d 0.0.0.0/0 '
                    '-j SNAT --to-source 10.10.10.1 -o eth0')
        self._test_add_snat_rule(expected, False)

    def test_add_snat_rule_ext(self):
        self.flags(routing_source_ip='10.10.10.1')
        expected = ()
        self._test_add_snat_rule(expected, True)

    def test_add_snat_rule_snat_range_no_ext(self):
        self.flags(routing_source_ip='10.10.10.1',
                   force_snat_range=['10.10.10.0/24'])
        expected = ('-s 10.0.0.0/24 -d 0.0.0.0/0 '
                    '-j SNAT --to-source 10.10.10.1 -o eth0')
        self._test_add_snat_rule(expected, False)

    def test_add_snat_rule_snat_range_ext(self):
        self.flags(routing_source_ip='10.10.10.1',
                   force_snat_range=['10.10.10.0/24'])
        expected = ('-s 10.0.0.0/24 -d 10.10.10.0/24 '
                    '-j SNAT --to-source 10.10.10.1')
        self._test_add_snat_rule(expected, True)

    @mock.patch.object(fileutils, 'ensure_tree')
    @mock.patch.object(os, 'chmod')
    def test_update_dhcp_for_nw00(self, mock_chmod, mock_ensure_tree):
        with mock.patch.object(self.driver, 'write_to_file') \
                as mock_write_to_file:
            self.flags(use_single_default_gateway=True)

            self.driver.update_dhcp(self.context, "eth0", networks[0])

            self.assertEqual(mock_write_to_file.call_count, 2)
            self.assertEqual(mock_ensure_tree.call_count, 7)
            self.assertEqual(mock_chmod.call_count, 2)

    @mock.patch.object(fileutils, 'ensure_tree')
    @mock.patch.object(os, 'chmod')
    def test_update_dhcp_for_nw01(self, mock_chmod, mock_ensure_tree):
        with mock.patch.object(self.driver, 'write_to_file') \
                as mock_write_to_file:
            self.flags(use_single_default_gateway=True)

            self.driver.update_dhcp(self.context, "eth0", networks[0])

            self.assertEqual(mock_write_to_file.call_count, 2)
            self.assertEqual(mock_ensure_tree.call_count, 7)
            self.assertEqual(mock_chmod.call_count, 2)

    def _get_fixedips(self, network, host=None):
        return objects.FixedIPList.get_by_network(self.context,
                                                  network,
                                                  host=host)

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
        fixedips = self._get_fixedips(networks[0])
        actual_hosts = self.driver.get_dhcp_hosts(self.context, networks[0],
                                                  fixedips)

        self.assertEqual(expected, actual_hosts)

    def test_get_dhcp_hosts_for_nw01(self):
        self.flags(use_single_default_gateway=True)

        expected = (
                "DE:AD:BE:EF:00:02,fake_instance01.novalocal,"
                "192.168.0.101,net:NW-2\n"
                "DE:AD:BE:EF:00:05,fake_instance01.novalocal,"
                "192.168.1.102,net:NW-5"
        )
        fixedips = self._get_fixedips(networks[1], host='fake_instance01')
        actual_hosts = self.driver.get_dhcp_hosts(self.context, networks[1],
                                                  fixedips)
        self.assertEqual(expected, actual_hosts)

    def test_get_dns_hosts_for_nw00(self):
        expected = (
                "192.168.0.100\tfake_instance00.novalocal\n"
                "192.168.1.101\tfake_instance01.novalocal\n"
                "192.168.0.102\tfake_instance00.novalocal"
        )
        actual_hosts = self.driver.get_dns_hosts(self.context, networks[0])
        self.assertEqual(expected, actual_hosts)

    def test_get_dns_hosts_for_nw01(self):
        expected = (
                "192.168.1.100\tfake_instance00.novalocal\n"
                "192.168.0.101\tfake_instance01.novalocal\n"
                "192.168.1.102\tfake_instance01.novalocal"
        )
        actual_hosts = self.driver.get_dns_hosts(self.context, networks[1])
        self.assertEqual(expected, actual_hosts)

    def test_get_dhcp_opts_for_nw00(self):
        self.flags(use_single_default_gateway=True)
        expected_opts = 'NW-0,3,192.168.0.1\nNW-3,3\nNW-4,3'
        fixedips = self._get_fixedips(networks[0])
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[0],
                                                fixedips)

        self.assertEqual(expected_opts, actual_opts)

    def test_get_dhcp_opts_for_nw00_no_single_default_gateway(self):
        self.flags(use_single_default_gateway=False)
        expected_opts = '3,192.168.0.1'
        fixedips = self._get_fixedips(networks[0])
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[0],
                                                fixedips)

        self.assertEqual(expected_opts, actual_opts)

    def test_get_dhcp_opts_for_nw01(self):
        self.flags(use_single_default_gateway=True)
        expected_opts = "NW-2,3,192.168.1.1\nNW-5,3"
        fixedips = self._get_fixedips(networks[1], 'fake_instance01')
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[1],
                                                fixedips)

        self.assertEqual(expected_opts, actual_opts)

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
            self.assertGreater(int(lease[0]), seconds_since_epoch)
            self.assertEqual(data['vif_address'], lease[1])
            self.assertEqual(data['address'], lease[2])
            self.assertEqual(data['instance_hostname'], lease[3])
            self.assertEqual('*', lease[4])

    def test_get_dhcp_leases_for_nw01(self):
        self.flags(host='fake_instance01')
        timestamp = timeutils.utcnow()
        seconds_since_epoch = calendar.timegm(timestamp.utctimetuple())

        leases = self.driver.get_dhcp_leases(self.context, networks[1])
        leases = leases.split('\n')
        for lease in leases:
            lease = lease.split(' ')
            data = get_associated(self.context, 1, address=lease[2])[0]
            self.assertTrue(data['leased'])
            self.assertGreater(int(lease[0]), seconds_since_epoch)
            self.assertEqual(data['vif_address'], lease[1])
            self.assertEqual(data['address'], lease[2])
            self.assertEqual(data['instance_hostname'], lease[3])
            self.assertEqual('*', lease[4])

    def test_dhcp_opts_not_default_gateway_network(self):
        expected = "NW-0,3"
        fixedip = objects.FixedIPList.get_by_network(self.context,
                                                     {'id': 0})[0]
        actual = self.driver._host_dhcp_opts(fixedip.virtual_interface_id)
        self.assertEqual(expected, actual)

    def test_host_dhcp_without_default_gateway_network(self):
        expected = ','.join(['DE:AD:BE:EF:00:00',
                             'fake_instance00.novalocal',
                             '192.168.0.100'])
        fixedip = objects.FixedIPList.get_by_network(self.context,
                                                     {'id': 0})[0]
        actual = self.driver._host_dhcp(fixedip)
        self.assertEqual(expected, actual)

    def test_host_dhcp_truncated_hostname(self):
        expected = ','.join(['DE:AD:BE:EF:00:07',
                             're-ng_fake_instance02_to_test_hostname_'
                             'truncation_when_too_long.novalocal',
                             '192.168.2.100'])
        fixedip = objects.FixedIPList.get_by_network(self.context,
                                                     {'id': 2})[0]
        actual = self.driver._host_dhcp(fixedip)
        self.assertEqual(expected, actual)

    def test_host_dns_without_default_gateway_network(self):
        expected = "192.168.0.100\tfake_instance00.novalocal"
        fixedip = objects.FixedIPList.get_by_network(self.context,
                                                     {'id': 0})[0]
        actual = self.driver._host_dns(fixedip)
        self.assertEqual(expected, actual)

    @mock.patch.object(linux_net.iptables_manager.ipv4['filter'], 'add_rule')
    @mock.patch.object(utils, 'execute')
    def test_linux_bridge_driver_plug(self, mock_execute, mock_add_rule):
        """Makes sure plug doesn't drop FORWARD by default.

        Ensures bug 890195 doesn't reappear.
        """

        def fake_execute(*args, **kwargs):
            return "", ""

        def verify_add_rule(chain, rule):
            self.assertEqual('FORWARD', chain)
            self.assertIn('ACCEPT', rule)

        mock_execute.side_effect = fake_execute
        mock_add_rule.side_effect = verify_add_rule

        driver = linux_net.LinuxBridgeInterfaceDriver()
        driver.plug({"bridge": "br100", "bridge_interface": "eth0",
                     "share_address": False}, "fakemac")
        self.assertEqual(2, mock_add_rule.call_count)

    @mock.patch.object(linux_net, 'device_exists')
    @mock.patch.object(utils, 'execute')
    def test_linux_ovs_driver_plug_exception(self, mock_execute,
                                             mock_device_exists):
        self.flags(fake_network=False)

        def fake_execute(*args, **kwargs):
            raise processutils.ProcessExecutionError('specific_error')

        def fake_device_exists(*args, **kwargs):
            return False

        mock_execute.side_effect = fake_execute
        mock_device_exists.side_effect = fake_device_exists

        driver = linux_net.LinuxOVSInterfaceDriver()

        exc = self.assertRaises(exception.OvsConfigurationFailure,
                                driver.plug,
                                {'uuid': 'fake_network_uuid'}, 'fake_mac')
        self.assertRegex(
            str(exc),
            re.compile("OVS configuration failed with: .*specific_error.*",
                       re.DOTALL))
        self.assertIsInstance(exc.kwargs['inner_exception'],
                              processutils.ProcessExecutionError)
        mock_execute.assert_called_once()
        mock_device_exists.assert_called_once()

    @mock.patch.object(linux_net.LinuxBridgeInterfaceDriver,
                      'ensure_vlan_bridge')
    def test_vlan_override(self, mock_ensure_vlan_bridge):
        """Makes sure vlan_interface flag overrides network bridge_interface.

        Allows heterogeneous networks a la bug 833426
        """

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        def test_ensure(vlan, bridge, interface, network, mac_address, mtu):
            info['passed_interface'] = interface

        mock_ensure_vlan_bridge.side_effect = test_ensure

        network = {
                "bridge": "br100",
                "bridge_interface": "base_interface",
                "share_address": False,
                "vlan": "fake"
        }
        self.flags(vlan_interface="")
        driver.plug(network, "fakemac")
        self.assertEqual("base_interface", info['passed_interface'])
        self.flags(vlan_interface="override_interface")
        driver.plug(network, "fakemac")
        self.assertEqual("override_interface", info['passed_interface'])
        driver.plug(network, "fakemac")
        self.assertEqual(3, mock_ensure_vlan_bridge.call_count)

    @mock.patch.object(linux_net.LinuxBridgeInterfaceDriver, 'ensure_bridge')
    def test_flat_override(self, mock_ensure_bridge):
        """Makes sure flat_interface flag overrides network bridge_interface.

        Allows heterogeneous networks a la bug 833426
        """

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        def test_ensure(bridge, interface, network, gateway):
            info['passed_interface'] = interface

        mock_ensure_bridge.side_effect = test_ensure

        network = {
                "bridge": "br100",
                "bridge_interface": "base_interface",
                "share_address": False,
        }
        driver.plug(network, "fakemac")
        self.assertEqual("base_interface", info['passed_interface'])
        self.flags(flat_interface="override_interface")
        driver.plug(network, "fakemac")
        self.assertEqual("override_interface", info['passed_interface'])
        self.assertEqual(2, mock_ensure_bridge.call_count)

    @mock.patch.object(linux_net, '_dnsmasq_pid_for')
    @mock.patch.object(linux_net, 'write_to_file')
    @mock.patch('os.chmod')
    @mock.patch.object(linux_net, '_add_dhcp_mangle_rule')
    @mock.patch.object(linux_net, '_execute')
    def _test_dnsmasq_execute(self, mock_execute, mock_add_dhcp_mangle_rule,
                              mock_chmod, mock_write_to_file,
                              mock_dnsmasq_pid_for, extra_expected=None):
        network_ref = {'id': 'fake',
                       'label': 'fake',
                       'gateway': '10.0.0.1',
                       'multi_host': False,
                       'cidr': '10.0.0.0/24',
                       'netmask': '255.255.255.0',
                       'dns1': '8.8.4.4',
                       'dhcp_start': '1.0.0.2',
                       'dhcp_server': '10.0.0.1',
                       'share_address': False}

        def fake_execute(*args, **kwargs):
            executes.append(args)
            return "", ""

        def fake_add_dhcp_mangle_rule(*args, **kwargs):
            executes.append(args)

        mock_execute.side_effect = fake_execute
        mock_add_dhcp_mangle_rule.side_effect = fake_add_dhcp_mangle_rule

        dev = 'br100'

        default_domain = CONF.dhcp_domain
        for domain in ('', default_domain):
            executes = []
            self.flags(dhcp_domain=domain)
            fixedips = self._get_fixedips(network_ref)
            linux_net.restart_dhcp(self.context, dev, network_ref, fixedips)
            expected = ['env',
            'CONFIG_FILE=%s' % jsonutils.dumps(CONF.dhcpbridge_flagfile),
            'NETWORK_ID=fake',
            'dnsmasq',
            '--strict-order',
            '--bind-interfaces',
            '--conf-file=%s' % CONF.dnsmasq_config_file,
            '--pid-file=%s' % linux_net._dhcp_file(dev, 'pid'),
            '--dhcp-optsfile=%s' % linux_net._dhcp_file(dev, 'opts'),
            '--listen-address=%s' % network_ref['dhcp_server'],
            '--except-interface=lo',
            "--dhcp-range=set:%s,%s,static,%s,%ss" % (network_ref['label'],
                                                    network_ref['dhcp_start'],
                                                    network_ref['netmask'],
                                                    CONF.dhcp_lease_time),
            '--dhcp-lease-max=256',
            '--dhcp-hostsfile=%s' % linux_net._dhcp_file(dev, 'conf'),
            '--dhcp-script=%s' % CONF.dhcpbridge,
            '--no-hosts',
            '--leasefile-ro']

            if CONF.dhcp_domain:
                expected.append('--domain=%s' % CONF.dhcp_domain)

            if extra_expected:
                expected += extra_expected
            self.assertEqual([(dev,), tuple(expected)], executes)
        self.assertEqual(2, mock_execute.call_count)
        self.assertEqual(2, mock_add_dhcp_mangle_rule.call_count)
        self.assertEqual(4, mock_chmod.call_count)
        self.assertEqual(2, mock_write_to_file.call_count)
        self.assertEqual(2, mock_dnsmasq_pid_for.call_count)

    def test_dnsmasq_execute(self):
        self._test_dnsmasq_execute()

    def test_dnsmasq_execute_dns_servers(self):
        self.flags(dns_server=['1.1.1.1', '2.2.2.2'])
        expected = [
            '--no-resolv',
            '--server=1.1.1.1',
            '--server=2.2.2.2',
        ]
        self._test_dnsmasq_execute(extra_expected=expected)

    def test_dnsmasq_execute_use_network_dns_servers(self):
        self.flags(use_network_dns_servers=True)
        expected = [
            '--no-resolv',
            '--server=8.8.4.4',
        ]
        self._test_dnsmasq_execute(extra_expected=expected)

    def test_isolated_host(self):
        self.flags(fake_network=False,
                   share_dhcp_address=True)
        executes = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            return "", ""

        driver = linux_net.LinuxBridgeInterfaceDriver()

        def fake_ensure(bridge, interface, network, gateway):
            return bridge

        self.stub_out('nova.network.linux_net.iptables_manager',
                      linux_net.IptablesManager())
        self.stub_out('nova.network.linux_net.binary_name', 'test')
        self.stub_out('nova.utils.execute', fake_execute)
        self.stub_out(
            'nova.network.linux_net.LinuxBridgeInterfaceDriver.ensure_bridge',
            fake_ensure)

        iface = 'eth0'
        dhcp = '192.168.1.1'
        network = {'dhcp_server': dhcp,
                   'share_address': False,
                   'bridge': 'br100',
                   'bridge_interface': iface}
        driver.plug(network, 'fakemac')

        expected = [
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'INPUT', '-p',
             'ARP', '-i', iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-I', 'INPUT', '-p',
             'ARP', '-i', iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'OUTPUT', '-p',
             'ARP', '-o', iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-I', 'OUTPUT', '-p',
             'ARP', '-o', iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'FORWARD',
             '-p', 'IPv4', '-i', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-I', 'FORWARD',
             '-p', 'IPv4', '-i', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'FORWARD',
             '-p', 'IPv4', '-o', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-I', 'FORWARD',
             '-p', 'IPv4', '-o', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
            ('iptables-save', '-c'),
            ('iptables-restore', '-c'),
            ('ip6tables-save', '-c'),
            ('ip6tables-restore', '-c'),
        ]
        self.assertEqual(expected, executes)

        executes = []

        def fake_remove(bridge, gateway):
            return

        self.stub_out(
            'nova.network.linux_net.LinuxBridgeInterfaceDriver.remove_bridge',
            fake_remove)

        driver.unplug(network)
        expected = [
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'INPUT', '-p',
             'ARP', '-i', iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'OUTPUT', '-p',
             'ARP', '-o', iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'FORWARD',
             '-p', 'IPv4', '-i', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
            ('ebtables', '--concurrent', '-t', 'filter', '-D', 'FORWARD',
             '-p', 'IPv4', '-o', iface, '--ip-protocol', 'udp',
             '--ip-destination-port', '67:68', '-j', 'DROP'),
        ]
        self.assertEqual(expected, executes)

    @mock.patch.object(utils, 'execute')
    def _test_initialize_gateway(self, existing, expected, mock_execute,
                                 routes=''):
        self.flags(fake_network=False)
        executes = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            if args[0] == 'ip' and args[1] == 'addr' and args[2] == 'show':
                return existing, ""
            if args[0] == 'ip' and args[1] == 'route' and args[2] == 'show':
                return routes, ""
            if args[0] == 'sysctl':
                return '1\n', ''

        mock_execute.side_effect = fake_execute

        network = {'dhcp_server': '192.168.1.1',
                   'cidr': '192.168.1.0/24',
                   'broadcast': '192.168.1.255',
                   'cidr_v6': '2001:db8::/64'}
        self.driver.initialize_gateway_device('eth0', network)
        self.assertEqual(expected, executes)
        self.assertTrue(mock_execute.called)

    def test_initialize_gateway_moves_wrong_ip(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-n', 'net.ipv4.ip_forward'),
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

    def test_initialize_gateway_ip_with_dynamic_flag(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global "
            "dynamic eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-n', 'net.ipv4.ip_forward'),
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
            ('sysctl', '-n', 'net.ipv4.ip_forward'),
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
        self._test_initialize_gateway(existing, expected, routes=routes)

    def test_initialize_gateway_no_move_right_ip(self):
        existing = ("2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> "
            "    mtu 1500 qdisc pfifo_fast state UNKNOWN qlen 1000\n"
            "    link/ether de:ad:be:ef:be:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.1.1/24 brd 192.168.1.255 scope global eth0\n"
            "    inet 192.168.0.1/24 brd 192.168.0.255 scope global eth0\n"
            "    inet6 dead::beef:dead:beef:dead/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n")
        expected = [
            ('sysctl', '-n', 'net.ipv4.ip_forward'),
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
            ('sysctl', '-n', 'net.ipv4.ip_forward'),
            ('ip', 'addr', 'show', 'dev', 'eth0', 'scope', 'global'),
            ('ip', 'route', 'show', 'dev', 'eth0'),
            ('ip', 'addr', 'add', '192.168.1.1/24',
             'brd', '192.168.1.255', 'dev', 'eth0'),
            ('ip', '-f', 'inet6', 'addr', 'change',
             '2001:db8::/64', 'dev', 'eth0'),
        ]
        self._test_initialize_gateway(existing, expected)

    @mock.patch.object(linux_net, 'ensure_ebtables_rules')
    @mock.patch.object(linux_net.iptables_manager, 'apply')
    def test_ensure_floating_no_duplicate_forwards(self, mock_apply,
                                                   mock_ensure_ebtables_rules):
        ln = linux_net

        mock_apply.side_effect = lambda: None
        mock_ensure_ebtables_rules.side_effect = lambda *a, **kw: None

        net = {'bridge': 'br100', 'cidr': '10.0.0.0/24'}
        ln.ensure_floating_forward('10.10.10.10', '10.0.0.1', 'eth0', net)
        ln.ensure_floating_forward('10.10.10.11', '10.0.0.10', 'eth0', net)
        two_forward_rules = len(linux_net.iptables_manager.ipv4['nat'].rules)
        ln.ensure_floating_forward('10.10.10.10', '10.0.0.3', 'eth0', net)
        dup_forward_rules = len(linux_net.iptables_manager.ipv4['nat'].rules)
        self.assertEqual(two_forward_rules, dup_forward_rules)
        self.assertEqual(3, mock_apply.call_count)
        self.assertEqual(3, mock_ensure_ebtables_rules.call_count)

    def test_apply_ran(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = False
        with mock.patch.object(manager, '_apply') as mock_apply:
            empty_ret = manager.apply()
            mock_apply.assert_called_once()
            self.assertIsNone(empty_ret)

    def test_apply_not_run(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = True
        with mock.patch.object(manager, '_apply') as mock_apply:
            manager.apply()
            mock_apply.assert_not_called()

    def test_deferred_unset_apply_ran(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = True
        with mock.patch.object(manager, '_apply') as mock_apply:
            manager.defer_apply_off()
            mock_apply.assert_called_once()
            self.assertFalse(manager.iptables_apply_deferred)

    @mock.patch.object(linux_net.iptables_manager.ipv4['filter'], 'add_rule')
    def _test_add_metadata_accept_rule(self, expected, mock_add_rule):
        def verify_add_rule(chain, rule):
            self.assertEqual('INPUT', chain)
            self.assertEqual(expected, rule)

        mock_add_rule.side_effect = verify_add_rule
        linux_net.metadata_accept()
        mock_add_rule.assert_called_once()

    @mock.patch.object(linux_net.iptables_manager.ipv6['filter'], 'add_rule')
    def _test_add_metadata_accept_ipv6_rule(self, expected, mock_add_rule):
        def verify_add_rule(chain, rule):
            self.assertEqual('INPUT', chain)
            self.assertEqual(expected, rule)

        mock_add_rule.side_effect = verify_add_rule
        linux_net.metadata_accept()
        mock_add_rule.assert_called_once()

    def test_metadata_accept(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='10.10.10.1')
        expected = ('-p tcp -m tcp --dport 8775 '
                    '-d 10.10.10.1 -j ACCEPT')
        self._test_add_metadata_accept_rule(expected)

    def test_metadata_accept_ipv6(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='2600::')
        expected = ('-p tcp -m tcp --dport 8775 '
                    '-d 2600:: -j ACCEPT')
        self._test_add_metadata_accept_ipv6_rule(expected)

    def test_metadata_accept_localhost(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='127.0.0.1')
        expected = ('-p tcp -m tcp --dport 8775 '
                    '-m addrtype --dst-type LOCAL -j ACCEPT')
        self._test_add_metadata_accept_rule(expected)

    def test_metadata_accept_ipv6_localhost(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='::1')
        expected = ('-p tcp -m tcp --dport 8775 '
                    '-m addrtype --dst-type LOCAL -j ACCEPT')
        self._test_add_metadata_accept_ipv6_rule(expected)

    @mock.patch.object(linux_net.iptables_manager.ipv4['nat'], 'add_rule')
    def _test_add_metadata_forward_rule(self, expected, mock_add_rule):
        def verify_add_rule(chain, rule):
            self.assertEqual('PREROUTING', chain)
            self.assertEqual(expected, rule)

        mock_add_rule.side_effect = verify_add_rule
        linux_net.metadata_forward()
        mock_add_rule.assert_called_once()

    def test_metadata_forward(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='10.10.10.1')
        expected = ('-s 0.0.0.0/0 -d 169.254.169.254/32 -p tcp -m tcp '
                    '--dport 80 -j DNAT --to-destination 10.10.10.1:8775')
        self._test_add_metadata_forward_rule(expected)

    def test_metadata_forward_localhost(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='127.0.0.1')
        expected = ('-s 0.0.0.0/0 -d 169.254.169.254/32 -p tcp -m tcp '
                    '--dport 80 -j REDIRECT --to-ports 8775')
        self._test_add_metadata_forward_rule(expected)

    def test_ensure_bridge_brings_up_interface(self):
        # We have to bypass the CONF.fake_network check so that netifaces
        # is actually called.
        self.flags(fake_network=False)
        fake_mac = 'aa:bb:cc:00:11:22'
        fake_ifaces = {
            netifaces.AF_LINK: [{'addr': fake_mac}]
        }
        calls = {
            'device_exists': [mock.call('bridge')],
            '_execute': [
                mock.call('brctl', 'addif', 'bridge', 'eth0',
                          run_as_root=True, check_exit_code=False),
                mock.call('ip', 'link', 'set', 'bridge', 'address', fake_mac,
                          run_as_root=True),
                mock.call('ip', 'link', 'set', 'eth0', 'up',
                          run_as_root=True, check_exit_code=False),
                mock.call('ip', 'route', 'show', 'dev', 'eth0'),
                mock.call('ip', 'addr', 'show', 'dev', 'eth0', 'scope',
                          'global'),
                ]
            }
        with test.nested(
            mock.patch.object(linux_net, 'device_exists', return_value=True),
            mock.patch.object(linux_net, '_execute', return_value=('', '')),
            mock.patch.object(netifaces, 'ifaddresses')
        ) as (device_exists, _execute, ifaddresses):
            ifaddresses.return_value = fake_ifaces
            driver = linux_net.LinuxBridgeInterfaceDriver()
            driver.ensure_bridge('bridge', 'eth0')
            device_exists.assert_has_calls(calls['device_exists'])
            _execute.assert_has_calls(calls['_execute'])
            ifaddresses.assert_called_once_with('eth0')

    def test_ensure_bridge_brclt_addif_exception(self):
        def fake_execute(*cmd, **kwargs):
            if ('brctl', 'addif', 'bridge', 'eth0') == cmd:
                return ('', 'some error happens')
            else:
                return ('', '')

        with test.nested(
            mock.patch.object(linux_net, 'device_exists', return_value=True),
            mock.patch.object(linux_net, '_execute', fake_execute)
        ) as (device_exists, _):
            driver = linux_net.LinuxBridgeInterfaceDriver()
            self.assertRaises(exception.NovaException,
                              driver.ensure_bridge, 'bridge', 'eth0')
            device_exists.assert_called_once_with('bridge')

    def test_ensure_bridge_brclt_addbr_neutron_race(self):
        def fake_execute(*cmd, **kwargs):
            if ('brctl', 'addbr', 'brq1234567-89') == cmd:
                return ('', "device brq1234567-89 already exists; "
                            "can't create bridge with the same name\n")
            else:
                return ('', '')

        with test.nested(
            mock.patch.object(linux_net, 'device_exists', return_value=False),
            mock.patch.object(linux_net, '_execute', fake_execute)
        ) as (device_exists, _):
            driver = linux_net.LinuxBridgeInterfaceDriver()
            driver.ensure_bridge('brq1234567-89', '')
            device_exists.assert_called_once_with('brq1234567-89')

    def test_set_device_mtu_default(self):
        calls = []
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net._set_device_mtu('fake-dev')
            ex.assert_has_calls(calls)

    def _ovs_vif_port(self, calls, interface_type=None):
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net.create_ovs_vif_port('fake-bridge', 'fake-dev',
                                          'fake-iface-id', 'fake-mac',
                                          'fake-instance-uuid',
                                          interface_type=interface_type)
            ex.assert_has_calls(calls)

    def test_ovs_vif_port_cmd(self):
        expected = ['--', '--if-exists',
                    'del-port', 'fake-dev', '--', 'add-port',
                    'fake-bridge', 'fake-dev',
                    '--', 'set', 'Interface', 'fake-dev',
                    'external-ids:iface-id=fake-iface-id',
                    'external-ids:iface-status=active',
                    'external-ids:attached-mac=fake-mac',
                    'external-ids:vm-uuid=fake-instance-uuid'
                ]
        cmd = linux_net._create_ovs_vif_cmd('fake-bridge', 'fake-dev',
                                            'fake-iface-id', 'fake-mac',
                                            'fake-instance-uuid')

        self.assertEqual(expected, cmd)

        expected += ['type=fake-type']
        cmd = linux_net._create_ovs_vif_cmd('fake-bridge', 'fake-dev',
                                            'fake-iface-id', 'fake-mac',
                                            'fake-instance-uuid',
                                            'fake-type')
        self.assertEqual(expected, cmd)

    def test_ovs_vif_port(self):
        calls = [
                mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                          'del-port', 'fake-dev', '--', 'add-port',
                          'fake-bridge', 'fake-dev',
                          '--', 'set', 'Interface', 'fake-dev',
                          'external-ids:iface-id=fake-iface-id',
                          'external-ids:iface-status=active',
                          'external-ids:attached-mac=fake-mac',
                          'external-ids:vm-uuid=fake-instance-uuid',
                          run_as_root=True)
                ]
        self._ovs_vif_port(calls)

    @mock.patch.object(linux_net, '_ovs_vsctl')
    @mock.patch.object(linux_net, '_create_ovs_vif_cmd')
    @mock.patch.object(linux_net, '_set_device_mtu')
    def test_ovs_vif_port_with_type_vhostuser(self, mock_set_device_mtu,
                                              mock_create_cmd, mock_vsctl):
        linux_net.create_ovs_vif_port(
            'fake-bridge',
            'fake-dev', 'fake-iface-id', 'fake-mac',
            "fake-instance-uuid", mtu=1500,
            interface_type=network_model.OVS_VHOSTUSER_INTERFACE_TYPE)
        mock_create_cmd.assert_called_once_with('fake-bridge',
            'fake-dev', 'fake-iface-id', 'fake-mac',
            "fake-instance-uuid", network_model.OVS_VHOSTUSER_INTERFACE_TYPE)
        self.assertFalse(mock_set_device_mtu.called)
        self.assertTrue(mock_vsctl.called)

    def _create_veth_pair(self, calls):
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net._create_veth_pair('fake-dev1', 'fake-dev2')
            ex.assert_has_calls(calls)

    def test_create_veth_pair(self):
        calls = [
            mock.call('ip', 'link', 'add', 'fake-dev1', 'type', 'veth',
                      'peer', 'name', 'fake-dev2', run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'promisc', 'on',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'promisc', 'on',
                      run_as_root=True)
        ]
        self._create_veth_pair(calls)

    def test_exec_ebtables_success(self):
        executes = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            return "", ""

        with mock.patch.object(self.driver, '_execute',
                               side_effect=fake_execute):
            self.driver._exec_ebtables('fake')
            self.assertEqual(1, len(executes))

    def _ebtables_race_stderr(self):
        return (u"Unable to update the kernel. Two possible causes:\n"
                "1. Multiple ebtables programs were executing simultaneously."
                " The ebtables\n userspace tool doesn't by default support "
                "multiple ebtables programs running\n concurrently. The "
                "ebtables option --concurrent or a tool like flock can be\n "
                "used to support concurrent scripts that update the ebtables "
                "kernel tables.\n2. The kernel doesn't support a certain "
                "ebtables extension, consider\n recompiling your kernel or "
                "insmod the extension.\n.\n")

    def test_exec_ebtables_fail_all(self):
        executes = []

        def fake_sleep(interval):
            pass

        def fake_execute(*args, **kwargs):
            executes.append(args)
            raise processutils.ProcessExecutionError('error',
                    stderr=self._ebtables_race_stderr())

        with mock.patch.object(time, 'sleep', side_effect=fake_sleep), \
                mock.patch.object(self.driver, '_execute',
                                  side_effect=fake_execute):
            self.assertRaises(processutils.ProcessExecutionError,
                              self.driver._exec_ebtables, 'fake')
            max_calls = CONF.ebtables_exec_attempts
            self.assertEqual(max_calls, len(executes))

    def test_exec_ebtables_fail_no_retry(self):
        executes = []

        def fake_sleep(interval):
            pass

        def fake_execute(*args, **kwargs):
            executes.append(args)
            raise processutils.ProcessExecutionError('error',
                    stderr="Sorry, rule does not exist")

        with mock.patch.object(time, 'sleep', side_effect=fake_sleep), \
                mock.patch.object(self.driver, '_execute',
                              side_effect=fake_execute):
            self.assertRaises(processutils.ProcessExecutionError,
                              self.driver._exec_ebtables, 'fake')
            self.assertEqual(1, len(executes))

    def test_exec_ebtables_fail_once(self):
        executes = []

        def fake_sleep(interval):
            pass

        def fake_execute(*args, **kwargs):
            executes.append(args)
            if len(executes) == 1:
                raise processutils.ProcessExecutionError('error',
                        stderr=self._ebtables_race_stderr())
            else:
                return "", ""

        with mock.patch.object(time, 'sleep', side_effect=fake_sleep), \
                mock.patch.object(self.driver, '_execute',
                                  side_effect=fake_execute):
            self.driver._exec_ebtables('fake')
            self.assertEqual(2, len(executes))

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_remove_bridge(self, mock_execute, mock_exists):
        linux_net.LinuxBridgeInterfaceDriver.remove_bridge('fake-bridge')
        expected_exists_args = mock.call('/sys/class/net/fake-bridge')
        expected_execute_args = [
            mock.call('ip', 'link', 'set', 'fake-bridge', 'down',
                      run_as_root=True),
            mock.call('brctl', 'delbr', 'fake-bridge', run_as_root=True)]

        self.assertIn(expected_exists_args, mock_exists.mock_calls)
        self.assertEqual(expected_execute_args, mock_execute.mock_calls)

    @mock.patch.object(linux_net, '_execute')
    @mock.patch.object(linux_net, 'device_exists', return_value=False)
    @mock.patch.object(linux_net, '_set_device_mtu')
    def test_ensure_vlan(self, mock_set_device_mtu, mock_device_exists,
                         mock_execute):
        interface = linux_net.LinuxBridgeInterfaceDriver.ensure_vlan(
                        1, 'eth0', 'MAC', 'MTU', "vlan_name")
        self.assertEqual("vlan_name", interface)
        mock_device_exists.assert_called_once_with('vlan_name')

        expected_execute_args = [
            mock.call('ip', 'link', 'add', 'link', 'eth0', 'name', 'vlan_name',
                      'type', 'vlan', 'id', 1, check_exit_code=[0, 2, 254],
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'vlan_name', 'address', 'MAC',
                       check_exit_code=[0, 2, 254], run_as_root=True),
            mock.call('ip', 'link', 'set', 'vlan_name', 'up',
                      check_exit_code=[0, 2, 254], run_as_root=True)]
        self.assertEqual(expected_execute_args, mock_execute.mock_calls)
        mock_set_device_mtu.assert_called_once_with('vlan_name', 'MTU')

    @mock.patch.object(linux_net, '_execute')
    @mock.patch.object(linux_net, 'device_exists', return_value=True)
    @mock.patch.object(linux_net, '_set_device_mtu')
    def test_ensure_vlan_device_exists(self, mock_set_device_mtu,
                                       mock_device_exists, mock_execute):
        interface = linux_net.LinuxBridgeInterfaceDriver.ensure_vlan(1, 'eth0')
        self.assertEqual("vlan1", interface)
        mock_device_exists.assert_called_once_with('vlan1')
        self.assertFalse(mock_execute.called)
        mock_set_device_mtu.assert_called_once_with('vlan1', None)

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute',
                side_effect=processutils.ProcessExecutionError())
    def test_remove_bridge_negative(self, mock_execute, mock_exists):
        self.assertRaises(processutils.ProcessExecutionError,
                          linux_net.LinuxBridgeInterfaceDriver.remove_bridge,
                          'fake-bridge')

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev(self, mock_execute):
        linux_net.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('os.path.exists', return_value=True)
    @mock.patch('nova.utils.execute')
    def test_create_tap_skipped_when_exists(self, mock_execute, mock_exists):
        linux_net.create_tap_dev('tap42')

        mock_exists.assert_called_once_with('/sys/class/net/tap42')
        mock_execute.assert_not_called()

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_mac(self, mock_execute):
        linux_net.create_tap_dev('tap42', '00:11:22:33:44:55')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42',
                      'address', '00:11:22:33:44:55',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_fallback_to_tunctl(self, mock_execute):
        # ip failed, fall back to tunctl
        mock_execute.side_effect = [processutils.ProcessExecutionError, 0, 0]

        linux_net.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('tunctl', '-b', '-t', 'tap42',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_multiqueue(self, mock_execute):
        linux_net.create_tap_dev('tap42', multiqueue=True)

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      'multi_queue',
                      run_as_root=True, check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'tap42', 'up',
                      run_as_root=True, check_exit_code=[0, 2, 254])
        ])

    @mock.patch('nova.utils.execute')
    def test_create_tap_dev_multiqueue_tunctl_raises(self, mock_execute):
        # if creation of a tap by the means of ip command fails,
        # create_tap_dev() will try to do that by the means of tunctl
        mock_execute.side_effect = processutils.ProcessExecutionError
        # but tunctl can't create multiqueue taps, so the failure is expected
        self.assertRaises(processutils.ProcessExecutionError,
                          linux_net.create_tap_dev,
                          'tap42', multiqueue=True)

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
import contextlib
import datetime
import os

import mock
import mox
from oslo.config import cfg

from nova import context
from nova import db
from nova import exception
from nova.network import driver
from nova.network import linux_net
from nova.objects import fixed_ip as fixed_ip_obj
from nova.openstack.common import fileutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.openstack.common import timeutils
from nova import test
from nova import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

HOST = "testhost"

instances = {'00000000-0000-0000-0000-0000000000000000':
                 {'id': 0,
                  'uuid': '00000000-0000-0000-0000-0000000000000000',
                  'host': 'fake_instance00',
                  'created_at': datetime.datetime(1955, 11, 5, 0, 0, 0),
                  'updated_at': datetime.datetime(1985, 10, 26, 1, 35, 0),
                  'hostname': 'fake_instance00'},
             '00000000-0000-0000-0000-0000000000000001':
                 {'id': 1,
                  'uuid': '00000000-0000-0000-0000-0000000000000001',
                  'host': 'fake_instance01',
                  'created_at': datetime.datetime(1955, 11, 5, 0, 0, 0),
                  'updated_at': datetime.datetime(1985, 10, 26, 1, 35, 0),
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


class LinuxNetworkTestCase(test.NoDBTestCase):

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

        self.stubs.Set(db, 'virtual_interface_get_by_instance', get_vifs)
        self.stubs.Set(db, 'instance_get', get_instance)
        self.stubs.Set(db, 'network_get_associated_fixed_ips', get_associated)

    def _test_add_snat_rule(self, expected):
        def verify_add_rule(chain, rule):
            self.assertEqual(chain, 'snat')
            self.assertEqual(rule, expected)

        self.stubs.Set(linux_net.iptables_manager.ipv4['nat'],
                       'add_rule', verify_add_rule)
        linux_net.add_snat_rule('10.0.0.0/24')

    def test_add_snat_rule(self):
        self.flags(routing_source_ip='10.10.10.1')
        expected = ('-s 10.0.0.0/24 -d 0.0.0.0/0 '
                    '-j SNAT --to-source 10.10.10.1 -o eth0')
        self._test_add_snat_rule(expected)

    def test_add_snat_rule_snat_range(self):
        self.flags(routing_source_ip='10.10.10.1',
                   force_snat_range=['10.10.10.0/24'])
        expected = ('-s 10.0.0.0/24 -d 10.10.10.0/24 '
                    '-j SNAT --to-source 10.10.10.1 -o eth0')
        self._test_add_snat_rule(expected)

    def test_update_dhcp_for_nw00(self):
        self.flags(use_single_default_gateway=True)

        self.mox.StubOutWithMock(self.driver, 'write_to_file')
        self.mox.StubOutWithMock(fileutils, 'ensure_tree')
        self.mox.StubOutWithMock(os, 'chmod')

        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())
        os.chmod(mox.IgnoreArg(), mox.IgnoreArg())

        self.mox.ReplayAll()

        self.driver.update_dhcp(self.context, "eth0", networks[0])

    def test_update_dhcp_for_nw01(self):
        self.flags(use_single_default_gateway=True)

        self.mox.StubOutWithMock(self.driver, 'write_to_file')
        self.mox.StubOutWithMock(fileutils, 'ensure_tree')
        self.mox.StubOutWithMock(os, 'chmod')

        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        self.driver.write_to_file(mox.IgnoreArg(), mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
        fileutils.ensure_tree(mox.IgnoreArg())
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

        self.assertEqual(actual_hosts, expected)

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
        self.assertEqual(actual_hosts, expected)

    def test_get_dns_hosts_for_nw00(self):
        expected = (
                "192.168.0.100\tfake_instance00.novalocal\n"
                "192.168.1.101\tfake_instance01.novalocal\n"
                "192.168.0.102\tfake_instance00.novalocal"
        )
        actual_hosts = self.driver.get_dns_hosts(self.context, networks[0])
        self.assertEqual(actual_hosts, expected)

    def test_get_dns_hosts_for_nw01(self):
        expected = (
                "192.168.1.100\tfake_instance00.novalocal\n"
                "192.168.0.101\tfake_instance01.novalocal\n"
                "192.168.1.102\tfake_instance01.novalocal"
        )
        actual_hosts = self.driver.get_dns_hosts(self.context, networks[1])
        self.assertEqual(actual_hosts, expected)

    def test_get_dhcp_opts_for_nw00(self):
        expected_opts = 'NW-3,3\nNW-4,3'
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[0])

        self.assertEqual(actual_opts, expected_opts)

    def test_get_dhcp_opts_for_nw01(self):
        self.flags(host='fake_instance01')
        expected_opts = "NW-5,3"
        actual_opts = self.driver.get_dhcp_opts(self.context, networks[1])

        self.assertEqual(actual_opts, expected_opts)

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
        fixedip = fixed_ip_obj.FixedIPList.get_by_network(self.context,
                                                          {'id': 0})[0]
        actual = self.driver._host_dhcp_opts(fixedip)
        self.assertEqual(actual, expected)

    def test_host_dhcp_without_default_gateway_network(self):
        expected = ','.join(['DE:AD:BE:EF:00:00',
                             'fake_instance00.novalocal',
                             '192.168.0.100'])
        fixedip = fixed_ip_obj.FixedIPList.get_by_network(self.context,
                                                          {'id': 0})[0]
        actual = self.driver._host_dhcp(fixedip)
        self.assertEqual(actual, expected)

    def test_host_dns_without_default_gateway_network(self):
        expected = "192.168.0.100\tfake_instance00.novalocal"
        fixedip = fixed_ip_obj.FixedIPList.get_by_network(self.context,
                                                          {'id': 0})[0]
        actual = self.driver._host_dns(fixedip)
        self.assertEqual(actual, expected)

    def test_linux_bridge_driver_plug(self):
        """Makes sure plug doesn't drop FORWARD by default.

        Ensures bug 890195 doesn't reappear.
        """

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

    def test_linux_ovs_driver_plug_exception(self):
        self.flags(fake_network=False)

        def fake_execute(*args, **kwargs):
            raise processutils.ProcessExecutionError('error')

        def fake_device_exists(*args, **kwargs):
            return False

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(linux_net, 'device_exists', fake_device_exists)
        driver = linux_net.LinuxOVSInterfaceDriver()
        self.assertRaises(exception.AgentError,
                          driver.plug, {'uuid': 'fake_network_uuid'},
                          'fake_mac')

    def test_vlan_override(self):
        """Makes sure vlan_interface flag overrides network bridge_interface.

        Allows heterogeneous networks a la bug 833426
        """

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        @staticmethod
        def test_ensure(vlan, bridge, interface, network, mac_address):
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

        Allows heterogeneous networks a la bug 833426
        """

        driver = linux_net.LinuxBridgeInterfaceDriver()

        info = {}

        @staticmethod
        def test_ensure(bridge, interface, network, gateway):
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

    def _test_dnsmasq_execute(self, extra_expected=None):
        network_ref = {'id': 'fake',
                       'label': 'fake',
                       'multi_host': False,
                       'cidr': '10.0.0.0/24',
                       'netmask': '255.255.255.0',
                       'dns1': '8.8.4.4',
                       'dhcp_start': '1.0.0.2',
                       'dhcp_server': '10.0.0.1'}

        def fake_execute(*args, **kwargs):
            executes.append(args)
            return "", ""

        def fake_add_dhcp_mangle_rule(*args, **kwargs):
            executes.append(args)

        self.stubs.Set(linux_net, '_execute', fake_execute)
        self.stubs.Set(linux_net, '_add_dhcp_mangle_rule',
                       fake_add_dhcp_mangle_rule)

        self.stubs.Set(os, 'chmod', lambda *a, **kw: None)
        self.stubs.Set(linux_net, 'write_to_file', lambda *a, **kw: None)
        self.stubs.Set(linux_net, '_dnsmasq_pid_for', lambda *a, **kw: None)
        dev = 'br100'

        default_domain = CONF.dhcp_domain
        for domain in ('', default_domain):
            executes = []
            CONF.dhcp_domain = domain
            linux_net.restart_dhcp(self.context, dev, network_ref)
            expected = ['env',
            'CONFIG_FILE=%s' % jsonutils.dumps(CONF.dhcpbridge_flagfile),
            'NETWORK_ID=fake',
            'dnsmasq',
            '--strict-order',
            '--bind-interfaces',
            '--conf-file=%s' % CONF.dnsmasq_config_file,
            '--pid-file=%s' % linux_net._dhcp_file(dev, 'pid'),
            '--listen-address=%s' % network_ref['dhcp_server'],
            '--except-interface=lo',
            "--dhcp-range=set:%s,%s,static,%s,%ss" % (network_ref['label'],
                                                    network_ref['dhcp_start'],
                                                    network_ref['netmask'],
                                                    CONF.dhcp_lease_time),
            '--dhcp-lease-max=256',
            '--dhcp-hostsfile=%s' % linux_net._dhcp_file(dev, 'conf'),
            '--dhcp-script=%s' % CONF.dhcpbridge,
            '--leasefile-ro']

            if CONF.dhcp_domain:
                expected.append('--domain=%s' % CONF.dhcp_domain)

            if extra_expected:
                expected += extra_expected
            self.assertEqual([(dev,), tuple(expected)], executes)

    def test_dnsmasq_execute(self):
        self._test_dnsmasq_execute()

    def test_dnsmasq_execute_dns_servers(self):
        self.flags(dns_server=['1.1.1.1', '2.2.2.2'])
        expected = [
            '--no-hosts',
            '--no-resolv',
            '--server=1.1.1.1',
            '--server=2.2.2.2',
        ]
        self._test_dnsmasq_execute(expected)

    def test_dnsmasq_execute_use_network_dns_servers(self):
        self.flags(use_network_dns_servers=True)
        expected = [
            '--no-hosts',
            '--no-resolv',
            '--server=8.8.4.4',
        ]
        self._test_dnsmasq_execute(expected)

    def test_isolated_host(self):
        self.flags(fake_network=False,
                   share_dhcp_address=True)
        # NOTE(vish): use a fresh copy of the manager for each test
        self.stubs.Set(linux_net, 'iptables_manager',
                       linux_net.IptablesManager())
        self.stubs.Set(linux_net, 'binary_name', 'test')
        executes = []
        inputs = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            process_input = kwargs.get('process_input')
            if process_input:
                inputs.append(process_input)
            return "", ""

        self.stubs.Set(utils, 'execute', fake_execute)

        driver = linux_net.LinuxBridgeInterfaceDriver()

        @staticmethod
        def fake_ensure(bridge, interface, network, gateway):
            return bridge

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'ensure_bridge', fake_ensure)

        iface = 'eth0'
        dhcp = '192.168.1.1'
        network = {'dhcp_server': dhcp,
                   'bridge': 'br100',
                   'bridge_interface': iface}
        driver.plug(network, 'fakemac')
        expected = [
            ('ebtables', '-t', 'filter', '-D', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-I', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-D', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-I', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('iptables-save', '-c'),
            ('iptables-restore', '-c'),
            ('ip6tables-save', '-c'),
            ('ip6tables-restore', '-c'),
        ]
        self.assertEqual(executes, expected)
        expected_inputs = [
             '-A test-FORWARD -m physdev --physdev-in %s '
             '-d 255.255.255.255 -p udp --dport 67 -j DROP' % iface,
             '-A test-FORWARD -m physdev --physdev-out %s '
             '-d 255.255.255.255 -p udp --dport 67 -j DROP' % iface,
             '-A test-FORWARD -m physdev --physdev-in %s '
             '-d 192.168.1.1 -j DROP' % iface,
             '-A test-FORWARD -m physdev --physdev-out %s '
             '-s 192.168.1.1 -j DROP' % iface,
        ]
        for inp in expected_inputs:
            self.assertIn(inp, inputs[0])

        executes = []
        inputs = []

        @staticmethod
        def fake_remove(bridge, gateway):
            return

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'remove_bridge', fake_remove)

        driver.unplug(network)
        expected = [
            ('ebtables', '-t', 'filter', '-D', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-D', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('iptables-save', '-c'),
            ('iptables-restore', '-c'),
            ('ip6tables-save', '-c'),
            ('ip6tables-restore', '-c'),
        ]
        self.assertEqual(executes, expected)
        for inp in expected_inputs:
            self.assertNotIn(inp, inputs[0])

    def test_isolated_host_iptables_logdrop(self):
        # Ensure that a different drop action for iptables doesn't change
        # the drop action for ebtables.
        self.flags(fake_network=False,
                   share_dhcp_address=True,
                   iptables_drop_action='LOGDROP')

        # NOTE(vish): use a fresh copy of the manager for each test
        self.stubs.Set(linux_net, 'iptables_manager',
                       linux_net.IptablesManager())
        self.stubs.Set(linux_net, 'binary_name', 'test')
        executes = []
        inputs = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            process_input = kwargs.get('process_input')
            if process_input:
                inputs.append(process_input)
            return "", ""

        self.stubs.Set(utils, 'execute', fake_execute)

        driver = linux_net.LinuxBridgeInterfaceDriver()

        @staticmethod
        def fake_ensure(bridge, interface, network, gateway):
            return bridge

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'ensure_bridge', fake_ensure)

        iface = 'eth0'
        dhcp = '192.168.1.1'
        network = {'dhcp_server': dhcp,
                   'bridge': 'br100',
                   'bridge_interface': iface}
        driver.plug(network, 'fakemac')
        expected = [
            ('ebtables', '-t', 'filter', '-D', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-I', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-D', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-I', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('iptables-save', '-c'),
            ('iptables-restore', '-c'),
            ('ip6tables-save', '-c'),
            ('ip6tables-restore', '-c'),
        ]
        self.assertEqual(executes, expected)
        expected_inputs = [
             ('-A test-FORWARD -m physdev --physdev-in %s '
              '-d 255.255.255.255 -p udp --dport 67 -j LOGDROP' % iface),
             ('-A test-FORWARD -m physdev --physdev-out %s '
              '-d 255.255.255.255 -p udp --dport 67 -j LOGDROP' % iface),
             ('-A test-FORWARD -m physdev --physdev-in %s '
              '-d 192.168.1.1 -j LOGDROP' % iface),
             ('-A test-FORWARD -m physdev --physdev-out %s '
              '-s 192.168.1.1 -j LOGDROP' % iface),
        ]
        for inp in expected_inputs:
            self.assertIn(inp, inputs[0])

        executes = []
        inputs = []

        @staticmethod
        def fake_remove(bridge, gateway):
            return

        self.stubs.Set(linux_net.LinuxBridgeInterfaceDriver,
                       'remove_bridge', fake_remove)

        driver.unplug(network)
        expected = [
            ('ebtables', '-t', 'filter', '-D', 'INPUT', '-p', 'ARP', '-i',
             iface, '--arp-ip-dst', dhcp, '-j', 'DROP'),
            ('ebtables', '-t', 'filter', '-D', 'OUTPUT', '-p', 'ARP', '-o',
             iface, '--arp-ip-src', dhcp, '-j', 'DROP'),
            ('iptables-save', '-c'),
            ('iptables-restore', '-c'),
            ('ip6tables-save', '-c'),
            ('ip6tables-restore', '-c'),
        ]
        self.assertEqual(executes, expected)
        for inp in expected_inputs:
            self.assertNotIn(inp, inputs[0])

    def _test_initialize_gateway(self, existing, expected, routes=''):
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

    def test_ensure_floating_no_duplicate_forwards(self):
        ln = linux_net
        self.stubs.Set(ln.iptables_manager, 'apply', lambda: None)
        self.stubs.Set(ln, 'ensure_ebtables_rules', lambda *a, **kw: None)
        net = {'bridge': 'br100', 'cidr': '10.0.0.0/24'}
        ln.ensure_floating_forward('10.10.10.10', '10.0.0.1', 'eth0', net)
        ln.ensure_floating_forward('10.10.10.11', '10.0.0.10', 'eth0', net)
        two_forward_rules = len(linux_net.iptables_manager.ipv4['nat'].rules)
        ln.ensure_floating_forward('10.10.10.10', '10.0.0.3', 'eth0', net)
        dup_forward_rules = len(linux_net.iptables_manager.ipv4['nat'].rules)
        self.assertEqual(two_forward_rules, dup_forward_rules)

    def test_apply_ran(self):
        manager = linux_net.IptablesManager()
        manager.iptables_apply_deferred = False
        self.mox.StubOutWithMock(manager, '_apply')
        manager._apply()
        self.mox.ReplayAll()
        empty_ret = manager.apply()
        self.assertIsNone(empty_ret)

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

    def _test_add_metadata_accept_rule(self, expected):
        def verify_add_rule(chain, rule):
            self.assertEqual(chain, 'INPUT')
            self.assertEqual(expected, rule)

        self.stubs.Set(linux_net.iptables_manager.ipv4['filter'],
                       'add_rule', verify_add_rule)
        linux_net.metadata_accept()

    def test_metadata_accept(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='10.10.10.1')
        expected = ('-s 0.0.0.0/0 -p tcp -m tcp --dport 8775 '
                    '-d 10.10.10.1 -j ACCEPT')
        self._test_add_metadata_accept_rule(expected)

    def test_metadata_accept_localhost(self):
        self.flags(metadata_port='8775')
        self.flags(metadata_host='127.0.0.1')
        expected = ('-s 0.0.0.0/0 -p tcp -m tcp --dport 8775 '
                    '-m addrtype --dst-type LOCAL -j ACCEPT')
        self._test_add_metadata_accept_rule(expected)

    def _test_add_metadata_forward_rule(self, expected):
        def verify_add_rule(chain, rule):
            self.assertEqual(chain, 'PREROUTING')
            self.assertEqual(expected, rule)

        self.stubs.Set(linux_net.iptables_manager.ipv4['nat'],
                       'add_rule', verify_add_rule)
        linux_net.metadata_forward()

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
        calls = {
            'device_exists': [mock.call('bridge')],
            '_execute': [
                mock.call('brctl', 'addif', 'bridge', 'eth0',
                          run_as_root=True, check_exit_code=False),
                mock.call('ip', 'link', 'set', 'eth0', 'up',
                          run_as_root=True, check_exit_code=False),
                mock.call('ip', 'route', 'show', 'dev', 'eth0'),
                mock.call('ip', 'addr', 'show', 'dev', 'eth0', 'scope',
                          'global'),
                ]
            }
        with contextlib.nested(
            mock.patch.object(linux_net, 'device_exists', return_value=True),
            mock.patch.object(linux_net, '_execute', return_value=('', ''))
        ) as (device_exists, _execute):
            driver = linux_net.LinuxBridgeInterfaceDriver()
            driver.ensure_bridge('bridge', 'eth0')
            device_exists.assert_has_calls(calls['device_exists'])
            _execute.assert_has_calls(calls['_execute'])

    def test_ensure_bridge_brclt_addif_exception(self):
        def fake_execute(*cmd, **kwargs):
            if ('brctl', 'addif', 'bridge', 'eth0') == cmd:
                return ('', 'some error happens')
            else:
                return ('', '')

        with contextlib.nested(
            mock.patch.object(linux_net, 'device_exists', return_value=True),
            mock.patch.object(linux_net, '_execute', fake_execute)
        ) as (device_exists, _execute):
            driver = linux_net.LinuxBridgeInterfaceDriver()
            self.assertRaises(exception.NovaException,
                              driver.ensure_bridge, 'bridge', 'eth0')

    def test_set_device_mtu_configured(self):
        self.flags(network_device_mtu=10000)
        calls = [
                mock.call('ip', 'link', 'set', 'fake-dev', 'mtu',
                          10000, run_as_root=True,
                          check_exit_code=[0, 2, 254])
                ]
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net._set_device_mtu('fake-dev')
            ex.assert_has_calls(calls)

    def test_set_device_mtu_default(self):
        calls = []
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net._set_device_mtu('fake-dev')
            ex.assert_has_calls(calls)

    def _ovs_vif_port(self, calls):
        with mock.patch.object(utils, 'execute', return_value=('', '')) as ex:
            linux_net.create_ovs_vif_port('fake-bridge', 'fake-dev',
                                          'fake-iface-id', 'fake-mac',
                                          'fake-instance-uuid')
            ex.assert_has_calls(calls)

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

    def test_ovs_vif_port_with_mtu(self):
        self.flags(network_device_mtu=10000)
        calls = [
                mock.call('ovs-vsctl', '--timeout=120', '--', '--if-exists',
                          'del-port', 'fake-dev', '--', 'add-port',
                          'fake-bridge', 'fake-dev',
                          '--', 'set', 'Interface', 'fake-dev',
                          'external-ids:iface-id=fake-iface-id',
                          'external-ids:iface-status=active',
                          'external-ids:attached-mac=fake-mac',
                          'external-ids:vm-uuid=fake-instance-uuid',
                          run_as_root=True),
                mock.call('ip', 'link', 'set', 'fake-dev', 'mtu',
                          10000, run_as_root=True,
                          check_exit_code=[0, 2, 254])
                ]
        self._ovs_vif_port(calls)

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

    def test_create_veth_pair_with_mtu(self):
        self.flags(network_device_mtu=10000)
        calls = [
            mock.call('ip', 'link', 'add', 'fake-dev1', 'type', 'veth',
                      'peer', 'name', 'fake-dev2', run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'promisc', 'on',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev1', 'mtu',
                      10000, run_as_root=True,
                      check_exit_code=[0, 2, 254]),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'up',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'promisc', 'on',
                      run_as_root=True),
            mock.call('ip', 'link', 'set', 'fake-dev2', 'mtu',
                      10000, run_as_root=True,
                      check_exit_code=[0, 2, 254])
        ]
        self._create_veth_pair(calls)

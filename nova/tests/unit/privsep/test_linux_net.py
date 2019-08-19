# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from oslo_concurrency import processutils
import six

from nova import exception
import nova.privsep.linux_net
from nova import test
from nova.tests import fixtures


@mock.patch('oslo_concurrency.processutils.execute')
class LinuxNetTestCase(test.NoDBTestCase):
    """Test networking helpers."""

    def setUp(self):
        super(LinuxNetTestCase, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())

    def test_bridge_add_interface(self, mock_execute):
        nova.privsep.linux_net.bridge_add_interface('br0', 'eth0')
        cmd = ['brctl', 'addif', 'br0', 'eth0']
        mock_execute.assert_called_once_with(*cmd, check_exit_code=False)

    @mock.patch('os.path.exists')
    def test_device_exists(self, mock_exists, mock_execute):
        nova.privsep.linux_net.device_exists('eth0')
        mock_exists('/sys/class/net/eth0')

    def test_set_device_mtu_default(self, mock_execute):
        mock_execute.return_value = ('', '')

        nova.privsep.linux_net.set_device_mtu('fake-dev', None)
        mock_execute.assert_has_calls([])

    def test_set_device_mtu_actual(self, mock_execute):
        mock_execute.return_value = ('', '')

        nova.privsep.linux_net.set_device_mtu('fake-dev', 1500)
        mock_execute.assert_has_calls([
            mock.call('ip', 'link', 'set', 'fake-dev', 'mtu',
                      1500, check_exit_code=[0, 2, 254])])

    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev(self, mock_enabled, mock_execute):
        nova.privsep.linux_net.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')

    @mock.patch('os.path.exists', return_value=True)
    def test_create_tap_skipped_when_exists(self, mock_exists, mock_execute):
        nova.privsep.linux_net.create_tap_dev('tap42')

        mock_exists.assert_called_once_with('/sys/class/net/tap42')
        mock_execute.assert_not_called()

    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    @mock.patch('nova.privsep.linux_net._set_device_macaddr_inner')
    def test_create_tap_dev_mac(self, mock_set_macaddr, mock_enabled,
                                mock_execute):
        nova.privsep.linux_net.create_tap_dev(
            'tap42', '00:11:22:33:44:55')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')
        mock_set_macaddr.assert_has_calls([
            mock.call('tap42', '00:11:22:33:44:55')])

    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev_fallback_to_tunctl(self, mock_enabled,
                                               mock_execute):
        # ip failed, fall back to tunctl
        mock_execute.side_effect = [processutils.ProcessExecutionError, 0, 0]

        nova.privsep.linux_net.create_tap_dev('tap42')

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      check_exit_code=[0, 2, 254]),
            mock.call('tunctl', '-b', '-t', 'tap42')
        ])
        mock_enabled.assert_called_once_with('tap42')

    @mock.patch('nova.privsep.linux_net._set_device_enabled_inner')
    def test_create_tap_dev_multiqueue(self, mock_enabled, mock_execute):
        nova.privsep.linux_net.create_tap_dev(
            'tap42', multiqueue=True)

        mock_execute.assert_has_calls([
            mock.call('ip', 'tuntap', 'add', 'tap42', 'mode', 'tap',
                      'multi_queue', check_exit_code=[0, 2, 254])
        ])
        mock_enabled.assert_called_once_with('tap42')

    def test_create_tap_dev_multiqueue_tunctl_raises(self, mock_execute):
        # if creation of a tap by the means of ip command fails,
        # create_tap_dev() will try to do that by the means of tunctl
        mock_execute.side_effect = processutils.ProcessExecutionError
        # but tunctl can't create multiqueue taps, so the failure is expected
        self.assertRaises(processutils.ProcessExecutionError,
                          nova.privsep.linux_net.create_tap_dev,
                          'tap42', multiqueue=True)

    @mock.patch('nova.privsep.linux_net.ipv4_forwarding_check',
                return_value=False)
    def test_enable_ipv4_forwarding_required(self, mock_check, mock_execute):
        nova.privsep.linux_net.enable_ipv4_forwarding()
        mock_check.assert_called_once()
        mock_execute.assert_called_once_with(
            'sysctl', '-w', 'net.ipv4.ip_forward=1')

    @mock.patch('nova.privsep.linux_net.ipv4_forwarding_check',
                return_value=True)
    def test_enable_ipv4_forwarding_redundant(self, mock_check, mock_execute):
        nova.privsep.linux_net.enable_ipv4_forwarding()
        mock_check.assert_called_once()
        mock_execute.assert_not_called()

    def test_modify_ebtables_insert_rule(self, mock_execute):
        table = 'filter'
        rule = 'INPUT -p ARP -i %s --arp-ip-dst %s -j DROP'.split()

        nova.privsep.linux_net.modify_ebtables(table, rule, insert_rule=True)

        cmd = ['ebtables', '--concurrent', '-t', table] + ['-I'] + rule
        mock_execute.assert_called_once_with(*cmd, check_exit_code=[0])

    def test_modify_ebtables_remove_rule(self, mock_execute):
        table = 'filter'
        rule = 'INPUT -p ARP -i %s --arp-ip-dst %s -j DROP'.split()

        nova.privsep.linux_net.modify_ebtables(table, rule, insert_rule=False)

        cmd = ['ebtables', '--concurrent', '-t', table] + ['-D'] + rule
        mock_execute.assert_called_once_with(*cmd, check_exit_code=[0])

    def test_add_vlan(self, mock_execute):
        nova.privsep.linux_net.add_vlan('eth0', 'vlan_name', 1)
        cmd = ['ip', 'link', 'add', 'link', 'eth0', 'name', 'vlan_name',
               'type', 'vlan', 'id', 1]
        mock_execute.assert_called_once_with(*cmd, check_exit_code=[0, 2, 254])

    def test_iptables_get_rules(self, mock_execute):
        nova.privsep.linux_net.iptables_get_rules()
        cmd = ['iptables-save', '-c']
        mock_execute.assert_called_once_with(*cmd, attempts=5)

    def test_iptables_get_rules_ipv6(self, mock_execute):
        nova.privsep.linux_net.iptables_get_rules(ipv4=False)
        cmd = ['ip6tables-save', '-c']
        mock_execute.assert_called_once_with(*cmd, attempts=5)

    def test_iptables_set_rules(self, mock_execute):
        rules = [
            "# Generated by iptables-save v1.8.2 on Mon Aug 19 11:25:48 2019",
            "*security",
            ":INPUT ACCEPT [508089:729290563]",
            ":FORWARD ACCEPT [247333:239588306]",
            ":OUTPUT ACCEPT [340769:25538424]",
            ":FORWARD_direct - [0:0]",
            ":INPUT_direct - [0:0]",
            ":OUTPUT_direct - [0:0]",
            "-A INPUT -j INPUT_direct",
            "-A FORWARD -j FORWARD_direct",
            "-A OUTPUT -j OUTPUT_direct",
            "COMMIT",
            "# Completed on Mon Aug 19 11:25:48 2019",
        ]
        rules_str = six.b('\n'.join(rules))

        nova.privsep.linux_net.iptables_set_rules(rules)
        cmd = ['iptables-restore', '-c']
        mock_execute.assert_called_once_with(*cmd, process_input=rules_str,
                                             attempts=5)

    def test_iptables_set_rules_ipv6(self, mock_execute):
        rules = [
            "# Generated by ip6tables-save v1.8.2 on Mon Aug 19 12:00:29 2019",
            "*security",
            ":INPUT ACCEPT [56:10115]",
            ":FORWARD ACCEPT [0:0]",
            ":OUTPUT ACCEPT [147:15301]",
            ":FORWARD_direct - [0:0]",
            ":INPUT_direct - [0:0]",
            ":OUTPUT_direct - [0:0]",
            "-A INPUT -j INPUT_direct",
            "-A FORWARD -j FORWARD_direct",
            "-A OUTPUT -j OUTPUT_direct",
            "COMMIT",
            "# Completed on Mon Aug 19 12:00:29 2019",
        ]
        rules_str = six.b('\n'.join(rules))

        nova.privsep.linux_net.iptables_set_rules(rules, ipv4=False)
        cmd = ['ip6tables-restore', '-c']
        mock_execute.assert_called_once_with(*cmd, process_input=rules_str,
                                             attempts=5)

    def test_ovs_plug__fail(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError

        exc = self.assertRaises(exception.OVSConfigurationFailure,
                                nova.privsep.linux_net.ovs_plug,
                                60, 'int-br', 'eth0', '00:14:22:01:23:45')
        self.assertIsInstance(exc.kwargs['inner_exception'],
                              processutils.ProcessExecutionError)

    def test_ovs_unplug__fail(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError

        exc = self.assertRaises(exception.OVSConfigurationFailure,
                                nova.privsep.linux_net.ovs_unplug,
                                60, 'int-br', 'eth0')
        self.assertIsInstance(exc.kwargs['inner_exception'],
                              processutils.ProcessExecutionError)

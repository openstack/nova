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

from nova import exception
from nova import objects
from nova import test
from nova.virt import firewall

_IPT_DRIVER_CLS = firewall.IptablesFirewallDriver
_FN_INSTANCE_RULES = 'instance_rules'
_FN_ADD_FILTERS = 'add_filters_for_instance'
_FN_DO_BASIC_RULES = '_do_basic_rules'
_FN_DO_DHCP_RULES = '_do_dhcp_rules'


class TestIptablesFirewallDriver(test.NoDBTestCase):
    def setUp(self):
        super(TestIptablesFirewallDriver, self).setUp()
        self.driver = _IPT_DRIVER_CLS()

    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_constructor(self, iptm_mock):
        self.driver.__init__()

        self.assertEqual({}, self.driver.instance_info)
        self.assertFalse(self.driver.dhcp_create)
        self.assertFalse(self.driver.dhcp_created)
        self.assertEqual(iptm_mock, self.driver.iptables)

        # NOTE(jaypipes): Here we are not testing the IptablesManager
        # constructor. We are only testing the calls made against the
        # IptablesManager singleton during initialization of the
        # IptablesFirewallDriver.
        expected = [
            mock.call.add_chain('sg-fallback'),
            mock.call.add_rule('sg-fallback', '-j DROP'),
        ]
        iptm_mock.ipv4.__getitem__.return_value \
            .assert_has_calls(expected)
        iptm_mock.ipv6.__getitem__.return_value \
            .assert_has_calls(expected)

    def test_filter_defer_apply_on(self):
        with mock.patch.object(self.driver.iptables,
                               'defer_apply_on') as dao_mock:
            self.driver.filter_defer_apply_on()
            dao_mock.assert_called_once_with()

    def test_filter_defer_apply_off(self):
        with mock.patch.object(self.driver.iptables,
                               'defer_apply_off') as dao_mock:
            self.driver.filter_defer_apply_off()
            dao_mock.assert_called_once_with()

    @mock.patch.object(_IPT_DRIVER_CLS, 'remove_filters_for_instance')
    def test_unfilter_instance_valid(self, rfii_mock):
        with mock.patch.object(self.driver, 'instance_info') as ii_mock, \
            mock.patch.object(self.driver, 'iptables') as ipt_mock:
            fake_instance = objects.Instance(id=123)
            ii_mock.pop.return_value = True

            self.driver.unfilter_instance(fake_instance,
                                          mock.sentinel.net_info)

            ii_mock.pop.assert_called_once_with(fake_instance.id, None)
            rfii_mock.assert_called_once_with(fake_instance)
            ipt_mock.apply.assert_called_once_with()

    @mock.patch.object(_IPT_DRIVER_CLS, 'remove_filters_for_instance')
    def test_unfilter_instance_invalid(self, rfii_mock):
        with mock.patch.object(self.driver, 'instance_info') as ii_mock, \
            mock.patch.object(self.driver, 'iptables') as ipt_mock:
            fake_instance = objects.Instance(id=123)
            ii_mock.pop.return_value = False

            self.driver.unfilter_instance(fake_instance,
                                          mock.sentinel.net_info)

            ii_mock.pop.assert_called_once_with(fake_instance.id, None)
            self.assertFalse(rfii_mock.called)
            self.assertFalse(ipt_mock.apply.called)

    def setup_instance_filter(self, i_rules_mock):
        # NOTE(chenli) The IptablesFirewallDriver init method calls the
        # iptables manager, so we must reset here.
        self.driver.iptables = mock.MagicMock()

        i_mock = mock.MagicMock(spec=dict)
        i_mock.id = 'fake_id'
        i_rules_mock.return_value = (mock.sentinel.v4_rules,
                                     mock.sentinel.v6_rules)
        return i_mock

    @mock.patch.object(_IPT_DRIVER_CLS, _FN_ADD_FILTERS)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_INSTANCE_RULES)
    def test_prepare_instance_filter(self, i_rules_mock, add_filters_mock):
        i_mock = self.setup_instance_filter(i_rules_mock)

        self.driver.prepare_instance_filter(i_mock, mock.sentinel.net_info)

        i_rules_mock.assert_called_once_with(i_mock, mock.sentinel.net_info)
        add_filters_mock.assert_called_once_with(
            i_mock, mock.sentinel.net_info,
            mock.sentinel.v4_rules, mock.sentinel.v6_rules)
        self.driver.iptables.apply.assert_called_once_with()
        # When DHCP created flag is False, make sure we don't set any filters
        gi_mock = self.driver.iptables.ipv4.__getitem__.return_value
        self.assertFalse(gi_mock.called)

    @mock.patch.object(_IPT_DRIVER_CLS, _FN_ADD_FILTERS)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_INSTANCE_RULES)
    def test_prepare_instance_filter_with_dhcp_create(self, i_rules_mock,
        add_filters_mock):

        i_mock = self.setup_instance_filter(i_rules_mock)
        # add rules when DHCP create is set
        self.driver.dhcp_create = True

        self.driver.prepare_instance_filter(i_mock, mock.sentinel.net_info)

        expected = [
            mock.call.add_rule(
                'INPUT',
                '-s 0.0.0.0/32 -d 255.255.255.255/32 '
                '-p udp -m udp --sport 68 --dport 67 -j ACCEPT'),
            mock.call.add_rule(
                'FORWARD',
                '-s 0.0.0.0/32 -d 255.255.255.255/32 '
                '-p udp -m udp --sport 68 --dport 67 -j ACCEPT')
        ]
        self.driver.iptables.ipv4.__getitem__.return_value.assert_has_calls(
            expected)

    @mock.patch.object(_IPT_DRIVER_CLS, _FN_ADD_FILTERS)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_INSTANCE_RULES)
    def test_prepare_instance_filter_recreate(self, i_rules_mock,
                                              add_filters_mock):

        i_mock = self.setup_instance_filter(i_rules_mock)
        # add rules when DHCP create is set and create the rule
        self.driver.dhcp_create = True
        self.driver.prepare_instance_filter(i_mock, mock.sentinel.net_info)

        # Check we don't recreate the DHCP rules if we've already
        # done so (there is a dhcp_created flag on the driver that is
        # set when prepare_instance_filters() first creates them)
        self.driver.iptables.ipv4.__getitem__.reset_mock()
        self.driver.prepare_instance_filter(i_mock, mock.sentinel.net_info)
        gi_mock = self.driver.iptables.ipv4.__getitem__.return_value
        self.assertFalse(gi_mock.called)

    def test_create_filter(self):
        filter = self.driver._create_filter(['myip', 'otherip'], 'mychain')
        self.assertEqual(filter, ['-d myip -j $mychain',
                                  '-d otherip -j $mychain'])

    def test_get_subnets(self):
        subnet1 = {'version': '1', 'foo': 1}
        subnet2 = {'version': '2', 'foo': 2}
        subnet3 = {'version': '1', 'foo': 3}
        network_info = [{'network': {'subnets': [subnet1, subnet2]}},
                        {'network': {'subnets': [subnet3]}}]
        subnets = self.driver._get_subnets(network_info, '1')
        self.assertEqual(subnets, [subnet1, subnet3])

    def get_subnets_mock(self, network_info, version):
        if version == 4:
            return [{'ips': [{'address': '1.1.1.1'}, {'address': '2.2.2.2'}]}]
        if version == 6:
            return [{'ips': [{'address': '3.3.3.3'}]}]

    def create_filter_mock(self, ips, chain_name):
        if ips == ['1.1.1.1', '2.2.2.2']:
            return 'rule1'
        if ips == ['3.3.3.3']:
            return 'rule2'

    def test_filters_for_instance(self):
        self.flags(use_ipv6=True)
        chain_name = 'mychain'
        network_info = {'foo': 'bar'}
        self.driver._get_subnets = mock.Mock(side_effect=self.get_subnets_mock)
        self.driver._create_filter = \
            mock.Mock(side_effect=self.create_filter_mock)

        ipv4_rules, ipv6_rules = \
            self.driver._filters_for_instance(chain_name, network_info)

        self.assertEqual(self.driver._get_subnets.mock_calls,
            [mock.call(network_info, 4), mock.call(network_info, 6)])
        self.assertEqual(self.driver._create_filter.mock_calls,
            [mock.call(['1.1.1.1', '2.2.2.2'], chain_name),
             mock.call(['3.3.3.3'], chain_name)])
        self.assertEqual(ipv4_rules, 'rule1')
        self.assertEqual(ipv6_rules, 'rule2')

    def test_add_filters(self):
        self.flags(use_ipv6=True)
        self.driver.iptables.ipv4['filter'].add_rule = mock.Mock()
        self.driver.iptables.ipv6['filter'].add_rule = mock.Mock()
        chain_name = 'mychain'
        ipv4_rules = ['rule1', 'rule2']
        ipv6_rules = ['rule3', 'rule4']

        self.driver._add_filters(chain_name, ipv4_rules, ipv6_rules)

        self.assertEqual(self.driver.iptables.ipv4['filter'].add_rule.
                         mock_calls, [mock.call(chain_name, 'rule1'),
                                      mock.call(chain_name, 'rule2')])
        self.assertEqual(self.driver.iptables.ipv6['filter'].add_rule.
                         mock_calls, [mock.call(chain_name, 'rule3'),
                                      mock.call(chain_name, 'rule4')])

    @mock.patch.object(_IPT_DRIVER_CLS, '_instance_chain_name',
                       return_value=mock.sentinel.mychain)
    @mock.patch.object(_IPT_DRIVER_CLS, '_filters_for_instance',
                       return_value=[mock.sentinel.ipv4_rules,
                                     mock.sentinel.ipv6_rules])
    @mock.patch.object(_IPT_DRIVER_CLS, '_add_filters')
    def test_add_filters_for_instance(self, add_filters_mock,
                                      ffi_mock, icn_mock):
        self.flags(use_ipv6=True)
        with mock.patch.object(self.driver.iptables.ipv6['filter'],
                               'add_chain') as ipv6_add_chain_mock, \
             mock.patch.object(self.driver.iptables.ipv4['filter'],
                               'add_chain') as ipv4_add_chain_mock:

            self.driver.add_filters_for_instance(
                mock.sentinel.instance,
                mock.sentinel.network_info,
                mock.sentinel.inst_ipv4_rules,
                mock.sentinel.inst_ipv6_rules)
            ipv4_add_chain_mock.assert_called_with(mock.sentinel.mychain)
            ipv6_add_chain_mock.assert_called_with(mock.sentinel.mychain)
            icn_mock.assert_called_with(mock.sentinel.instance)
            ffi_mock.assert_called_with(mock.sentinel.mychain,
                                        mock.sentinel.network_info)
            self.assertEqual([mock.call('local',
                                         mock.sentinel.ipv4_rules,
                                         mock.sentinel.ipv6_rules),
                              mock.call(mock.sentinel.mychain,
                                        mock.sentinel.inst_ipv4_rules,
                                        mock.sentinel.inst_ipv6_rules)],
                            add_filters_mock.mock_calls)

    def test_remove_filters_for_instance(self):
        self.flags(use_ipv6=True)
        self.driver._instance_chain_name = \
            mock.Mock(return_value='mychainname')
        self.driver.iptables.ipv4['filter'].remove_chain = mock.Mock()
        self.driver.iptables.ipv6['filter'].remove_chain = mock.Mock()

        self.driver.remove_filters_for_instance('myinstance')

        self.driver._instance_chain_name.assert_called_with('myinstance')
        self.driver.iptables.ipv4['filter'].remove_chain.assert_called_with(
            'mychainname')
        self.driver.iptables.ipv6['filter'].remove_chain.assert_called_with(
            'mychainname')

    def test_instance_chain_name(self):
        instance = mock.Mock()
        instance.id = "myinstanceid"
        instance_chain_name = self.driver._instance_chain_name(instance)
        self.assertEqual(instance_chain_name, 'inst-myinstanceid')

    def test_do_basic_rules(self):
        ipv4_rules = ['rule1']
        ipv6_rules = ['rule2']
        self.driver._do_basic_rules(ipv4_rules, ipv6_rules,
                                    mock.sentinel.net_info)
        self.assertEqual(ipv4_rules,
                         ['rule1', '-m state --state INVALID -j DROP',
                          '-m state --state ESTABLISHED,RELATED -j ACCEPT'])
        self.assertEqual(ipv6_rules,
                         ['rule2', '-m state --state INVALID -j DROP',
                          '-m state --state ESTABLISHED,RELATED -j ACCEPT'])

    def test_do_dhcp_rules(self):
        subnet1 = mock.Mock()
        subnet1.get_meta = mock.Mock(return_value='mydhcp')
        subnet2 = mock.Mock()
        subnet2.get_meta = mock.Mock(return_value=None)
        self.driver._get_subnets = mock.Mock(return_value=[subnet1, subnet2])
        ipv4_rules = ['rule1']
        self.driver._do_dhcp_rules(ipv4_rules, mock.sentinel.net_info)
        self.assertEqual(ipv4_rules,
                         ['rule1',
                          '-s mydhcp -p udp --sport 67 --dport 68 -j ACCEPT'])

    def test_do_project_network_rules(self):
        self.flags(use_ipv6=True)
        subnet1 = {'cidr': 'mycidr1'}
        subnet2 = {'cidr': 'mycidr2'}
        ipv4_rules = ['rule1']
        ipv6_rules = ['rule2']
        self.driver._get_subnets = mock.Mock(return_value=[subnet1, subnet2])
        self.driver._do_project_network_rules(ipv4_rules, ipv6_rules,
                                              mock.sentinel.net_info)
        self.assertEqual(ipv4_rules,
                         ['rule1',
                          '-s mycidr1 -j ACCEPT', '-s mycidr2 -j ACCEPT'])
        self.assertEqual(ipv6_rules,
                         ['rule2',
                          '-s mycidr1 -j ACCEPT', '-s mycidr2 -j ACCEPT'])

    def test_do_ra_rules(self):
        subnet1 = {'gateway': {'address': 'myaddress1'}}
        subnet2 = {'gateway': {'address': 'myaddress2'}}
        self.driver._get_subnets = \
            mock.Mock(return_value=[subnet1, subnet2])
        ipv6_rules = ['rule1']
        self.driver._do_ra_rules(ipv6_rules, mock.sentinel.net_info)
        self.assertEqual(ipv6_rules, ['rule1',
                                      '-s myaddress1/128 -p icmpv6 -j ACCEPT',
                                      '-s myaddress2/128 -p icmpv6 -j ACCEPT'])

    def test_build_icmp_rule(self):
        rule = mock.Mock()
        # invalid icmp type
        rule.from_port = -1
        icmp_rule = self.driver._build_icmp_rule(rule, 4)
        self.assertEqual(icmp_rule, [])
        # version 4 invalid icmp code
        rule.from_port = 123
        rule.to_port = -1
        icmp_rule = self.driver._build_icmp_rule(rule, 4)
        self.assertEqual(icmp_rule,
                         ['-m', 'icmp', '--icmp-type', '123'])
        # version 6 valid icmp code
        rule.from_port = 123
        rule.to_port = 456
        icmp_rule = self.driver._build_icmp_rule(rule, 6)
        self.assertEqual(icmp_rule,
                         ['-m', 'icmp6', '--icmpv6-type', '123/456'])

    def test_build_tcp_udp_rule(self):
        rule = mock.Mock()
        # equal from and to port
        rule.from_port = 123
        rule.to_port = 123
        tu_rule = self.driver._build_tcp_udp_rule(rule, 42)
        self.assertEqual(tu_rule, ['--dport', '123'])
        # different from and to port
        rule.to_port = 456
        tu_rule = self.driver._build_tcp_udp_rule(rule, 42)
        self.assertEqual(tu_rule, ['-m', 'multiport', '--dports', '123:456'])

    def setup_instance_rules(self, ins_obj_cls_mock):
        """Create necessary mock varibles for instance_rules.

        The i_mock and ni_mock represent instance_rules parameters
        instance and network_info.

        The i_obj_mock represent the return vaue for nova.objects.Instance.
        """
        i_mock = mock.MagicMock(spec=dict)
        ni_mock = mock.MagicMock(spec=dict)
        i_obj_mock = mock.MagicMock()
        ins_obj_cls_mock._from_db_object.return_value = i_obj_mock
        driver = firewall.IptablesFirewallDriver()
        return i_mock, ni_mock, i_obj_mock, driver

    @mock.patch('nova.objects.SecurityGroupRuleList')
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_DHCP_RULES)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_BASIC_RULES)
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.context.get_admin_context',
                return_value=mock.sentinel.ctx)
    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_instance_rules_no_secgroups(self, _iptm_mock, ctx_mock,
            ins_obj_cls_mock, _do_basic_mock, _do_dhcp_mock,
            sec_grp_list_mock):

        i_mock, ni_mock, i_obj_mock, driver = self.setup_instance_rules(
            ins_obj_cls_mock)

        # Simple unit test that verifies that the fallback jump
        # is the only rule added to the returned list of rules if
        # no secgroups are found (we ignore the basic and DHCP
        # rule additions here)
        sec_grp_list_mock.get_by_instance.return_value = []

        v4_rules, v6_rules = driver.instance_rules(i_mock, ni_mock)

        ins_obj_cls_mock._from_db_object.assert_called_once_with(
                mock.sentinel.ctx, mock.ANY, i_mock, mock.ANY)
        sec_grp_list_mock.get_by_instance.assert_called_once_with(
                mock.sentinel.ctx, i_obj_mock)

        expected = ['-j $sg-fallback']
        self.assertEqual(expected, v4_rules)
        self.assertEqual(expected, v6_rules)

    @mock.patch('nova.objects.SecurityGroupRuleList')
    @mock.patch('nova.objects.SecurityGroupList')
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_DHCP_RULES)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_BASIC_RULES)
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.context.get_admin_context',
                return_value=mock.sentinel.ctx)
    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_instance_rules_cidr(self, _iptm_mock, ctx_mock,
            ins_obj_cls_mock, _do_basic_mock, _do_dhcp_mock,
            sec_grp_list_mock, sec_grp_rule_list_mock):

        i_mock, ni_mock, i_obj_mock, driver = self.setup_instance_rules(
            ins_obj_cls_mock)

        # Tests that sec group rules that contain a CIDR (i.e. the
        # rule does not contain a grantee group of instances) populates
        # the returned iptables rules with appropriate ingress and
        # egress filters.
        sec_grp_list_mock.get_by_instance.return_value = [
            mock.sentinel.sec_grp
        ]
        sec_grp_rule_list_mock.get_by_security_group.return_value = [
            {
                "cidr": "192.168.1.0/24",
                "protocol": "tcp",
                "to_port": "22",
                "from_port": "22"
            }
        ]

        v4_rules, v6_rules = driver.instance_rules(i_mock, ni_mock)

        expected = [
        #    '-j ACCEPT -p tcp --dport 22 -s 192.168.1.0/24',
            '-j $sg-fallback'
        ]
        self.assertEqual(expected, v4_rules)
        expected = ['-j $sg-fallback']
        self.assertEqual(expected, v6_rules)

    def setup_grantee_group(
        self, ins_obj_cls_mock, sec_grp_list_mock, sec_grp_rule_list_mock,
        ins_list_mock):

        i_mock, ni_mock, i_obj_mock, driver = self.setup_instance_rules(
            ins_obj_cls_mock)

        # Tests that sec group rules that DO NOT contain a CIDR (i.e. the
        # rule contains a grantee group of instances) populates
        # the returned iptables rules with appropriate ingress and
        # egress filters after calling out to the network API for information
        # about the instances in the grantee group.
        sec_grp_list_mock.get_by_instance.return_value = [
            mock.sentinel.sec_grp
        ]
        sec_grp_rule_list_mock.get_by_security_group.return_value = [
            {
                "cidr": None,
                "grantee_group": mock.sentinel.gg,
                "protocol": "tcp",
                "to_port": "22",
                "from_port": "22"
            }
        ]
        i_obj_list_mock = mock.MagicMock()
        i_obj_list_mock.info_cache.return_value = {
            "deleted": False
        }
        ins_list_mock.get_by_security_group.return_value = [i_obj_list_mock]
        return i_mock, i_obj_mock, ni_mock, driver

    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch('nova.objects.InstanceList')
    @mock.patch('nova.objects.SecurityGroupRuleList')
    @mock.patch('nova.objects.SecurityGroupList')
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_DHCP_RULES)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_BASIC_RULES)
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.context.get_admin_context',
                return_value=mock.sentinel.ctx)
    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_instance_rules_grantee_group(self, _iptm_mock, ctx_mock,
            ins_obj_cls_mock, _do_basic_mock, _do_dhcp_mock,
            sec_grp_list_mock, sec_grp_rule_list_mock, ins_list_mock,
            get_nw_info_mock):

        i_mock, i_obj_mock, ni_mock, driver = self.setup_grantee_group(
            ins_obj_cls_mock, sec_grp_list_mock, sec_grp_rule_list_mock,
            ins_list_mock)

        nw_info_mock = mock.MagicMock()
        nw_info_mock.fixed_ips.return_value = [
            {
                "address": "10.0.1.4",
                "version": 4
            }
        ]
        get_nw_info_mock.return_value = nw_info_mock

        v4_rules, v6_rules = driver.instance_rules(i_mock, ni_mock)

        expected = ['-j $sg-fallback']
        self.assertEqual(expected, v4_rules)
        self.assertEqual(expected, v6_rules)

    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch('nova.objects.InstanceList')
    @mock.patch('nova.objects.SecurityGroupRuleList')
    @mock.patch('nova.objects.SecurityGroupList')
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_DHCP_RULES)
    @mock.patch.object(_IPT_DRIVER_CLS, _FN_DO_BASIC_RULES)
    @mock.patch('nova.objects.Instance')
    @mock.patch('nova.context.get_admin_context',
                return_value=mock.sentinel.ctx)
    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_instance_rules_grantee_group_instance_deleted(
        self, _iptm_mock, ctx_mock, ins_obj_cls_mock, _do_basic_mock,
         _do_dhcp_mock, sec_grp_list_mock, sec_grp_rule_list_mock,
         ins_list_mock, get_nw_info_mock):

        i_mock, i_obj_mock, ni_mock, driver = self.setup_grantee_group(
            ins_obj_cls_mock, sec_grp_list_mock, sec_grp_rule_list_mock,
            ins_list_mock)

        # Emulate one of the instances in the grantee group being deleted
        # in between when the spawn of this instance and when we set up
        # network for that instance, and ensure that we do not crash and
        # burn but just skip the deleted instance from the iptables filters
        get_nw_info_mock.side_effect = exception.InstanceNotFound(
                instance_id="_ignored")

        v4_rules, v6_rules = driver.instance_rules(i_mock, ni_mock)

        expected = ['-j $sg-fallback']
        self.assertEqual(expected, v4_rules)
        self.assertEqual(expected, v6_rules)

    def test_refresh_security_group_rules(self):
        self.driver.do_refresh_security_group_rules = mock.Mock()
        self.driver.iptables.apply = mock.Mock()
        self.driver.refresh_security_group_rules('mysecgroup')
        self.driver.do_refresh_security_group_rules \
            .assert_called_with('mysecgroup')
        self.driver.iptables.apply.assert_called()

    def test_refresh_instance_security_rules(self):
        self.driver.do_refresh_instance_rules = mock.Mock()
        self.driver.iptables.apply = mock.Mock()
        self.driver.refresh_instance_security_rules('myinstance')
        self.driver.do_refresh_instance_rules.assert_called_with('myinstance')
        self.driver.iptables.apply.assert_called()

    def test_do_refresh_security_group_rules(self):
        self.driver.instance_info = \
            {'1': ['myinstance1', 'netinfo1'],
             '2': ['myinstance2', 'netinfo2']}
        self.driver.instance_rules = \
            mock.Mock(return_value=['myipv4rules', 'myipv6rules'])
        self.driver._inner_do_refresh_rules = mock.Mock()
        self.driver.do_refresh_security_group_rules('mysecgroup')
        self.driver.instance_rules.assert_any_call('myinstance1', 'netinfo1')
        self.driver.instance_rules.assert_any_call('myinstance2', 'netinfo2')
        self.driver._inner_do_refresh_rules.assert_any_call(
            'myinstance1', 'netinfo1',
            'myipv4rules', 'myipv6rules')
        self.driver._inner_do_refresh_rules.assert_any_call(
            'myinstance2', 'netinfo2',
            'myipv4rules', 'myipv6rules')

    def test_do_refresh_instance_rules(self):
        instance = mock.Mock()
        instance.id = 'myid'
        self.driver.instance_info = {instance.id: ['myinstance', 'mynetinfo']}
        self.driver.instance_rules = \
            mock.Mock(return_value=['myipv4rules', 'myipv6rules'])
        self.driver._inner_do_refresh_rules = mock.Mock()
        self.driver.do_refresh_instance_rules(instance)
        self.driver.instance_rules.assert_called_with(instance, 'mynetinfo')
        self.driver._inner_do_refresh_rules.assert_called_with(
            instance, 'mynetinfo', 'myipv4rules', 'myipv6rules')

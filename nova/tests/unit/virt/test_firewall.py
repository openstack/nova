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


from nova import objects
from nova import test
from nova.virt import firewall

_IPT_DRIVER_CLS = firewall.IptablesFirewallDriver


class TestIptablesFirewallDriver(test.NoDBTestCase):
    def setUp(self):
        super(TestIptablesFirewallDriver, self).setUp()
        self.driver = _IPT_DRIVER_CLS()

    @mock.patch('nova.network.linux_net.iptables_manager')
    def test_constructor(self, iptm_mock):
        self.driver.__init__()

        self.assertEqual({}, self.driver.instance_info)
        self.assertEqual(False, self.driver.dhcp_create)
        self.assertEqual(False, self.driver.dhcp_created)
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

            self.driver.unfilter_instance(fake_instance, 'fakenetinfo')

            ii_mock.pop.assert_called_once_with(fake_instance.id, None)
            rfii_mock.assert_called_once_with(fake_instance)
            ipt_mock.apply.assert_called_once_with()

    @mock.patch.object(_IPT_DRIVER_CLS, 'remove_filters_for_instance')
    def test_unfilter_instance_invalid(self, rfii_mock):
        with mock.patch.object(self.driver, 'instance_info') as ii_mock, \
            mock.patch.object(self.driver, 'iptables') as ipt_mock:
            fake_instance = objects.Instance(id=123)
            ii_mock.pop.return_value = False

            self.driver.unfilter_instance(fake_instance, 'fakenetinfo')

            ii_mock.pop.assert_called_once_with(fake_instance.id, None)
            self.assertFalse(rfii_mock.called)
            self.assertFalse(ipt_mock.apply.called)

#    Copyright (c) 2011 OpenStack Foundation
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

"""Test suite for IPv6."""

from nova import ipv6
from nova import test


class IPv6RFC2462TestCase(test.NoDBTestCase):
    """Unit tests for IPv6 rfc2462 backend operations."""
    def setUp(self):
        super(IPv6RFC2462TestCase, self).setUp()
        self.flags(ipv6_backend='rfc2462')
        ipv6.reset_backend()

    def test_to_global(self):
        addr = ipv6.to_global('2001:db8::', '02:16:3e:33:44:55', 'test')
        self.assertEqual(addr, '2001:db8::16:3eff:fe33:4455')

    def test_to_mac(self):
        mac = ipv6.to_mac('2001:db8::216:3eff:fe33:4455')
        self.assertEqual(mac, '00:16:3e:33:44:55')

    def test_to_global_with_bad_mac(self):
        bad_mac = '02:16:3e:33:44:5Z'
        expected_msg = 'Bad mac for to_global_ipv6: %s' % bad_mac
        err = self.assertRaises(TypeError, ipv6.to_global,
                                    '2001:db8::', bad_mac, 'test')
        self.assertEqual(expected_msg, str(err))

    def test_to_global_with_bad_prefix(self):
        bad_prefix = '2001::1::2'
        expected_msg = 'Bad prefix for to_global_ipv6: %s' % bad_prefix
        err = self.assertRaises(TypeError, ipv6.to_global,
                                    bad_prefix,
                                    '02:16:3e:33:44:55',
                                    'test')
        self.assertEqual(expected_msg, str(err))


class IPv6AccountIdentiferTestCase(test.NoDBTestCase):
    """Unit tests for IPv6 account_identifier backend operations."""
    def setUp(self):
        super(IPv6AccountIdentiferTestCase, self).setUp()
        self.flags(ipv6_backend='account_identifier')
        ipv6.reset_backend()

    def test_to_global(self):
        addr = ipv6.to_global('2001:db8::', '02:16:3e:33:44:55', 'test')
        self.assertEqual(addr, '2001:db8::a94a:8fe5:ff33:4455')

    def test_to_mac(self):
        mac = ipv6.to_mac('2001:db8::a94a:8fe5:ff33:4455')
        self.assertEqual(mac, '02:16:3e:33:44:55')

    def test_to_global_with_bad_mac(self):
        bad_mac = '02:16:3e:33:44:5Z'
        expected_msg = 'Bad mac for to_global_ipv6: %s' % bad_mac
        err = self.assertRaises(TypeError, ipv6.to_global,
                                    '2001:db8::', bad_mac, 'test')
        self.assertEqual(expected_msg, str(err))

    def test_to_global_with_bad_prefix(self):
        bad_prefix = '2001::1::2'
        expected_msg = 'Bad prefix for to_global_ipv6: %s' % bad_prefix
        err = self.assertRaises(TypeError, ipv6.to_global,
                                    bad_prefix,
                                    '02:16:3e:33:44:55',
                                    'test')
        self.assertEqual(expected_msg, str(err))

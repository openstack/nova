# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
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

from nova.rootwrap.filters import CommandFilter, RegExpFilter, DnsmasqFilter
from nova.rootwrap.wrapper import match_filter
from nova import test


class RootwrapTestCase(test.TestCase):

    def setUp(self):
        super(RootwrapTestCase, self).setUp()
        self.filters = [
            RegExpFilter("/bin/ls", "root", 'ls', '/[a-z]+'),
            CommandFilter("/usr/bin/foo_bar_not_exist", "root"),
            RegExpFilter("/bin/cat", "root", 'cat', '/[a-z]+'),
            CommandFilter("/nonexistant/cat", "root"),
            CommandFilter("/bin/cat", "root")  # Keep this one last
            ]

    def tearDown(self):
        super(RootwrapTestCase, self).tearDown()

    def test_RegExpFilter_match(self):
        usercmd = ["ls", "/root"]
        filtermatch = match_filter(self.filters, usercmd)
        self.assertFalse(filtermatch is None)
        self.assertEqual(filtermatch.get_command(usercmd),
            ["/bin/ls", "/root"])

    def test_RegExpFilter_reject(self):
        usercmd = ["ls", "root"]
        filtermatch = match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is None)

    def test_missing_command(self):
        usercmd = ["foo_bar_not_exist"]
        filtermatch = match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is None)

    def test_dnsmasq_filter(self):
        usercmd = ['FLAGFILE=A', 'NETWORK_ID="foo bar"', 'dnsmasq', 'foo']
        f = DnsmasqFilter("/usr/bin/dnsmasq", "root")
        self.assertTrue(f.match(usercmd))
        self.assertEqual(f.get_command(usercmd),
            ['FLAGFILE=A', 'NETWORK_ID="foo bar"', '/usr/bin/dnsmasq', 'foo'])

    def test_skips(self):
        # Check that all filters are skipped and that the last matches
        usercmd = ["cat", "/"]
        filtermatch = match_filter(self.filters, usercmd)
        self.assertTrue(filtermatch is self.filters[-1])

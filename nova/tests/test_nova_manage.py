# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
#    Copyright 2011 Ilya Alekseyev
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

import gettext
import os
import sys

TOPDIR = os.path.normpath(os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            os.pardir,
                            os.pardir))
NOVA_MANAGE_PATH = os.path.join(TOPDIR, 'bin', 'nova-manage')

gettext.install('nova', unicode=1)

sys.dont_write_bytecode = True
import imp
nova_manage = imp.load_source('nova_manage.py', NOVA_MANAGE_PATH)
sys.dont_write_bytecode = False

import netaddr
import StringIO
from nova import context
from nova import db
from nova import flags
from nova import test
from nova import exception

FLAGS = flags.FLAGS


class FixedIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FixedIpCommandsTestCase, self).setUp()
        cidr = '10.0.0.0/24'
        net = netaddr.IPNetwork(cidr)
        net_info = {'bridge': 'fakebr',
               'bridge_interface': 'fakeeth',
               'dns': FLAGS.flat_network_dns,
               'cidr': cidr,
               'netmask': str(net.netmask),
               'gateway': str(net[1]),
               'broadcast': str(net.broadcast),
               'dhcp_start': str(net[2])}
        self.network = db.network_create_safe(context.get_admin_context(),
                                              net_info)
        num_ips = len(net)
        for index in range(num_ips):
            address = str(net[index])
            reserved = (index == 1 or index == 2)
            db.fixed_ip_create(context.get_admin_context(),
                               {'network_id': self.network['id'],
                                'address': address,
                                'reserved': reserved})
        self.commands = nova_manage.FixedIpCommands()

    def tearDown(self):
        db.network_delete_safe(context.get_admin_context(), self.network['id'])
        super(FixedIpCommandsTestCase, self).tearDown()

    def test_reserve(self):
        self.commands.reserve('10.0.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '10.0.0.100')
        self.assertEqual(address['reserved'], True)

    def test_unreserve(self):
        db.fixed_ip_update(context.get_admin_context(), '10.0.0.100',
                           {'reserved': True})
        self.commands.unreserve('10.0.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '10.0.0.100')
        self.assertEqual(address['reserved'], False)

class NetworkCommandsTestCase(test.TestCase):
    def setUp(self):
#        print 'piyo'
        super(NetworkCommandsTestCase, self).setUp()
        self.commands = nova_manage.NetworkCommands()
        self.context = context.get_admin_context()
        nets = db.network_get_all(self.context)
        for net in nets:
            db.network_delete_safe(self.context, net['id'])

    def tearDown(self):
        super(NetworkCommandsTestCase, self).tearDown()

    def test_create(self):
        self.commands.create(
                             label = 'Test',
                             fixed_range_v4 = '10.2.0.0/24',
                             fixed_range_v6 = 'fd00:2::/64',
                             num_networks = 1,
                             network_size = 256,
                             vlan_start = 200,
                             bridge_interface = 'eth0',
                                )
        net = db.network_get_by_cidr(self.context, '10.2.0.0/24')
        self.assertEqual(net['label'], 'Test')
        self.assertEqual(net['cidr'], '10.2.0.0/24')
        self.assertEqual(net['netmask'], '255.255.255.0')
        self.assertEqual(net['cidr_v6'], 'fd00:2::/64')
        self.assertEqual(net['bridge_interface'], 'eth0')
        self.assertEqual(net['vlan'], 200)

    def test_list(self):
        format = "%-18s\t%-15s\t%-15s\t%-15s\t%-15s\t%-15s\t%-15s"
        head = format % (
            _('IPv4'),
            _('IPv6'),
            _('start address'),
            _('DNS1'),
            _('DNS2'),
            _('VlanID'),
            _('project'))
        body = format % (
            '10.2.0.0/24',
            'fd00:2::/64',
            '10.2.0.3',
            'None',
            'None',
            '200',
            'None',)
        self.test_create()
        output = StringIO.StringIO()
        sys.stdout = output
        self.commands.list()
        sys.stdout = sys.__stdout__
        result = output.getvalue()
        answer = '%s\n%s\n' % (head, body)
        self.assertEqual(result, answer)

    def test_delete(self):
        self.test_create()
        self.commands.delete(fixed_range = '10.2.0.0/24')
        net_exist = True
        try:
            net = db.network_get_by_cidr(self.context, '10.2.0.0/24')
        except exception.NetworkNotFoundForCidr, e:
            net_exist = False
        self.assertEqual(net_exist, False)

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

import os
import sys

TOPDIR = os.path.normpath(os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            os.pardir,
                            os.pardir))
NOVA_MANAGE_PATH = os.path.join(TOPDIR, 'bin', 'nova-manage')

sys.dont_write_bytecode = True
import imp
nova_manage = imp.load_source('nova_manage.py', NOVA_MANAGE_PATH)
sys.dont_write_bytecode = False
import mox
import stubout

import StringIO
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.db import fakes as db_fakes


class FixedIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FixedIpCommandsTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        db_fakes.stub_out_db_network_api(self.stubs)
        self.commands = nova_manage.FixedIpCommands()

    def tearDown(self):
        super(FixedIpCommandsTestCase, self).tearDown()
        self.stubs.UnsetAll()

    def test_reserve(self):
        self.commands.reserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertEqual(address['reserved'], True)

    def test_reserve_nonexistent_address(self):
        self.assertRaises(SystemExit,
                          self.commands.reserve,
                          '55.55.55.55')

    def test_unreserve(self):
        self.commands.unreserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertEqual(address['reserved'], False)

    def test_unreserve_nonexistent_address(self):
        self.assertRaises(SystemExit,
                          self.commands.unreserve,
                          '55.55.55.55')


class NetworkCommandsTestCase(test.TestCase):
    def setUp(self):
        super(NetworkCommandsTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.commands = nova_manage.NetworkCommands()
        self.context = context.get_admin_context()
        self.net = {'id': 0,
                    'label': 'fake',
                    'injected': False,
                    'cidr': '192.168.0.0/24',
                    'cidr_v6': 'dead:beef::/64',
                    'multi_host': False,
                    'gateway_v6': 'dead:beef::1',
                    'netmask_v6': '64',
                    'netmask': '255.255.255.0',
                    'bridge': 'fa0',
                    'bridge_interface': 'fake_fa0',
                    'gateway': '192.168.0.1',
                    'broadcast': '192.168.0.255',
                    'dns1': '8.8.8.8',
                    'dns2': '8.8.4.4',
                    'vlan': 200,
                    'vpn_public_address': '10.0.0.2',
                    'vpn_public_port': '2222',
                    'vpn_private_address': '192.168.0.2',
                    'dhcp_start': '192.168.0.3',
                    'project_id': 'fake_project',
                    'host': 'fake_host',
                    'uuid': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}

        def fake_network_get_by_cidr(context, cidr):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(cidr, self.fake_net['cidr'])
            return db_fakes.FakeModel(self.fake_net)

        def fake_network_update(context, network_id, values):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
            self.assertEqual(values, self.fake_update_value)
        self.fake_network_get_by_cidr = fake_network_get_by_cidr
        self.fake_network_update = fake_network_update

    def tearDown(self):
        super(NetworkCommandsTestCase, self).tearDown()
        self.stubs.UnsetAll()

    def test_create(self):

        def fake_create_networks(obj, context, **kwargs):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(kwargs['label'], 'Test')
            self.assertEqual(kwargs['cidr'], '10.2.0.0/24')
            self.assertEqual(kwargs['multi_host'], False)
            self.assertEqual(kwargs['num_networks'], 1)
            self.assertEqual(kwargs['network_size'], 256)
            self.assertEqual(kwargs['vlan_start'], 200)
            self.assertEqual(kwargs['vpn_start'], 2000)
            self.assertEqual(kwargs['cidr_v6'], 'fd00:2::/120')
            self.assertEqual(kwargs['gateway_v6'], 'fd00:2::22')
            self.assertEqual(kwargs['bridge'], 'br200')
            self.assertEqual(kwargs['bridge_interface'], 'eth0')
            self.assertEqual(kwargs['dns1'], '8.8.8.8')
            self.assertEqual(kwargs['dns2'], '8.8.4.4')
        self.flags(network_manager='nova.network.manager.VlanManager')
        from nova.network import manager as net_manager
        self.stubs.Set(net_manager.VlanManager, 'create_networks',
                       fake_create_networks)
        self.commands.create(
                            label='Test',
                            fixed_range_v4='10.2.0.0/24',
                            num_networks=1,
                            network_size=256,
                            multi_host='F',
                            vlan_start=200,
                            vpn_start=2000,
                            fixed_range_v6='fd00:2::/120',
                            gateway_v6='fd00:2::22',
                            bridge='br200',
                            bridge_interface='eth0',
                            dns1='8.8.8.8',
                            dns2='8.8.4.4')

    def test_list(self):

        def fake_network_get_all(context):
            return [db_fakes.FakeModel(self.net)]
        self.stubs.Set(db, 'network_get_all', fake_network_get_all)
        output = StringIO.StringIO()
        sys.stdout = output
        self.commands.list()
        sys.stdout = sys.__stdout__
        result = output.getvalue()
        _fmt = "%(id)-5s\t%(cidr)-18s\t%(cidr_v6)-15s\t%(dhcp_start)-15s\t" +\
               "%(dns1)-15s\t%(dns2)-15s\t%(vlan)-15s\t%(project_id)-15s\t" +\
               "%(uuid)-15s"
        head = _fmt % {'id': _('id'),
                       'cidr': _('IPv4'),
                       'cidr_v6': _('IPv6'),
                       'dhcp_start': _('start address'),
                       'dns1': _('DNS1'),
                       'dns2': _('DNS2'),
                       'vlan': _('VlanID'),
                       'project_id': _('project'),
                       'uuid': _("uuid")}
        body = _fmt % {'id': self.net['id'],
                       'cidr': self.net['cidr'],
                       'cidr_v6': self.net['cidr_v6'],
                       'dhcp_start': self.net['dhcp_start'],
                       'dns1': self.net['dns1'],
                       'dns2': self.net['dns2'],
                       'vlan': self.net['vlan'],
                       'project_id': self.net['project_id'],
                       'uuid': self.net['uuid']}
        answer = '%s\n%s\n' % (head, body)
        self.assertEqual(result, answer)

    def test_delete(self):
        self.fake_net = self.net
        self.fake_net['project_id'] = None
        self.fake_net['host'] = None
        self.stubs.Set(db, 'network_get_by_cidr',
                       self.fake_network_get_by_cidr)

        def fake_network_delete_safe(context, network_id):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
        self.stubs.Set(db, 'network_delete_safe', fake_network_delete_safe)
        self.commands.delete(fixed_range=self.fake_net['cidr'])

    def _test_modify_base(self, update_value, project, host, dis_project=None,
                          dis_host=None):
        self.fake_net = self.net
        self.fake_update_value = update_value
        self.stubs.Set(db, 'network_get_by_cidr',
                       self.fake_network_get_by_cidr)
        self.stubs.Set(db, 'network_update', self.fake_network_update)
        self.commands.modify(self.fake_net['cidr'], project=project, host=host,
                             dis_project=dis_project, dis_host=dis_host)

    def test_modify_associate(self):
        self._test_modify_base(update_value={'project_id': 'test_project',
                                             'host': 'test_host'},
                               project='test_project', host='test_host')

    def test_modify_unchanged(self):
        self._test_modify_base(update_value={}, project=None, host=None)

    def test_modify_disassociate(self):
        self._test_modify_base(update_value={'project_id': None, 'host': None},
                               project=None, host=None, dis_project=True,
                               dis_host=True)

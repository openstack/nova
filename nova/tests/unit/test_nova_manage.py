#    Copyright 2011 OpenStack Foundation
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

import StringIO
import sys

import fixtures
import mock

from nova.cmd import manage
from nova import context
from nova import db
from nova.db import migration
from nova import exception
from nova.i18n import _
from nova import test
from nova.tests.unit.db import fakes as db_fakes
from nova.tests.unit.objects import test_network


class FixedIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FixedIpCommandsTestCase, self).setUp()
        db_fakes.stub_out_db_network_api(self.stubs)
        self.commands = manage.FixedIpCommands()

    def test_reserve(self):
        self.commands.reserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertEqual(address['reserved'], True)

    def test_reserve_nonexistent_address(self):
        self.assertEqual(2, self.commands.reserve('55.55.55.55'))

    def test_unreserve(self):
        self.commands.unreserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertEqual(address['reserved'], False)

    def test_unreserve_nonexistent_address(self):
        self.assertEqual(2, self.commands.unreserve('55.55.55.55'))

    def test_list(self):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO.StringIO()))
        self.commands.list()
        self.assertNotEqual(1, sys.stdout.getvalue().find('192.168.0.100'))

    def test_list_just_one_host(self):
        def fake_fixed_ip_get_by_host(*args, **kwargs):
            return [db_fakes.fixed_ip_fields]

        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.fixed_ip_get_by_host',
            fake_fixed_ip_get_by_host))
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO.StringIO()))
        self.commands.list('banana')
        self.assertNotEqual(1, sys.stdout.getvalue().find('192.168.0.100'))


class FloatingIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FloatingIpCommandsTestCase, self).setUp()
        db_fakes.stub_out_db_network_api(self.stubs)
        self.commands = manage.FloatingIpCommands()

    def test_address_to_hosts(self):
        def assert_loop(result, expected):
            for ip in result:
                self.assertIn(str(ip), expected)

        address_to_hosts = self.commands.address_to_hosts
        # /32 and /31
        self.assertRaises(exception.InvalidInput, address_to_hosts,
                          '192.168.100.1/32')
        self.assertRaises(exception.InvalidInput, address_to_hosts,
                          '192.168.100.1/31')
        # /30
        expected = ["192.168.100.%s" % i for i in range(1, 3)]
        result = address_to_hosts('192.168.100.0/30')
        self.assertEqual(2, len(list(result)))
        assert_loop(result, expected)
        # /29
        expected = ["192.168.100.%s" % i for i in range(1, 7)]
        result = address_to_hosts('192.168.100.0/29')
        self.assertEqual(6, len(list(result)))
        assert_loop(result, expected)
        # /28
        expected = ["192.168.100.%s" % i for i in range(1, 15)]
        result = address_to_hosts('192.168.100.0/28')
        self.assertEqual(14, len(list(result)))
        assert_loop(result, expected)
        # /16
        result = address_to_hosts('192.168.100.0/16')
        self.assertEqual(65534, len(list(result)))
        # NOTE(dripton): I don't test /13 because it makes the test take 3s.
        # /12 gives over a million IPs, which is ridiculous.
        self.assertRaises(exception.InvalidInput, address_to_hosts,
                          '192.168.100.1/12')


class NetworkCommandsTestCase(test.TestCase):
    def setUp(self):
        super(NetworkCommandsTestCase, self).setUp()
        self.commands = manage.NetworkCommands()
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
                    'vlan_start': 201,
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
            return db_fakes.FakeModel(dict(test_network.fake_network,
                                           **self.fake_net))

        def fake_network_get_by_uuid(context, uuid):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(uuid, self.fake_net['uuid'])
            return db_fakes.FakeModel(dict(test_network.fake_network,
                                           **self.fake_net))

        def fake_network_update(context, network_id, values):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
            self.assertEqual(values, self.fake_update_value)
        self.fake_network_get_by_cidr = fake_network_get_by_cidr
        self.fake_network_get_by_uuid = fake_network_get_by_uuid
        self.fake_network_update = fake_network_update

    def test_create(self):

        def fake_create_networks(obj, context, **kwargs):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(kwargs['label'], 'Test')
            self.assertEqual(kwargs['cidr'], '10.2.0.0/24')
            self.assertEqual(kwargs['multi_host'], False)
            self.assertEqual(kwargs['num_networks'], 1)
            self.assertEqual(kwargs['network_size'], 256)
            self.assertEqual(kwargs['vlan'], 200)
            self.assertEqual(kwargs['vlan_start'], 201)
            self.assertEqual(kwargs['vpn_start'], 2000)
            self.assertEqual(kwargs['cidr_v6'], 'fd00:2::/120')
            self.assertEqual(kwargs['gateway'], '10.2.0.1')
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
                            cidr='10.2.0.0/24',
                            num_networks=1,
                            network_size=256,
                            multi_host='F',
                            vlan=200,
                            vlan_start=201,
                            vpn_start=2000,
                            cidr_v6='fd00:2::/120',
                            gateway='10.2.0.1',
                            gateway_v6='fd00:2::22',
                            bridge='br200',
                            bridge_interface='eth0',
                            dns1='8.8.8.8',
                            dns2='8.8.4.4',
                            uuid='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')

    def test_list(self):

        def fake_network_get_all(context):
            return [db_fakes.FakeModel(self.net)]
        self.stubs.Set(db, 'network_get_all', fake_network_get_all)
        output = StringIO.StringIO()
        sys.stdout = output
        self.commands.list()
        sys.stdout = sys.__stdout__
        result = output.getvalue()
        _fmt = "\t".join(["%(id)-5s", "%(cidr)-18s", "%(cidr_v6)-15s",
                          "%(dhcp_start)-15s", "%(dns1)-15s", "%(dns2)-15s",
                          "%(vlan)-15s", "%(project_id)-15s", "%(uuid)-15s"])
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
        self.stubs.Set(db, 'network_get_by_uuid',
                       self.fake_network_get_by_uuid)

        def fake_network_delete_safe(context, network_id):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
        self.stubs.Set(db, 'network_delete_safe', fake_network_delete_safe)
        self.commands.delete(uuid=self.fake_net['uuid'])

    def test_delete_by_cidr(self):
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


class NeutronV2NetworkCommandsTestCase(test.TestCase):
    def setUp(self):
        super(NeutronV2NetworkCommandsTestCase, self).setUp()
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        self.commands = manage.NetworkCommands()

    def test_create(self):
        self.assertEqual(2, self.commands.create())

    def test_list(self):
        self.assertEqual(2, self.commands.list())

    def test_delete(self):
        self.assertEqual(2, self.commands.delete())

    def test_modify(self):
        self.assertEqual(2, self.commands.modify('192.168.0.1'))


class ProjectCommandsTestCase(test.TestCase):
    def setUp(self):
        super(ProjectCommandsTestCase, self).setUp()
        self.commands = manage.ProjectCommands()

    def test_quota(self):
        output = StringIO.StringIO()
        sys.stdout = output
        self.commands.quota(project_id='admin',
                            key='instances',
                            value='unlimited',
                           )

        sys.stdout = sys.__stdout__
        result = output.getvalue()
        print_format = "%-36s %-10s" % ('instances', 'unlimited')
        self.assertEqual((print_format in result), True)

    def test_quota_update_invalid_key(self):
        self.assertEqual(2, self.commands.quota('admin', 'volumes1', '10'))


class DBCommandsTestCase(test.TestCase):
    def setUp(self):
        super(DBCommandsTestCase, self).setUp()
        self.commands = manage.DbCommands()

    def test_archive_deleted_rows_negative(self):
        self.assertEqual(1, self.commands.archive_deleted_rows(-1))

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 0})
    def test_null_instance_uuid_scan_no_records_found(self, mock_scan):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO.StringIO()))
        self.commands.null_instance_uuid_scan()
        self.assertIn("There were no records found", sys.stdout.getvalue())

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 1, 'bar': 0})
    def _test_null_instance_uuid_scan(self, mock_scan, delete):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO.StringIO()))
        self.commands.null_instance_uuid_scan(delete)
        output = sys.stdout.getvalue()

        if delete:
            self.assertIn("Deleted 1 records from table 'foo'.", output)
            self.assertNotIn("Deleted 0 records from table 'bar'.", output)
        else:
            self.assertIn("1 records in the 'foo' table", output)
            self.assertNotIn("0 records in the 'bar' table", output)
        self.assertNotIn("There were no records found", output)

    def test_null_instance_uuid_scan_readonly(self):
        self._test_null_instance_uuid_scan(delete=False)

    def test_null_instance_uuid_scan_delete(self):
        self._test_null_instance_uuid_scan(delete=True)


class ServiceCommandsTestCase(test.TestCase):
    def setUp(self):
        super(ServiceCommandsTestCase, self).setUp()
        self.commands = manage.ServiceCommands()

    def test_service_enable_invalid_params(self):
        self.assertEqual(2, self.commands.enable('nohost', 'noservice'))

    def test_service_disable_invalid_params(self):
        self.assertEqual(2, self.commands.disable('nohost', 'noservice'))


class CellCommandsTestCase(test.TestCase):
    def setUp(self):
        super(CellCommandsTestCase, self).setUp()
        self.commands = manage.CellCommands()

    def test_create_transport_hosts_multiple(self):
        """Test the _create_transport_hosts method
        when broker_hosts is set.
        """
        brokers = "127.0.0.1:5672,127.0.0.2:5671"
        thosts = self.commands._create_transport_hosts(
                                           'guest', 'devstack',
                                           broker_hosts=brokers)
        self.assertEqual(2, len(thosts))
        self.assertEqual('127.0.0.1', thosts[0].hostname)
        self.assertEqual(5672, thosts[0].port)
        self.assertEqual('127.0.0.2', thosts[1].hostname)
        self.assertEqual(5671, thosts[1].port)

    def test_create_transport_hosts_single(self):
        """Test the _create_transport_hosts method when hostname is passed."""
        thosts = self.commands._create_transport_hosts('guest', 'devstack',
                                                       hostname='127.0.0.1',
                                                       port=80)
        self.assertEqual(1, len(thosts))
        self.assertEqual('127.0.0.1', thosts[0].hostname)
        self.assertEqual(80, thosts[0].port)

    def test_create_transport_hosts_single_broker(self):
        """Test the _create_transport_hosts method for single broker_hosts."""
        thosts = self.commands._create_transport_hosts(
                                              'guest', 'devstack',
                                              broker_hosts='127.0.0.1:5672')
        self.assertEqual(1, len(thosts))
        self.assertEqual('127.0.0.1', thosts[0].hostname)
        self.assertEqual(5672, thosts[0].port)

    def test_create_transport_hosts_both(self):
        """Test the _create_transport_hosts method when both broker_hosts
        and hostname/port are passed.
        """
        thosts = self.commands._create_transport_hosts(
                                              'guest', 'devstack',
                                              broker_hosts='127.0.0.1:5672',
                                              hostname='127.0.0.2', port=80)
        self.assertEqual(1, len(thosts))
        self.assertEqual('127.0.0.1', thosts[0].hostname)
        self.assertEqual(5672, thosts[0].port)

    def test_create_transport_hosts_wrong_val(self):
        """Test the _create_transport_hosts method when broker_hosts
        is wrongly sepcified
        """
        self.assertRaises(ValueError,
                          self.commands._create_transport_hosts,
                          'guest', 'devstack',
                          broker_hosts='127.0.0.1:5672,127.0.0.1')

    def test_create_transport_hosts_wrong_port_val(self):
        """Test the _create_transport_hosts method when port in
        broker_hosts is wrongly sepcified
        """
        self.assertRaises(ValueError,
                          self.commands._create_transport_hosts,
                          'guest', 'devstack',
                          broker_hosts='127.0.0.1:')

    def test_create_transport_hosts_wrong_port_arg(self):
        """Test the _create_transport_hosts method when port
        argument is wrongly sepcified
        """
        self.assertRaises(ValueError,
                          self.commands._create_transport_hosts,
                          'guest', 'devstack',
                          hostname='127.0.0.1', port='ab')

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(db, 'cell_create')
    def test_create_broker_hosts(self, mock_db_cell_create, mock_ctxt):
        """Test the create function when broker_hosts is
        passed
        """
        cell_tp_url = "fake://guest:devstack@127.0.0.1:5432"
        cell_tp_url += ",guest:devstack@127.0.0.2:9999/"
        ctxt = mock.sentinel
        mock_ctxt.return_value = mock.sentinel
        self.commands.create("test",
                             broker_hosts='127.0.0.1:5432,127.0.0.2:9999',
                             woffset=0, wscale=0,
                             username="guest", password="devstack")
        exp_values = {'name': "test",
                      'is_parent': False,
                      'transport_url': cell_tp_url,
                      'weight_offset': 0.0,
                      'weight_scale': 0.0}
        mock_db_cell_create.assert_called_once_with(ctxt, exp_values)

    @mock.patch.object(context, 'get_admin_context')
    @mock.patch.object(db, 'cell_create')
    def test_create_hostname(self, mock_db_cell_create, mock_ctxt):
        """Test the create function when hostname and port is
        passed
        """
        cell_tp_url = "fake://guest:devstack@127.0.0.1:9999/"
        ctxt = mock.sentinel
        mock_ctxt.return_value = mock.sentinel
        self.commands.create("test",
                             hostname='127.0.0.1', port="9999",
                             woffset=0, wscale=0,
                             username="guest", password="devstack")
        exp_values = {'name': "test",
                      'is_parent': False,
                      'transport_url': cell_tp_url,
                      'weight_offset': 0.0,
                      'weight_scale': 0.0}
        mock_db_cell_create.assert_called_once_with(ctxt, exp_values)

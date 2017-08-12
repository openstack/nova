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

import sys

import fixtures
import mock
from oslo_db import exception as db_exc
from oslo_utils import uuidutils
from six.moves import StringIO

from nova.cmd import manage
from nova import conf
from nova import context
from nova import db
from nova.db import migration
from nova.db.sqlalchemy import migration as sqla_migration
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.db import fakes as db_fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_network
from nova.tests.unit import test_flavors
from nova.tests import uuidsentinel

CONF = conf.CONF


class FixedIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FixedIpCommandsTestCase, self).setUp()
        db_fakes.stub_out_db_network_api(self)
        self.commands = manage.FixedIpCommands()

    def test_reserve(self):
        self.commands.reserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertTrue(address['reserved'])

    def test_reserve_nonexistent_address(self):
        self.assertEqual(2, self.commands.reserve('55.55.55.55'))

    def test_unreserve(self):
        self.commands.unreserve('192.168.0.100')
        address = db.fixed_ip_get_by_address(context.get_admin_context(),
                                             '192.168.0.100')
        self.assertFalse(address['reserved'])

    def test_unreserve_nonexistent_address(self):
        self.assertEqual(2, self.commands.unreserve('55.55.55.55'))

    def test_list(self):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO()))
        self.commands.list()
        self.assertNotEqual(1, sys.stdout.getvalue().find('192.168.0.100'))

    def test_list_just_one_host(self):
        def fake_fixed_ip_get_by_host(*args, **kwargs):
            return [db_fakes.fixed_ip_fields]

        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.fixed_ip_get_by_host',
            fake_fixed_ip_get_by_host))
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO()))
        self.commands.list('banana')
        self.assertNotEqual(1, sys.stdout.getvalue().find('192.168.0.100'))


class FloatingIpCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(FloatingIpCommandsTestCase, self).setUp()
        db_fakes.stub_out_db_network_api(self)
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


class NetworkCommandsTestCase(test.NoDBTestCase):
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
            self.assertFalse(kwargs['multi_host'])
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
        self.stub_out('nova.network.manager.VlanManager.create_networks',
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

    def test_create_without_lable(self):
        self.assertRaises(exception.NetworkNotCreated,
                          self.commands.create,
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

    def test_create_with_lable_too_long(self):
        self.assertRaises(exception.LabelTooLong,
                          self.commands.create,
                          label='x' * 256,
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

    def test_create_without_cidr(self):
        self.assertRaises(exception.NetworkNotCreated,
                          self.commands.create,
                          label='Test',
                          num_networks=1,
                          network_size=256,
                          multi_host='F',
                          vlan=200,
                          vlan_start=201,
                          vpn_start=2000,
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
        self.stub_out('nova.db.network_get_all', fake_network_get_all)
        output = StringIO()
        sys.stdout = output
        self.commands.list()
        sys.stdout = sys.__stdout__
        result = output.getvalue()
        _fmt = "\t".join(["%(id)-5s", "%(cidr)-18s", "%(cidr_v6)-15s",
                          "%(dhcp_start)-15s", "%(dns1)-15s", "%(dns2)-15s",
                          "%(vlan)-15s", "%(project_id)-15s", "%(uuid)-15s"])
        head = _fmt % {'id': 'id',
                       'cidr': 'IPv4',
                       'cidr_v6': 'IPv6',
                       'dhcp_start': 'start address',
                       'dns1': 'DNS1',
                       'dns2': 'DNS2',
                       'vlan': 'VlanID',
                       'project_id': 'project',
                       'uuid': "uuid"}
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
        self.stub_out('nova.db.network_get_by_uuid',
                      self.fake_network_get_by_uuid)

        def fake_network_delete_safe(context, network_id):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
        self.stub_out('nova.db.network_delete_safe', fake_network_delete_safe)
        self.commands.delete(uuid=self.fake_net['uuid'])

    def test_delete_by_cidr(self):
        self.fake_net = self.net
        self.fake_net['project_id'] = None
        self.fake_net['host'] = None
        self.stub_out('nova.db.network_get_by_cidr',
                      self.fake_network_get_by_cidr)

        def fake_network_delete_safe(context, network_id):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(network_id, self.fake_net['id'])
        self.stub_out('nova.db.network_delete_safe', fake_network_delete_safe)
        self.commands.delete(fixed_range=self.fake_net['cidr'])

    def _test_modify_base(self, update_value, project, host, dis_project=None,
                          dis_host=None):
        self.fake_net = self.net
        self.fake_update_value = update_value
        self.stub_out('nova.db.network_get_by_cidr',
                      self.fake_network_get_by_cidr)
        self.stub_out('nova.db.network_update', self.fake_network_update)
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


class NeutronV2NetworkCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(NeutronV2NetworkCommandsTestCase, self).setUp()
        self.flags(use_neutron=True)
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
        output = StringIO()
        sys.stdout = output
        self.commands.quota(project_id='admin',
                            key='instances',
                            value='unlimited',
                           )

        sys.stdout = sys.__stdout__
        result = output.getvalue()
        print_format = "%-36s %-10s" % ('instances', 'unlimited')
        self.assertIn(print_format, result)

    def test_quota_update_invalid_key(self):
        self.assertEqual(2, self.commands.quota('admin', 'volumes1', '10'))

    def test_quota_usage_refresh_all_user_keys(self):
        self.assertIsNone(self.commands.quota_usage_refresh(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab'))

    def test_quota_usage_refresh_all_project_keys(self):
        self.assertIsNone(self.commands.quota_usage_refresh(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'))

    def test_quota_usage_refresh_with_keys(self):
        self.assertIsNone(self.commands.quota_usage_refresh(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab',
            'ram'))

    def test_quota_usage_refresh_invalid_user_key(self):
        self.assertEqual(2, self.commands.quota_usage_refresh(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab',
            'fixed_ip'))

    def test_quota_usage_refresh_invalid_project_key(self):
        self.assertEqual(2, self.commands.quota_usage_refresh(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            None,
            'ram'))


class VmCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VmCommandsTestCase, self).setUp()
        self.commands = manage.VmCommands()
        self.fake_flavor = objects.Flavor(**test_flavors.DEFAULT_FLAVORS[0])

    def test_list_without_host(self):
        output = StringIO()
        sys.stdout = output
        with mock.patch.object(objects.InstanceList, 'get_by_filters') as get:
            get.return_value = objects.InstanceList(
                objects=[fake_instance.fake_instance_obj(
                    context.get_admin_context(), host='foo-host',
                    flavor=self.fake_flavor,
                    system_metadata={})])
            self.commands.list()

        sys.stdout = sys.__stdout__
        result = output.getvalue()

        self.assertIn('node', result)   # check the header line
        self.assertIn('m1.tiny', result)    # flavor.name
        self.assertIn('foo-host', result)

    def test_list_with_host(self):
        output = StringIO()
        sys.stdout = output
        with mock.patch.object(objects.InstanceList, 'get_by_host') as get:
            get.return_value = objects.InstanceList(
                objects=[fake_instance.fake_instance_obj(
                    context.get_admin_context(),
                    flavor=self.fake_flavor,
                    system_metadata={})])
            self.commands.list(host='fake-host')

        sys.stdout = sys.__stdout__
        result = output.getvalue()

        self.assertIn('node', result)   # check the header line
        self.assertIn('m1.tiny', result)    # flavor.name
        self.assertIn('fake-host', result)


class DBCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DBCommandsTestCase, self).setUp()
        self.commands = manage.DbCommands()

    def test_archive_deleted_rows_negative(self):
        self.assertEqual(1, self.commands.archive_deleted_rows(-1))

    def test_archive_deleted_rows_large_number(self):
        large_number = '1' * 100
        self.assertEqual(1, self.commands.archive_deleted_rows(large_number))

    @mock.patch.object(db, 'archive_deleted_rows',
                       return_value=dict(instances=10, consoles=5))
    def _test_archive_deleted_rows(self, mock_db_archive, verbose=False):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        self.commands.archive_deleted_rows(20, verbose=verbose)
        mock_db_archive.assert_called_once_with(20)
        output = sys.stdout.getvalue()
        if verbose:
            expected = '''\
+-----------+-------------------------+
| Table     | Number of Rows Archived |
+-----------+-------------------------+
| consoles  | 5                       |
| instances | 10                      |
+-----------+-------------------------+
'''
            self.assertEqual(expected, output)
        else:
            self.assertEqual(0, len(output))

    def test_archive_deleted_rows(self):
        # Tests that we don't show any table output (not verbose).
        self._test_archive_deleted_rows()

    def test_archive_deleted_rows_verbose(self):
        # Tests that we get table output.
        self._test_archive_deleted_rows(verbose=True)

    @mock.patch.object(db, 'archive_deleted_rows', return_value={})
    def test_archive_deleted_rows_verbose_no_results(self, mock_db_archive):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        self.commands.archive_deleted_rows(20, verbose=True)
        mock_db_archive.assert_called_once_with(20)
        output = sys.stdout.getvalue()
        self.assertIn('Nothing was archived.', output)

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 0})
    def test_null_instance_uuid_scan_no_records_found(self, mock_scan):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO()))
        self.commands.null_instance_uuid_scan()
        self.assertIn("There were no records found", sys.stdout.getvalue())

    @mock.patch.object(migration, 'db_null_instance_uuid_scan',
                       return_value={'foo': 1, 'bar': 0})
    def _test_null_instance_uuid_scan(self, mock_scan, delete):
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO()))
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

    @mock.patch.object(sqla_migration, 'db_version', return_value=2)
    def test_version(self, sqla_migrate):
        self.commands.version()
        sqla_migrate.assert_called_once_with(context=None, database='main')

    @mock.patch.object(sqla_migration, 'db_sync')
    def test_sync(self, sqla_sync):
        self.commands.sync(version=4, local_cell=True)
        sqla_sync.assert_called_once_with(context=None,
                                          version=4, database='main')

    @mock.patch('nova.db.migration.db_sync')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid', return_value='map')
    def test_sync_cell0(self, mock_get_by_uuid, mock_db_sync):
        ctxt = context.get_admin_context()
        cell_ctxt = context.get_admin_context()
        with test.nested(
                mock.patch('nova.context.RequestContext',
                           return_value=ctxt),
                mock.patch('nova.context.target_cell')) \
                                   as (mock_get_context,
                                       mock_target_cell):
            fake_target_cell_mock = mock.MagicMock()
            fake_target_cell_mock.__enter__.return_value = cell_ctxt
            mock_target_cell.return_value = fake_target_cell_mock
            self.commands.sync(version=4)
            mock_get_by_uuid.assert_called_once_with(ctxt,
                                        objects.CellMapping.CELL0_UUID)
            mock_target_cell.assert_called_once_with(ctxt, 'map')

            db_sync_calls = [
                    mock.call(4, context=ctxt),
                    mock.call(4)
            ]
            mock_db_sync.assert_has_calls(db_sync_calls)

    def _fake_db_command(self, migrations=None):
        if migrations is None:
            mock_mig_1 = mock.MagicMock(__name__="mock_mig_1")
            mock_mig_2 = mock.MagicMock(__name__="mock_mig_2")
            mock_mig_1.return_value = (5, 4)
            mock_mig_2.return_value = (6, 6)
            migrations = (mock_mig_1, mock_mig_2)

        class _CommandSub(manage.DbCommands):
            online_migrations = migrations

        return _CommandSub

    @mock.patch('nova.context.get_admin_context')
    def test_online_migrations(self, mock_get_context):
        ctxt = mock_get_context.return_value
        command_cls = self._fake_db_command()
        command = command_cls()
        command.online_data_migrations(10)
        command_cls.online_migrations[0].assert_called_once_with(ctxt, 10)
        command_cls.online_migrations[1].assert_called_once_with(ctxt, 6)

    @mock.patch('nova.context.get_admin_context')
    def test_online_migrations_no_max_count(self, mock_get_context):
        total = [120]
        batches = [50, 40, 30, 0]
        runs = []

        def fake_migration(context, count):
            self.assertEqual(mock_get_context.return_value, context)
            runs.append(count)
            count = batches.pop(0)
            total[0] -= count
            return total[0], count

        command_cls = self._fake_db_command((fake_migration,))
        command = command_cls()
        command.online_data_migrations(None)
        self.assertEqual([], batches)
        self.assertEqual(0, total[0])
        self.assertEqual([50, 50, 50, 50], runs)

    def test_online_migrations_error(self):
        fake_migration = mock.MagicMock()
        fake_migration.side_effect = Exception
        command_cls = self._fake_db_command((fake_migration,))
        command = command_cls()
        command.online_data_migrations(None)

    def test_online_migrations_bad_max(self):
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count=-2))
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count='a'))
        self.assertEqual(127,
                         self.commands.online_data_migrations(max_count=0))

    def test_online_migrations_no_max(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = 0
            self.assertEqual(0,
                             self.commands.online_data_migrations())

    def test_online_migrations_finished(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = 0
            self.assertEqual(0,
                             self.commands.online_data_migrations(max_count=5))

    def test_online_migrations_not_finished(self):
        with mock.patch.object(self.commands, '_run_migration') as rm:
            rm.return_value = 5
            self.assertEqual(1,
                             self.commands.online_data_migrations(max_count=5))


class ApiDbCommandsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ApiDbCommandsTestCase, self).setUp()
        self.commands = manage.ApiDbCommands()

    @mock.patch.object(sqla_migration, 'db_version', return_value=2)
    def test_version(self, sqla_migrate):
        self.commands.version()
        sqla_migrate.assert_called_once_with(context=None,
                                             database='api')

    @mock.patch.object(sqla_migration, 'db_sync')
    def test_sync(self, sqla_sync):
        self.commands.sync(version=4)
        sqla_sync.assert_called_once_with(context=None,
                                          version=4, database='api')


class CellCommandsTestCase(test.NoDBTestCase):
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
        is wrongly specified
        """
        self.assertRaises(ValueError,
                          self.commands._create_transport_hosts,
                          'guest', 'devstack',
                          broker_hosts='127.0.0.1:5672,127.0.0.1')

    def test_create_transport_hosts_wrong_port_val(self):
        """Test the _create_transport_hosts method when port in
        broker_hosts is wrongly specified
        """
        self.assertRaises(ValueError,
                          self.commands._create_transport_hosts,
                          'guest', 'devstack',
                          broker_hosts='127.0.0.1:')

    def test_create_transport_hosts_wrong_port_arg(self):
        """Test the _create_transport_hosts method when port
        argument is wrongly specified
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
    def test_create_broker_hosts_with_url_decoding_fix(self,
                                                       mock_db_cell_create,
                                                       mock_ctxt):
        """Test the create function when broker_hosts is
        passed
        """
        cell_tp_url = "fake://the=user:the=password@127.0.0.1:5432/"
        ctxt = mock.sentinel
        mock_ctxt.return_value = mock.sentinel
        self.commands.create("test",
                             broker_hosts='127.0.0.1:5432',
                             woffset=0, wscale=0,
                             username="the=user",
                             password="the=password")
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


class CellV2CommandsTestCase(test.TestCase):
    def setUp(self):
        super(CellV2CommandsTestCase, self).setUp()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))
        self.commands = manage.CellV2Commands()

    def test_map_cell_and_hosts(self):
        # Create some fake compute nodes and check if they get host mappings
        ctxt = context.RequestContext()
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        self.commands.map_cell_and_hosts(cell_transport_url, name='ssd',
                                         verbose=True)
        cell_mapping_uuid = sys.stdout.getvalue().strip()
        # Verify the cell mapping
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_mapping_uuid)
        self.assertEqual('ssd', cell_mapping.name)
        self.assertEqual(cell_transport_url, cell_mapping.transport_url)
        # Verify the host mappings
        for i in range(3):
            host = 'host%s' % i
            host_mapping = objects.HostMapping.get_by_host(ctxt, host)
            self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)

    def test_map_cell_and_hosts_duplicate(self):
        # Create a cell mapping and hosts and check that nothing new is created
        ctxt = context.RequestContext()
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_mapping_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        # Create compute nodes that will map to the cell
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()
            host_mapping = objects.HostMapping(
                    ctxt, host=host, cell_mapping=cell_mapping)
            host_mapping.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        retval = self.commands.map_cell_and_hosts(cell_transport_url,
                                                  name='ssd',
                                                  verbose=True)
        self.assertEqual(0, retval)
        output = sys.stdout.getvalue().strip()
        expected = ''
        for i in range(3):
            expected += ('Host host%s is already mapped to cell %s\n' %
                         (i, cell_mapping_uuid))
        expected += 'All hosts are already mapped to cell(s), exiting.'
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_partial_update(self):
        # Create a cell mapping and partial hosts and check that
        # missing HostMappings are created
        ctxt = context.RequestContext()
        cell_mapping_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_mapping_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        # Create compute nodes that will map to the cell
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()

        # NOTE(danms): Create a second node on one compute to make sure
        # we handle that case
        compute_node = objects.ComputeNode(ctxt, host='host0', **values)
        compute_node.create()

        # Only create 2 existing HostMappings out of 3
        for i in range(2):
            host = 'host%s' % i
            host_mapping = objects.HostMapping(
                    ctxt, host=host, cell_mapping=cell_mapping)
            host_mapping.create()
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        self.commands.map_cell_and_hosts(cell_transport_url,
                                         name='ssd',
                                         verbose=True)
        # Verify the HostMapping for the last host was created
        host_mapping = objects.HostMapping.get_by_host(ctxt, 'host2')
        self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)
        # Verify the output
        output = sys.stdout.getvalue().strip()
        expected = ''
        for i in [0, 1, 0]:
            expected += ('Host host%s is already mapped to cell %s\n' %
                         (i, cell_mapping_uuid))
        # The expected CellMapping UUID for the last host should be the same
        expected += cell_mapping.uuid
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_no_hosts_found(self):
        cell_transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        retval = self.commands.map_cell_and_hosts(cell_transport_url,
                                                  name='ssd',
                                                  verbose=True)
        self.assertEqual(0, retval)
        output = sys.stdout.getvalue().strip()
        expected = 'No hosts found to map to cell, exiting.'
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_no_transport_url(self):
        retval = self.commands.map_cell_and_hosts()
        self.assertEqual(1, retval)
        output = sys.stdout.getvalue().strip()
        expected = ('Must specify --transport-url if [DEFAULT]/transport_url '
                    'is not set in the configuration file.')
        self.assertEqual(expected, output)

    def test_map_cell_and_hosts_transport_url_config(self):
        self.flags(transport_url = "fake://guest:devstack@127.0.0.1:9999/")
        retval = self.commands.map_cell_and_hosts()
        self.assertEqual(0, retval)

    def test_map_instances(self):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        instance_uuids = []
        for i in range(3):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             uuid=uuid).create()

        self.commands.map_instances(cell_uuid)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
            self.assertEqual(cell_mapping.uuid, inst_mapping.cell_mapping.uuid)

    def test_map_instances_duplicates(self):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        instance_uuids = []
        for i in range(3):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             uuid=uuid).create()

        objects.InstanceMapping(ctxt, project_id=ctxt.project_id,
                instance_uuid=instance_uuids[0],
                cell_mapping=cell_mapping).create()

        self.commands.map_instances(cell_uuid)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)

        mappings = objects.InstanceMappingList.get_by_project_id(ctxt,
                ctxt.project_id)
        self.assertEqual(3, len(mappings))

    def test_map_instances_two_batches(self):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        instance_uuids = []
        # Batch size is 50 in map_instances
        for i in range(60):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid)
        self.assertEqual(0, ret)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)

    def test_map_instances_max_count(self):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        instance_uuids = []
        for i in range(6):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid, max_count=3)
        self.assertEqual(1, ret)

        for uuid in instance_uuids[:3]:
            # First three are mapped
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)
        for uuid in instance_uuids[3:]:
            # Last three are not
            self.assertRaises(exception.InstanceMappingNotFound,
                    objects.InstanceMapping.get_by_instance_uuid, ctxt,
                    uuid)

    def test_map_instances_marker_deleted(self):
        ctxt = context.RequestContext('fake-user', 'fake_project')
        cell_uuid = uuidutils.generate_uuid()
        cell_mapping = objects.CellMapping(
                ctxt, uuid=cell_uuid, name='fake',
                transport_url='fake://', database_connection='fake://')
        cell_mapping.create()
        instance_uuids = []
        for i in range(6):
            uuid = uuidutils.generate_uuid()
            instance_uuids.append(uuid)
            objects.Instance(ctxt, project_id=ctxt.project_id,
                             uuid=uuid).create()

        ret = self.commands.map_instances(cell_uuid, max_count=3)
        self.assertEqual(1, ret)

        # Instances are mapped in the order created so we know the marker is
        # based off the third instance.
        marker = instance_uuids[2].replace('-', ' ')
        marker_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                marker)
        marker_mapping.destroy()

        ret = self.commands.map_instances(cell_uuid)
        self.assertEqual(0, ret)

        for uuid in instance_uuids:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(ctxt,
                    uuid)
            self.assertEqual(ctxt.project_id, inst_mapping.project_id)

    def test_map_cell0(self):
        ctxt = context.RequestContext()
        database_connection = 'fake:/foobar//'
        self.commands.map_cell0(database_connection)
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual(database_connection, cell_mapping.database_connection)

    def test_map_cell0_default_database(self):
        CONF.set_default('connection',
                         'fake://netloc/nova',
                         group='database')
        ctxt = context.RequestContext()
        self.commands.map_cell0()
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual('fake://netloc/nova_cell0',
                         cell_mapping.database_connection)

    def test_map_cell0_default_database_special_characters(self):
        """Tests that a URL with special characters, like in the credentials,
        is handled properly.
        """
        for connection in (
                'mysql+pymysql://nova:abcd0123:AB@controller/%s',
                'mysql+pymysql://nova:abcd0123?AB@controller/%s',
                'mysql+pymysql://nova:abcd0123@AB@controller/%s',
                'mysql+pymysql://nova:abcd0123/AB@controller/%s',
                'mysql+pymysql://test:abcd0123/AB@controller/%s?charset=utf8'):
            decoded_connection = connection % 'nova'
            self.flags(connection=decoded_connection, group='database')
            ctxt = context.RequestContext()
            self.commands.map_cell0()
            cell_mapping = objects.CellMapping.get_by_uuid(
                ctxt, objects.CellMapping.CELL0_UUID)
            self.assertEqual('cell0', cell_mapping.name)
            self.assertEqual('none:///', cell_mapping.transport_url)
            self.assertEqual(
            connection % 'nova_cell0',
                cell_mapping.database_connection)
            # Delete the cell mapping for the next iteration.
            cell_mapping.destroy()

    def _test_migrate_simple_command(self, cell0_sync_fail=False):
        ctxt = context.RequestContext()
        CONF.set_default('connection',
                         'fake://netloc/nova',
                         group='database')
        values = {
                'vcpus': 4,
                'memory_mb': 4096,
                'local_gb': 1024,
                'vcpus_used': 2,
                'memory_mb_used': 2048,
                'local_gb_used': 512,
                'hypervisor_type': 'Hyper-Dan-VM-ware',
                'hypervisor_version': 1001,
                'cpu_info': 'Schmintel i786',
            }
        for i in range(3):
            host = 'host%s' % i
            compute_node = objects.ComputeNode(ctxt, host=host, **values)
            compute_node.create()

        transport_url = "fake://guest:devstack@127.0.0.1:9999/"
        cell_uuid = uuidsentinel.cell

        @mock.patch('nova.db.migration.db_sync')
        @mock.patch.object(uuidutils, 'generate_uuid',
                return_value=cell_uuid)
        def _test(mock_gen_uuid, mock_db_sync):
            if cell0_sync_fail:
                mock_db_sync.side_effect = db_exc.DBError
            result = self.commands.simple_cell_setup(transport_url)
            mock_db_sync.assert_called_once_with(
                None, context=test.MatchType(context.RequestContext))
            return result

        r = _test()
        self.assertEqual(0, r)

        # Check cell0 from default
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt,
                objects.CellMapping.CELL0_UUID)
        self.assertEqual('cell0', cell_mapping.name)
        self.assertEqual('none:///', cell_mapping.transport_url)
        self.assertEqual('fake://netloc/nova_cell0',
                         cell_mapping.database_connection)

        # Verify the cell mapping
        cell_mapping = objects.CellMapping.get_by_uuid(ctxt, cell_uuid)
        self.assertEqual(transport_url, cell_mapping.transport_url)
        # Verify the host mappings
        for i in range(3):
            host = 'host%s' % i
            host_mapping = objects.HostMapping.get_by_host(ctxt, host)
            self.assertEqual(cell_mapping.uuid, host_mapping.cell_mapping.uuid)

    def test_simple_command_single(self):
        self._test_migrate_simple_command()

    def test_simple_command_cell0_fail(self):
        # Make sure that if db_sync fails, we still do all the other
        # bits
        self._test_migrate_simple_command(cell0_sync_fail=True)

    def test_simple_command_multiple(self):
        # Make sure that the command is idempotent
        self._test_migrate_simple_command()
        self._test_migrate_simple_command()

    def test_simple_command_cellsv1(self):
        self.flags(enable=True, group='cells')
        self.assertEqual(2, self.commands.simple_cell_setup('foo'))

    def test_instance_verify_no_mapping(self):
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(1, r)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_instance_verify_has_only_instance_mapping(self, mock_get):
        im = objects.InstanceMapping(cell_mapping=None)
        mock_get.return_value = im
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(2, r)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_instance_verify_has_all_mappings(self, mock_get):
        cm = objects.CellMapping(name='foo', uuid=uuidsentinel.cel)
        im = objects.InstanceMapping(cell_mapping=cm)
        mock_get.return_value = im
        r = self.commands.verify_instance(uuidsentinel.instance)
        self.assertEqual(0, r)

    def test_instance_verify_bad_uuid(self):
        self.assertEqual(16, self.commands.verify_instance(''))

    def test_instance_verify_quiet(self):
        # NOTE(danms): This will hit the first use of the say() wrapper
        # and reasonably verify that path
        self.assertEqual(1, self.commands.verify_instance(uuidsentinel.foo,
                                                          quiet=True))

    def _return_compute_nodes(self, ctxt, num=1):
        nodes = []
        for i in range(num):
            nodes.append(objects.ComputeNode(ctxt,
                                             uuid=uuidutils.generate_uuid(),
                                             host='fake',
                                             vcpus=1,
                                             memory_mb=1,
                                             local_gb=1,
                                             vcpus_used=0,
                                             memory_mb_used=0,
                                             local_gb_used=0,
                                             hypervisor_type='',
                                             hypervisor_version=1,
                                             cpu_info=''))
        return nodes

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects, 'HostMapping')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_discover_hosts_single_cell(self, mock_cell_mapping_get_by_uuid,
                                        mock_cell_mapping_get_all,
                                        mock_compute_get_all,
                                        mock_host_mapping, mock_target_cell):
        host_mock = mock.MagicMock()
        mock_host_mapping.return_value = host_mock
        exc = exception.HostMappingNotFound(name='fake')
        mock_host_mapping.get_by_host.side_effect = exc

        ctxt = context.RequestContext()

        compute_nodes = self._return_compute_nodes(ctxt)
        mock_compute_get_all.return_value = objects.ComputeNodeList(
            objects=compute_nodes)

        cell_mapping = objects.CellMapping(uuid=uuidutils.generate_uuid())
        mock_cell_mapping_get_by_uuid.return_value = cell_mapping

        self.commands.discover_hosts(cell_uuid=cell_mapping.uuid)

        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext), cell_mapping)
        host_mock.create.assert_called_once()
        mock_host_mapping.assert_called_once_with(
            test.MatchType(context.RequestContext), host='fake',
            cell_mapping=cell_mapping)
        mock_cell_mapping_get_all.assert_not_called()

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects, 'HostMapping')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_discover_hosts_single_cell_no_new_hosts(
            self, mock_cell_mapping_get_by_uuid, mock_cell_mapping_get_all,
            mock_compute_get_all, mock_host_mapping, mock_target_cell):

        host_mock = mock.MagicMock()
        mock_host_mapping.return_value = host_mock

        ctxt = context.RequestContext()

        compute_nodes = self._return_compute_nodes(ctxt)
        mock_compute_get_all.return_value = objects.ComputeNodeList(
            objects=compute_nodes)

        cell_mapping = objects.CellMapping(uuid=uuidutils.generate_uuid())
        mock_cell_mapping_get_by_uuid.return_value = cell_mapping

        self.commands.discover_hosts(cell_uuid=cell_mapping.uuid)

        mock_target_cell.assert_called_once_with(
            test.MatchType(context.RequestContext), cell_mapping)
        mock_host_mapping.assert_not_called()
        mock_cell_mapping_get_all.assert_not_called()

    @mock.patch.object(context, 'target_cell')
    @mock.patch.object(objects, 'HostMapping')
    @mock.patch.object(objects.ComputeNodeList, 'get_all')
    @mock.patch.object(objects.CellMappingList, 'get_all')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    def test_discover_hosts_multiple_cells(self, mock_cell_mapping_get_by_uuid,
                                           mock_cell_mapping_get_all,
                                           mock_compute_get_all,
                                           mock_host_mapping,
                                           mock_target_cell):
        host_mock = mock.MagicMock()
        mock_host_mapping.return_value = host_mock
        exc = exception.HostMappingNotFound(name='fake')
        mock_host_mapping.get_by_host.side_effect = exc

        ctxt = context.RequestContext()

        compute_nodes = self._return_compute_nodes(ctxt, num=2)
        mock_compute_get_all.side_effect = (
            objects.ComputeNodeList(objects=compute_nodes[1:]),
            objects.ComputeNodeList(objects=compute_nodes[:1]))

        cell_mapping1 = objects.CellMapping(uuid=uuidutils.generate_uuid())
        cell_mapping2 = objects.CellMapping(uuid=uuidutils.generate_uuid())
        mock_cell_mapping_get_all.return_value = objects.CellMappingList(
            objects=[cell_mapping1, cell_mapping2])

        self.commands.discover_hosts()

        self.assertEqual(2, mock_target_cell.call_count)
        target_calls = [mock.call(test.MatchType(context.RequestContext),
                                  cell_mapping1),
                        mock.call(test.MatchType(context.RequestContext),
                                  cell_mapping2)]
        self.assertEqual(target_calls, mock_target_cell.call_args_list)

        self.assertEqual(2, host_mock.create.call_count)
        self.assertEqual(2, mock_host_mapping.call_count)
        host_mapping_calls = [mock.call(test.MatchType(context.RequestContext),
                                        host=compute_nodes[0].host,
                                        cell_mapping=cell_mapping1),
                              mock.call(test.MatchType(context.RequestContext),
                                        host=compute_nodes[1].host,
                                        cell_mapping=cell_mapping2)]
        self.assertEqual(host_mapping_calls, mock_host_mapping.call_args_list)

        mock_cell_mapping_get_by_uuid.assert_not_called()
        mock_cell_mapping_get_all.assert_called_once_with(
            test.MatchType(context.RequestContext))

    def test_validate_transport_url_in_conf(self):
        from_conf = 'fake://user:pass@host:port/'
        self.flags(transport_url=from_conf)
        self.assertEqual(from_conf,
                         self.commands._validate_transport_url(None))

    def test_validate_transport_url_on_command_line(self):
        from_cli = 'fake://user:pass@host:port/'
        self.assertEqual(from_cli,
                         self.commands._validate_transport_url(from_cli))

    def test_validate_transport_url_missing(self):
        self.assertIsNone(self.commands._validate_transport_url(None))

    def test_validate_transport_url_favors_command_line(self):
        self.flags(transport_url='fake://user:pass@host:port/')
        from_cli = 'fake://otheruser:otherpass@otherhost:otherport'
        self.assertEqual(from_cli,
                         self.commands._validate_transport_url(from_cli))

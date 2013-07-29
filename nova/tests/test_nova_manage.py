# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import fixtures
import StringIO
import sys

from nova.cmd import manage
from nova import context
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova import test
from nova.tests.db import fakes as db_fakes


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
        self.assertTrue(sys.stdout.getvalue().find('192.168.0.100') != -1)

    def test_list_just_one_host(self):
        def fake_fixed_ip_get_by_host(*args, **kwargs):
            return [db_fakes.fixed_ip_fields]

        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.fixed_ip_get_by_host',
            fake_fixed_ip_get_by_host))
        self.useFixture(fixtures.MonkeyPatch('sys.stdout',
                                             StringIO.StringIO()))
        self.commands.list('banana')
        self.assertTrue(sys.stdout.getvalue().find('192.168.0.100') != -1)


class FloatingIpCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FloatingIpCommandsTestCase, self).setUp()
        db_fakes.stub_out_db_network_api(self.stubs)
        self.commands = manage.FloatingIpCommands()

    def test_address_to_hosts(self):
        def assert_loop(result, expected):
            for ip in result:
                self.assertTrue(str(ip) in expected)

        address_to_hosts = self.commands.address_to_hosts
        # /32 and /31
        self.assertRaises(exception.InvalidInput, address_to_hosts,
                          '192.168.100.1/32')
        self.assertRaises(exception.InvalidInput, address_to_hosts,
                          '192.168.100.1/31')
        # /30
        expected = ["192.168.100.%s" % i for i in range(1, 3)]
        result = address_to_hosts('192.168.100.0/30')
        self.assertTrue(len(list(result)) == 2)
        assert_loop(result, expected)
        # /29
        expected = ["192.168.100.%s" % i for i in range(1, 7)]
        result = address_to_hosts('192.168.100.0/29')
        self.assertTrue(len(list(result)) == 6)
        assert_loop(result, expected)
        # /28
        expected = ["192.168.100.%s" % i for i in range(1, 15)]
        result = address_to_hosts('192.168.100.0/28')
        self.assertTrue(len(list(result)) == 14)
        assert_loop(result, expected)
        # /16
        result = address_to_hosts('192.168.100.0/16')
        self.assertTrue(len(list(result)) == 65534)
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

        def fake_network_get_by_uuid(context, uuid):
            self.assertTrue(context.to_dict()['is_admin'])
            self.assertEqual(uuid, self.fake_net['uuid'])
            return db_fakes.FakeModel(self.fake_net)

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
            self.assertEqual(kwargs['vlan_start'], 200)
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
                            vlan_start=200,
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


class FlavorCommandsTestCase(test.TestCase):
    def setUp(self):
        super(FlavorCommandsTestCase, self).setUp()

        values = dict(name="test.small",
                      memory_mb=220,
                      vcpus=1,
                      root_gb=16,
                      ephemeral_gb=32,
                      flavorid=105)
        ref = db.flavor_create(context.get_admin_context(),
                                      values)
        self.instance_type_name = ref["name"]
        self.instance_type_id = ref["id"]
        self.instance_type_flavorid = ref["flavorid"]
        self.set_key = manage.FlavorCommands().set_key
        self.unset_key = manage.FlavorCommands().unset_key

    def tearDown(self):
        db.flavor_destroy(context.get_admin_context(),
                                 "test.small")
        super(FlavorCommandsTestCase, self).tearDown()

    def _test_extra_specs_empty(self):
        empty_specs = {}
        actual_specs = db.flavor_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_id)
        self.assertEquals(empty_specs, actual_specs)

    def test_extra_specs_set_unset(self):
        expected_specs = {'k1': 'v1'}

        self._test_extra_specs_empty()

        self.set_key(self.instance_type_name, "k1", "v1")
        actual_specs = db.flavor_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_flavorid)
        self.assertEquals(expected_specs, actual_specs)

        self.unset_key(self.instance_type_name, "k1")
        self._test_extra_specs_empty()

    def test_extra_specs_update(self):
        expected_specs = {'k1': 'v1'}
        updated_specs = {'k1': 'v2'}

        self._test_extra_specs_empty()

        self.set_key(self.instance_type_name, "k1", "v1")
        actual_specs = db.flavor_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_flavorid)
        self.assertEquals(expected_specs, actual_specs)

        self.set_key(self.instance_type_name, "k1", "v2")
        actual_specs = db.flavor_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_flavorid)
        self.assertEquals(updated_specs, actual_specs)

        self.unset_key(self.instance_type_name, "k1")

    def test_extra_specs_multiple(self):
        two_items_extra_specs = {'k1': 'v1',
                                'k3': 'v3'}

        self._test_extra_specs_empty()

        self.set_key(self.instance_type_name, "k1", "v1")
        self.set_key(self.instance_type_name, "k3", "v3")
        actual_specs = db.flavor_extra_specs_get(
                              context.get_admin_context(),
                              self.instance_type_flavorid)
        self.assertEquals(two_items_extra_specs, actual_specs)

        self.unset_key(self.instance_type_name, "k1")
        self.unset_key(self.instance_type_name, "k3")


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
        self.assertEquals((print_format in result), True)

    def test_quota_update_invalid_key(self):
        self.assertEqual(2, self.commands.quota('admin', 'volumes1', '10'))


class DBCommandsTestCase(test.TestCase):
    def setUp(self):
        super(DBCommandsTestCase, self).setUp()
        self.commands = manage.DbCommands()

    def test_archive_deleted_rows_negative(self):
        self.assertEqual(1, self.commands.archive_deleted_rows(-1))


class ServiceCommandsTestCase(test.TestCase):
    def setUp(self):
        super(ServiceCommandsTestCase, self).setUp()
        self.commands = manage.ServiceCommands()

    def test_service_enable_invalid_params(self):
        self.assertEqual(2, self.commands.enable('nohost', 'noservice'))

    def test_service_disable_invalid_params(self):
        self.assertEqual(2, self.commands.disable('nohost', 'noservice'))

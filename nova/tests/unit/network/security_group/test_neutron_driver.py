# Copyright 2013 OpenStack Foundation
# All Rights Reserved
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
#
import mock
from neutronclient.common import exceptions as n_exc
from neutronclient.neutron import v2_0 as neutronv20
from neutronclient.v2_0 import client
from six.moves import range

from nova import context
from nova import exception
from nova.network.security_group import neutron_driver
from nova import objects
from nova import test
from nova.tests import uuidsentinel as uuids


class TestNeutronDriver(test.NoDBTestCase):
    def setUp(self):
        super(TestNeutronDriver, self).setUp()
        self.context = context.RequestContext('userid', 'my_tenantid')
        setattr(self.context,
                'auth_token',
                'bff4a5a6b9eb4ea2a6efec6eefb77936')
        self.mocked_client = mock.Mock(spec=client.Client)
        self.stub_out('nova.network.neutronv2.api.get_client',
                      lambda context: self.mocked_client)

    def test_list_with_project(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        security_groups_list = {'security_groups': []}

        self.mocked_client.list_security_groups.return_value = (
            security_groups_list)
        sg_api = neutron_driver.SecurityGroupAPI()
        sg_api.list(self.context, project=project_id)

        self.mocked_client.list_security_groups.assert_called_once_with(
            tenant_id = project_id)

    def test_list_with_all_tenants_and_admin_context(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        search_opts = {'all_tenants': 1}
        security_groups_list = {'security_groups': []}
        admin_context = context.RequestContext('user1', project_id, True)

        with mock.patch.object(
                self.mocked_client,
                'list_security_groups',
                return_value=security_groups_list) as mock_list_secgroup:
            sg_api = neutron_driver.SecurityGroupAPI()
            sg_api.list(admin_context,
                        project=project_id,
                        search_opts=search_opts)

            mock_list_secgroup.assert_called_once_with()

    def test_list_without_all_tenants_and_admin_context(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        security_groups_list = {'security_groups': []}
        admin_context = context.RequestContext('user1', project_id, True)

        with mock.patch.object(
                self.mocked_client,
                'list_security_groups',
                return_value=security_groups_list) as mock_list_secgroup:
            sg_api = neutron_driver.SecurityGroupAPI()
            sg_api.list(admin_context, project=project_id)

            mock_list_secgroup.assert_called_once_with(tenant_id=project_id)

    def test_list_with_all_tenants_sec_name_and_admin_context(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        search_opts = {'all_tenants': 1}
        security_group_names = ['secgroup_ssh']
        security_groups_list = {'security_groups': []}
        admin_context = context.RequestContext('user1', project_id, True)

        with mock.patch.object(
                self.mocked_client,
                'list_security_groups',
                return_value=security_groups_list) as mock_list_secgroup:
            sg_api = neutron_driver.SecurityGroupAPI()
            sg_api.list(admin_context, project=project_id,
                        names=security_group_names,
                        search_opts=search_opts)

            mock_list_secgroup.assert_called_once_with(
                name=security_group_names,
                tenant_id=project_id)

    def test_list_with_all_tenants_sec_name_ids_and_admin_context(self):
        project_id = '0af70a4d22cf4652824ddc1f2435dd85'
        search_opts = {'all_tenants': 1}
        security_group_names = ['secgroup_ssh']
        security_group_ids = ['id1']
        security_groups_list = {'security_groups': []}
        admin_context = context.RequestContext('user1', project_id, True)

        with mock.patch.object(
                self.mocked_client,
                'list_security_groups',
                return_value=security_groups_list) as mock_list_secgroup:
            sg_api = neutron_driver.SecurityGroupAPI()
            sg_api.list(admin_context, project=project_id,
                        names=security_group_names,
                        ids=security_group_ids,
                        search_opts=search_opts)

            mock_list_secgroup.assert_called_once_with(
                name=security_group_names,
                id=security_group_ids,
                tenant_id=project_id)

    def test_list_with_all_tenants_not_admin(self):
        search_opts = {'all_tenants': 1}
        security_groups_list = {'security_groups': []}

        with mock.patch.object(
                self.mocked_client,
                'list_security_groups',
                return_value=security_groups_list) as mock_list_secgroup:
            sg_api = neutron_driver.SecurityGroupAPI()
            sg_api.list(self.context, project=self.context.project_id,
                        search_opts=search_opts)

            mock_list_secgroup.assert_called_once_with(
                tenant_id=self.context.tenant)

    def test_get_with_name_duplicated(self):
        sg_name = 'web_server'
        expected_sg_id = '85cc3048-abc3-43cc-89b3-377341426ac5'
        expected_sg = {'security_group': {'name': sg_name,
                                 'id': expected_sg_id,
                                 'tenant_id': self.context.project_id,
                                 'description': 'server', 'rules': []}}
        self.mocked_client.show_security_group.return_value = expected_sg

        sg_api = neutron_driver.SecurityGroupAPI()
        with mock.patch.object(neutronv20, 'find_resourceid_by_name_or_id',
                               return_value=expected_sg_id):
            observed_sg = sg_api.get(self.context, name=sg_name)
        expected_sg['security_group']['project_id'] = self.context.tenant
        del expected_sg['security_group']['tenant_id']
        self.assertEqual(expected_sg['security_group'], observed_sg)
        self.mocked_client.show_security_group.assert_called_once_with(
            expected_sg_id)

    def test_get_with_invalid_name(self):
        sg_name = 'invalid_name'
        expected_sg_id = '85cc3048-abc3-43cc-89b3-377341426ac5'
        self.mocked_client.show_security_group.side_effect = TypeError

        with mock.patch.object(neutronv20, 'find_resourceid_by_name_or_id',
                               return_value=expected_sg_id):
            sg_api = neutron_driver.SecurityGroupAPI()
            self.assertRaises(exception.SecurityGroupNotFound,
                              sg_api.get, self.context, name=sg_name)
        self.mocked_client.show_security_group.assert_called_once_with(
            expected_sg_id)

    def test_create_security_group_with_bad_request(self):
        name = 'test-security-group'
        description = None
        body = {'security_group': {'name': name,
                                   'description': description}}
        message = "Invalid input. Reason: 'None' is not a valid string."
        self.mocked_client.create_security_group.side_effect = (
            n_exc.BadRequest(message=message))

        sg_api = neutron_driver.SecurityGroupAPI()
        self.assertRaises(exception.Invalid,
                          sg_api.create_security_group, self.context, name,
                          description)
        self.mocked_client.create_security_group.assert_called_once_with(body)

    def test_create_security_group_exceed_quota(self):
        name = 'test-security-group'
        description = 'test-security-group'
        body = {'security_group': {'name': name,
                                   'description': description}}
        message = "Quota exceeded for resources: ['security_group']"
        self.mocked_client.create_security_group.side_effect = (
            n_exc.NeutronClientException(status_code=409, message=message))
        sg_api = neutron_driver.SecurityGroupAPI()
        self.assertRaises(exception.SecurityGroupLimitExceeded,
                          sg_api.create_security_group, self.context, name,
                          description)
        self.mocked_client.create_security_group.assert_called_once_with(body)

    def test_create_security_group_rules_exceed_quota(self):
        vals = {'protocol': 'tcp', 'cidr': '0.0.0.0/0',
                'parent_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'group_id': None, 'from_port': 1025, 'to_port': 1025}
        body = {'security_group_rules': [{'remote_group_id': None,
                'direction': 'ingress', 'protocol': 'tcp', 'ethertype': 'IPv4',
                'port_range_max': 1025, 'port_range_min': 1025,
                'security_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'remote_ip_prefix': '0.0.0.0/0'}]}
        name = 'test-security-group'
        message = "Quota exceeded for resources: ['security_group_rule']"
        self.mocked_client.create_security_group_rule.side_effect = (
            n_exc.NeutronClientException(status_code=409, message=message))
        sg_api = neutron_driver.SecurityGroupAPI()
        self.assertRaises(exception.SecurityGroupLimitExceeded,
                          sg_api.add_rules, self.context, None, name, [vals])
        self.mocked_client.create_security_group_rule.assert_called_once_with(
            body)

    def test_create_security_group_rules_bad_request(self):
        vals = {'protocol': 'icmp', 'cidr': '0.0.0.0/0',
                'parent_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'group_id': None, 'to_port': 255}
        body = {'security_group_rules': [{'remote_group_id': None,
                'direction': 'ingress', 'protocol': 'icmp',
                'ethertype': 'IPv4', 'port_range_max': 255,
                'security_group_id': '7ae75663-277e-4a0e-8f87-56ea4e70cb47',
                'remote_ip_prefix': '0.0.0.0/0'}]}
        name = 'test-security-group'
        message = "ICMP code (port-range-max) 255 is provided but ICMP type" \
                  " (port-range-min) is missing"
        self.mocked_client.create_security_group_rule.side_effect = (
            n_exc.NeutronClientException(status_code=400, message=message))
        sg_api = neutron_driver.SecurityGroupAPI()
        self.assertRaises(exception.Invalid, sg_api.add_rules,
                          self.context, None, name, [vals])
        self.mocked_client.create_security_group_rule.assert_called_once_with(
            body)

    def test_list_security_group_with_no_port_range_and_not_tcp_udp_icmp(self):
        sg1 = {'description': 'default',
               'id': '07f1362f-34f6-4136-819a-2dcde112269e',
               'name': 'default',
               'tenant_id': 'c166d9316f814891bcb66b96c4c891d6',
               'security_group_rules':
                   [{'direction': 'ingress',
                     'ethertype': 'IPv4',
                     'id': '0a4647f1-e1aa-488d-90e1-97a7d0293beb',
                      'port_range_max': None,
                      'port_range_min': None,
                      'protocol': '51',
                      'remote_group_id': None,
                      'remote_ip_prefix': None,
                      'security_group_id':
                           '07f1362f-34f6-4136-819a-2dcde112269e',
                      'tenant_id': 'c166d9316f814891bcb66b96c4c891d6'}]}

        self.mocked_client.list_security_groups.return_value = (
            {'security_groups': [sg1]})
        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.list(self.context)
        expected = [{'rules':
            [{'from_port': -1, 'protocol': '51', 'to_port': -1,
              'parent_group_id': '07f1362f-34f6-4136-819a-2dcde112269e',
              'cidr': '0.0.0.0/0', 'group_id': None,
              'id': '0a4647f1-e1aa-488d-90e1-97a7d0293beb'}],
            'project_id': 'c166d9316f814891bcb66b96c4c891d6',
            'id': '07f1362f-34f6-4136-819a-2dcde112269e',
            'name': 'default', 'description': 'default'}]
        self.assertEqual(expected, result)
        self.mocked_client.list_security_groups.assert_called_once_with()

    def test_instances_security_group_bindings(self):
        server_id = 'c5a20e8d-c4b0-47cf-9dca-ebe4f758acb1'
        port1_id = '4c505aec-09aa-47bc-bcc0-940477e84dc0'
        port2_id = 'b3b31a53-6e29-479f-ae5c-00b7b71a6d44'
        sg1_id = '2f7ce969-1a73-4ef9-bbd6-c9a91780ecd4'
        sg2_id = '20c89ce5-9388-4046-896e-64ffbd3eb584'
        servers = [{'id': server_id}]
        ports = [{'id': port1_id, 'device_id': server_id,
                  'security_groups': [sg1_id]},
                 {'id': port2_id, 'device_id': server_id,
                  'security_groups': [sg2_id]}]
        port_list = {'ports': ports}
        sg1 = {'id': sg1_id, 'name': 'wol'}
        sg2 = {'id': sg2_id, 'name': 'eor'}
        security_groups_list = {'security_groups': [sg1, sg2]}

        sg_bindings = {server_id: [{'name': 'wol'}, {'name': 'eor'}]}

        self.mocked_client.list_ports.return_value = port_list
        self.mocked_client.list_security_groups.return_value = (
            security_groups_list)

        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.get_instances_security_groups_bindings(
                                  self.context, servers)
        self.assertEqual(sg_bindings, result)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=[server_id])
        self.mocked_client.list_security_groups.assert_called_once_with(
            id=mock.ANY)
        self.assertEqual(sorted([sg1_id, sg2_id]),
            sorted(self.mocked_client.list_security_groups.call_args[1]['id']))

    def test_instances_security_group_bindings_port_not_found(self):
        server_id = 'c5a20e8d-c4b0-47cf-9dca-ebe4f758acb1'
        servers = [{'id': server_id}]

        self.mocked_client.list_ports.side_effect = n_exc.PortNotFoundClient()

        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.get_instances_security_groups_bindings(
                                  self.context, servers)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=[server_id])
        self.assertEqual({}, result)

    def _test_instances_security_group_bindings_scale(self, num_servers):
        max_query = 150
        sg1_id = '2f7ce969-1a73-4ef9-bbd6-c9a91780ecd4'
        sg2_id = '20c89ce5-9388-4046-896e-64ffbd3eb584'
        sg1 = {'id': sg1_id, 'name': 'wol'}
        sg2 = {'id': sg2_id, 'name': 'eor'}
        security_groups_list = {'security_groups': [sg1, sg2]}
        servers = []
        device_ids = []
        ports = []
        sg_bindings = {}
        for i in range(0, num_servers):
            server_id = "server-%d" % i
            port_id = "port-%d" % i
            servers.append({'id': server_id})
            device_ids.append(server_id)
            ports.append({'id': port_id,
                          'device_id': server_id,
                          'security_groups': [sg1_id, sg2_id]})
            sg_bindings[server_id] = [{'name': 'wol'}, {'name': 'eor'}]

        expected_args = []
        return_values = []
        for x in range(0, num_servers, max_query):
            expected_args.append(
                mock.call(device_id=device_ids[x:x + max_query]))
            return_values.append({'ports': ports[x:x + max_query]})

        self.mocked_client.list_security_groups.return_value = (
            security_groups_list)
        self.mocked_client.list_ports.side_effect = return_values

        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.get_instances_security_groups_bindings(
                                  self.context, servers)
        self.assertEqual(sg_bindings, result)
        self.mocked_client.list_security_groups.assert_called_once_with(
            id=mock.ANY)
        self.assertEqual(sorted([sg1_id, sg2_id]),
            sorted(self.mocked_client.list_security_groups.call_args[1]['id']))
        self.assertEqual(expected_args,
            self.mocked_client.list_ports.call_args_list)

    def test_instances_security_group_bindings_less_than_max(self):
        self._test_instances_security_group_bindings_scale(100)

    def test_instances_security_group_bindings_max(self):
        self._test_instances_security_group_bindings_scale(150)

    def test_instances_security_group_bindings_more_then_max(self):
        self._test_instances_security_group_bindings_scale(300)

    def test_instances_security_group_bindings_with_hidden_sg(self):
        servers = [{'id': 'server_1'}]
        ports = [{'id': '1', 'device_id': 'dev_1', 'security_groups': ['1']},
                 {'id': '2', 'device_id': 'dev_1', 'security_groups': ['2']}]
        port_list = {'ports': ports}
        sg1 = {'id': '1', 'name': 'wol'}
        # User doesn't have access to sg2
        security_groups_list = {'security_groups': [sg1]}

        sg_bindings = {'dev_1': [{'name': 'wol'}]}

        self.mocked_client.list_ports.return_value = port_list
        self.mocked_client.list_security_groups.return_value = (
            security_groups_list)

        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.get_instances_security_groups_bindings(
                                  self.context, servers)
        self.assertEqual(sg_bindings, result)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=['server_1'])
        self.mocked_client.list_security_groups.assert_called_once_with(
            id=mock.ANY)
        self.assertEqual(['1', '2'],
            sorted(self.mocked_client.list_security_groups.call_args[1]['id']))

    def test_instance_empty_security_groups(self):

        port_list = {'ports': [{'id': 1, 'device_id': uuids.instance,
                     'security_groups': []}]}
        self.mocked_client.list_ports.return_value = port_list
        sg_api = neutron_driver.SecurityGroupAPI()
        result = sg_api.get_instance_security_groups(
            self.context, objects.Instance(uuid=uuids.instance))
        self.assertEqual([], result)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=[uuids.instance])

    def test_add_to_instance(self):
        sg_name = 'web_server'
        sg_id = '85cc3048-abc3-43cc-89b3-377341426ac5'
        port_id = 1
        port_list = {'ports': [{'id': port_id, 'device_id': uuids.instance,
                     'fixed_ips': [{'ip_address': '10.0.0.1'}],
                     'port_security_enabled': True, 'security_groups': []}]}
        self.mocked_client.list_ports.return_value = port_list
        sg_api = neutron_driver.SecurityGroupAPI()
        with mock.patch.object(neutronv20, 'find_resourceid_by_name_or_id',
                               return_value=sg_id):
            sg_api.add_to_instance(
                self.context, objects.Instance(uuid=uuids.instance), sg_name)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=uuids.instance)
        self.mocked_client.update_port.assert_called_once_with(
            port_id, {'port': {'security_groups': [sg_id]}})

    def test_add_to_instance_with_bad_request(self):
        sg_name = 'web_server'
        sg_id = '85cc3048-abc3-43cc-89b3-377341426ac5'
        port_id = 1
        port_list = {'ports': [{'id': port_id, 'device_id': uuids.instance,
                     'fixed_ips': [{'ip_address': '10.0.0.1'}],
                     'port_security_enabled': True, 'security_groups': []}]}
        self.mocked_client.list_ports.return_value = port_list
        sg_api = neutron_driver.SecurityGroupAPI()
        self.mocked_client.update_port.side_effect = (
            n_exc.BadRequest(message='error'))
        with mock.patch.object(neutronv20, 'find_resourceid_by_name_or_id',
                               return_value=sg_id):
            self.assertRaises(exception.SecurityGroupCannotBeApplied,
                              sg_api.add_to_instance, self.context,
                              objects.Instance(uuid=uuids.instance), sg_name)
        self.mocked_client.list_ports.assert_called_once_with(
            device_id=uuids.instance)
        self.mocked_client.update_port.assert_called_once_with(
            port_id, {'port': {'security_groups': [sg_id]}})


class TestNeutronDriverWithoutMock(test.NoDBTestCase):

    def test_validate_property(self):
        sg_api = neutron_driver.SecurityGroupAPI()

        sg_api.validate_property('foo', 'name', None)
        sg_api.validate_property('', 'name', None)
        self.assertRaises(exception.Invalid, sg_api.validate_property,
                          'a' * 256, 'name', None)
        self.assertRaises(exception.Invalid, sg_api.validate_property,
                          None, 'name', None)

    def test_populate_security_groups(self):
        sg_api = neutron_driver.SecurityGroupAPI()
        r = sg_api.populate_security_groups(['default', uuids.secgroup_uuid])
        self.assertIsInstance(r, objects.SecurityGroupList)
        self.assertEqual(2, len(r))
        self.assertEqual('default', r[0].name)
        self.assertEqual(uuids.secgroup_uuid, r[1].uuid)

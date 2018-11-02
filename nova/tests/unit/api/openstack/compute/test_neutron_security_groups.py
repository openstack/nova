# Copyright 2013 Nicira, Inc.
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
import six

import mock
from neutronclient.common import exceptions as n_exc
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import webob

from nova.api.openstack.compute import security_groups
from nova import context
import nova.db.api
from nova import exception
from nova.network import model
from nova.network.neutronv2 import api as neutron_api
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack.compute import test_security_groups
from nova.tests.unit.api.openstack import fakes


UUID_SERVER = uuids.server


class TestNeutronSecurityGroupsTestCase(test.TestCase):
    def setUp(self):
        super(TestNeutronSecurityGroupsTestCase, self).setUp()
        cfg.CONF.set_override('use_neutron', True)
        self.original_client = neutron_api.get_client
        neutron_api.get_client = get_client

    def tearDown(self):
        neutron_api.get_client = self.original_client
        get_client()._reset()
        super(TestNeutronSecurityGroupsTestCase, self).tearDown()


class TestNeutronSecurityGroupsV21(
        test_security_groups.TestSecurityGroupsV21,
        TestNeutronSecurityGroupsTestCase):
    # Used to override set config in the base test in test_security_groups.
    use_neutron = True

    def _create_sg_template(self, **kwargs):
        sg = test_security_groups.security_group_request_template(**kwargs)
        return self.controller.create(self.req, body={'security_group': sg})

    def _create_network(self):
        body = {'network': {'name': 'net1'}}
        neutron = get_client()
        net = neutron.create_network(body)
        body = {'subnet': {'network_id': net['network']['id'],
                           'cidr': '10.0.0.0/24'}}
        neutron.create_subnet(body)
        return net

    def _create_port(self, **kwargs):
        body = {'port': {'binding:vnic_type': model.VNIC_TYPE_NORMAL}}
        fields = ['security_groups', 'device_id', 'network_id',
                  'port_security_enabled', 'ip_allocation']
        for field in fields:
            if field in kwargs:
                body['port'][field] = kwargs[field]
        neutron = get_client()
        return neutron.create_port(body)

    def _create_security_group(self, **kwargs):
        body = {'security_group': {}}
        fields = ['name', 'description']
        for field in fields:
            if field in kwargs:
                body['security_group'][field] = kwargs[field]
        neutron = get_client()
        return neutron.create_security_group(body)

    def test_create_security_group_with_no_description(self):
        # Neutron's security group description field is optional.
        pass

    def test_create_security_group_with_empty_description(self):
        # Neutron's security group description field is optional.
        pass

    def test_create_security_group_with_blank_name(self):
        # Neutron's security group name field is optional.
        pass

    def test_create_security_group_with_whitespace_name(self):
        # Neutron allows security group name to be whitespace.
        pass

    def test_create_security_group_with_blank_description(self):
        # Neutron's security group description field is optional.
        pass

    def test_create_security_group_with_whitespace_description(self):
        # Neutron allows description to be whitespace.
        pass

    def test_create_security_group_with_duplicate_name(self):
        # Neutron allows duplicate names for security groups.
        pass

    def test_create_security_group_non_string_name(self):
        # Neutron allows security group name to be non string.
        pass

    def test_create_security_group_non_string_description(self):
        # Neutron allows non string description.
        pass

    def test_create_security_group_quota_limit(self):
        # Enforced by Neutron server.
        pass

    def test_create_security_group_over_quota_during_recheck(self):
        # Enforced by Neutron server.
        pass

    def test_create_security_group_no_quota_recheck(self):
        # Enforced by Neutron server.
        pass

    def test_update_security_group(self):
        # Enforced by Neutron server.
        pass

    def test_get_security_group_list(self):
        self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        list_dict = self.controller.index(req)
        self.assertEqual(len(list_dict['security_groups']), 2)

    def test_get_security_group_list_offset_and_limit(self):
        path = '/v2/fake/os-security-groups?offset=1&limit=1'
        self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(path)
        list_dict = self.controller.index(req)
        self.assertEqual(len(list_dict['security_groups']), 1)

    def test_get_security_group_list_all_tenants(self):
        pass

    def test_get_security_group_by_instance(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=test_security_groups.UUID_SERVER)
        expected = [{'rules': [], 'tenant_id': 'fake', 'id': sg['id'],
                    'name': 'test', 'description': 'test-description'}]
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/os-security-groups'
                                      % test_security_groups.UUID_SERVER)
        res_dict = self.server_controller.index(
            req, test_security_groups.UUID_SERVER)['security_groups']
        self.assertEqual(expected, res_dict)

    def test_get_security_group_by_id(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s'
                                      % sg['id'])
        res_dict = self.controller.show(req, sg['id'])
        expected = {'security_group': sg}
        self.assertEqual(res_dict, expected)

    def test_delete_security_group_by_id(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s' %
                                      sg['id'])
        self.controller.delete(req, sg['id'])

    def test_delete_security_group_by_admin(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s' %
                                      sg['id'], use_admin_context=True)
        self.controller.delete(req, sg['id'])

    @mock.patch('nova.compute.utils.refresh_info_cache_for_instance')
    def test_delete_security_group_in_use(self, refresh_info_cache_mock):
        sg = self._create_sg_template().get('security_group')
        self._create_network()
        db_inst = fakes.stub_instance(id=1, nw_cache=[], security_groups=[])
        _context = context.get_admin_context()
        instance = instance_obj.Instance._from_db_object(
            _context, instance_obj.Instance(), db_inst,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        neutron = neutron_api.API()
        with mock.patch.object(nova.db.api, 'instance_get_by_uuid',
                               return_value=db_inst):
            neutron.allocate_for_instance(_context, instance, False, None,
                                          security_groups=[sg['id']])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s'
                                      % sg['id'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, sg['id'])

    def test_associate_non_running_instance(self):
        # Neutron does not care if the instance is running or not. When the
        # instances is detected by neutron it will push down the security
        # group policy to it.
        pass

    def test_associate_already_associated_security_group_to_instance(self):
        # Neutron security groups does not raise an error if you update a
        # port adding a security group to it that was already associated
        # to the port. This is because PUT semantics are used.
        pass

    def test_associate(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_associate_duplicate_names(self):
        sg1 = self._create_security_group(name='sg1',
                                          description='sg1')['security_group']
        self._create_security_group(name='sg1',
                                    description='sg1')['security_group']
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id']],
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="sg1"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.manager._addSecurityGroup,
                          req, UUID_SERVER, body)

    def test_associate_port_security_enabled_true(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            port_security_enabled=True,
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_associate_port_security_enabled_false(self):
        self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], port_security_enabled=False,
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup,
                          req, UUID_SERVER, body)

    def test_associate_deferred_ip_port(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            port_security_enabled=True, ip_allocation='deferred',
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_disassociate_by_non_existing_security_group_name(self):
        body = dict(removeSecurityGroup=dict(name='non-existing'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup,
                          req, UUID_SERVER, body)

    def test_disassociate_non_running_instance(self):
        # Neutron does not care if the instance is running or not. When the
        # instances is detected by neutron it will push down the security
        # group policy to it.
        pass

    def test_disassociate_already_associated_security_group_to_instance(self):
        # Neutron security groups does not raise an error if you update a
        # port adding a security group to it that was already associated
        # to the port. This is because PUT semantics are used.
        pass

    def test_disassociate(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=UUID_SERVER)

        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' %
                                      UUID_SERVER)
        self.manager._removeSecurityGroup(req, UUID_SERVER, body)

    def test_get_instances_security_groups_bindings(self):
        servers = [{'id': test_security_groups.FAKE_UUID1},
                   {'id': test_security_groups.FAKE_UUID2}]
        sg1 = self._create_sg_template(name='test1').get('security_group')
        sg2 = self._create_sg_template(name='test2').get('security_group')
        # test name='' is replaced with id
        sg3 = self._create_sg_template(name='').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id'],
                                                              sg2['id']],
            device_id=test_security_groups.FAKE_UUID1)
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg2['id'],
                                                              sg3['id']],
            device_id=test_security_groups.FAKE_UUID2)
        expected = {test_security_groups.FAKE_UUID1: [{'name': sg1['name']},
                                                      {'name': sg2['name']}],
                    test_security_groups.FAKE_UUID2: [{'name': sg2['name']},
                                                      {'name': sg3['id']}]}
        security_group_api = self.controller.security_group_api
        bindings = (
            security_group_api.get_instances_security_groups_bindings(
                context.get_admin_context(), servers))
        self.assertEqual(bindings, expected)

    def test_get_instance_security_groups(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        sg2 = self._create_sg_template(name='test2').get('security_group')
        # test name='' is replaced with id
        sg3 = self._create_sg_template(name='').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id'],
                                                              sg2['id'],
                                                              sg3['id']],
            device_id=test_security_groups.FAKE_UUID1)

        expected = [{'name': sg1['name']}, {'name': sg2['name']},
                    {'name': sg3['id']}]
        security_group_api = self.controller.security_group_api
        sgs = security_group_api.get_instance_security_groups(
            context.get_admin_context(),
            instance_obj.Instance(uuid=test_security_groups.FAKE_UUID1))
        self.assertEqual(sgs, expected)

    @mock.patch('nova.network.security_group.neutron_driver.SecurityGroupAPI.'
                'get_instances_security_groups_bindings')
    def test_get_security_group_empty_for_instance(self, neutron_sg_bind_mock):
        servers = [{'id': test_security_groups.FAKE_UUID1}]
        neutron_sg_bind_mock.return_value = {}

        security_group_api = self.controller.security_group_api
        ctx = context.get_admin_context()
        sgs = security_group_api.get_instance_security_groups(ctx,
                instance_obj.Instance(uuid=test_security_groups.FAKE_UUID1))

        neutron_sg_bind_mock.assert_called_once_with(ctx, servers, False)
        self.assertEqual([], sgs)

    def test_create_port_with_sg_and_port_security_enabled_true(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id']],
            port_security_enabled=True,
            device_id=test_security_groups.FAKE_UUID1)
        security_group_api = self.controller.security_group_api
        sgs = security_group_api.get_instance_security_groups(
            context.get_admin_context(),
            instance_obj.Instance(uuid=test_security_groups.FAKE_UUID1))
        self.assertEqual(sgs, [{'name': 'test1'}])

    def test_create_port_with_sg_and_port_security_enabled_false(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        net = self._create_network()
        self.assertRaises(exception.SecurityGroupCannotBeApplied,
                          self._create_port,
                           network_id=net['network']['id'],
                           security_groups=[sg1['id']],
                           port_security_enabled=False,
                           device_id=test_security_groups.FAKE_UUID1)


class TestNeutronSecurityGroupRulesTestCase(TestNeutronSecurityGroupsTestCase):
    def setUp(self):
        super(TestNeutronSecurityGroupRulesTestCase, self).setUp()
        id1 = '11111111-1111-1111-1111-111111111111'
        sg_template1 = test_security_groups.security_group_template(
            security_group_rules=[], id=id1)
        id2 = '22222222-2222-2222-2222-222222222222'
        sg_template2 = test_security_groups.security_group_template(
            security_group_rules=[], id=id2)
        self.controller_sg = security_groups.SecurityGroupController()
        neutron = get_client()
        neutron._fake_security_groups[id1] = sg_template1
        neutron._fake_security_groups[id2] = sg_template2

    def tearDown(self):
        neutron_api.get_client = self.original_client
        get_client()._reset()
        super(TestNeutronSecurityGroupsTestCase, self).tearDown()


class _TestNeutronSecurityGroupRulesBase(object):

    def test_create_add_existing_rules_by_cidr(self):
        sg = test_security_groups.security_group_template()
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.controller_sg.create(req, {'security_group': sg})
        rule = test_security_groups.security_group_rule_template(
            cidr='15.0.0.0/8', parent_group_id=self.sg2['id'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.controller.create(req, {'security_group_rule': rule})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_group_id(self):
        sg = test_security_groups.security_group_template()
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.controller_sg.create(req, {'security_group': sg})
        rule = test_security_groups.security_group_rule_template(
            group=self.sg1['id'], parent_group_id=self.sg2['id'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.controller.create(req, {'security_group_rule': rule})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_delete(self):
        rule = test_security_groups.security_group_rule_template(
            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules/%s'
                                      % security_group_rule['id'])
        self.controller.delete(req, security_group_rule['id'])

    def test_create_rule_quota_limit(self):
        # Enforced by neutron
        pass

    def test_create_rule_over_quota_during_recheck(self):
        # Enforced by neutron
        pass

    def test_create_rule_no_quota_recheck(self):
        # Enforced by neutron
        pass


class TestNeutronSecurityGroupRulesV21(
        _TestNeutronSecurityGroupRulesBase,
        test_security_groups.TestSecurityGroupRulesV21,
        TestNeutronSecurityGroupRulesTestCase):
    # Used to override set config in the base test in test_security_groups.
    use_neutron = True


class TestNeutronSecurityGroupsOutputTest(TestNeutronSecurityGroupsTestCase):
    content_type = 'application/json'

    def setUp(self):
        super(TestNeutronSecurityGroupsOutputTest, self).setUp()
        fakes.stub_out_nw_api(self)
        self.controller = security_groups.SecurityGroupController()
        self.stub_out('nova.compute.api.API.get',
                      test_security_groups.fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all',
                      test_security_groups.fake_compute_get_all)
        self.stub_out('nova.compute.api.API.create',
                      test_security_groups.fake_compute_create)
        self.stub_out(
            'nova.network.security_group.neutron_driver.SecurityGroupAPI.'
            'get_instances_security_groups_bindings',
            self._fake_get_instances_security_groups_bindings)

    def _fake_get_instances_security_groups_bindings(self, inst, context,
                                                     servers):
        groups = {
            '00000000-0000-0000-0000-000000000001': [{'name': 'fake-0-0'},
                                                     {'name': 'fake-0-1'}],
            '00000000-0000-0000-0000-000000000002': [{'name': 'fake-1-0'},
                                                     {'name': 'fake-1-1'}],
            '00000000-0000-0000-0000-000000000003': [{'name': 'fake-2-0'},
                                                     {'name': 'fake-2-1'}]}
        result = {}
        for server in servers:
            result[server['id']] = groups.get(server['id'])
        return result

    def _make_request(self, url, body=None):
        req = fakes.HTTPRequest.blank(url)
        if body:
            req.method = 'POST'
            req.body = encodeutils.safe_encode(self._encode_body(body))
        req.content_type = self.content_type
        req.headers['Accept'] = self.content_type

        # NOTE: This 'os-security-groups' is for enabling security_groups
        #       attribute on response body.
        res = req.get_response(fakes.wsgi_app_v21())
        return res

    def _encode_body(self, body):
        return jsonutils.dumps(body)

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def _get_groups(self, server):
        return server.get('security_groups')

    def test_create(self):
        url = '/v2/fake/servers'
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        security_groups = [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}]
        for security_group in security_groups:
            sg = test_security_groups.security_group_template(
                name=security_group['name'])
            self.controller.create(req, {'security_group': sg})

        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2,
                      security_groups=security_groups)
        res = self._make_request(url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_create_server_get_default_security_group(self):
        url = '/v2/fake/servers'
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        res = self._make_request(url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        group = self._get_groups(server)[0]
        self.assertEqual(group.get('name'), 'default')

    def test_show(self):
        self.stub_out('nova.network.security_group.neutron_driver.'
                      'SecurityGroupAPI.get_instance_security_groups',
                      lambda self, inst, context, id:
                          [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}])

        url = '/v2/fake/servers'
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        security_groups = [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}]
        for security_group in security_groups:
            sg = test_security_groups.security_group_template(
                name=security_group['name'])
            self.controller.create(req, {'security_group': sg})
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2,
                      security_groups=security_groups)

        res = self._make_request(url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

        # Test that show (GET) returns the same information as create (POST)
        url = '/v2/fake/servers/' + test_security_groups.UUID3
        res = self._make_request(url)
        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)

        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            for j, group in enumerate(self._get_groups(server)):
                name = 'fake-%s-%s' % (i, j)
                self.assertEqual(group.get('name'), name)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id='fake'))
    def test_no_instance_passthrough_404(self, mock_get):
        url = '/v2/fake/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


def get_client(context=None, admin=False):
    return MockClient()


class MockClient(object):

    # Needs to be global to survive multiple calls to get_client.
    _fake_security_groups = {}
    _fake_ports = {}
    _fake_networks = {}
    _fake_subnets = {}
    _fake_security_group_rules = {}

    def __init__(self):
        # add default security group
        if not len(self._fake_security_groups):
            ret = {'name': 'default', 'description': 'default',
                   'tenant_id': 'fake_tenant', 'security_group_rules': [],
                   'id': uuidutils.generate_uuid()}
            self._fake_security_groups[ret['id']] = ret

    def _reset(self):
        self._fake_security_groups.clear()
        self._fake_ports.clear()
        self._fake_networks.clear()
        self._fake_subnets.clear()
        self._fake_security_group_rules.clear()

    def create_security_group(self, body=None):
        s = body.get('security_group')
        if not isinstance(s.get('name', ''), six.string_types):
            msg = ('BadRequest: Invalid input for name. Reason: '
                   'None is not a valid string.')
            raise n_exc.BadRequest(message=msg)
        if not isinstance(s.get('description.', ''), six.string_types):
            msg = ('BadRequest: Invalid input for description. Reason: '
                   'None is not a valid string.')
            raise n_exc.BadRequest(message=msg)
        if len(s.get('name')) > 255 or len(s.get('description')) > 255:
            msg = 'Security Group name great than 255'
            raise n_exc.NeutronClientException(message=msg, status_code=401)
        ret = {'name': s.get('name'), 'description': s.get('description'),
               'tenant_id': 'fake', 'security_group_rules': [],
               'id': uuidutils.generate_uuid()}

        self._fake_security_groups[ret['id']] = ret
        return {'security_group': ret}

    def create_network(self, body):
        n = body.get('network')
        ret = {'status': 'ACTIVE', 'subnets': [], 'name': n.get('name'),
               'admin_state_up': n.get('admin_state_up', True),
               'tenant_id': 'fake_tenant',
               'id': uuidutils.generate_uuid()}
        if 'port_security_enabled' in n:
            ret['port_security_enabled'] = n['port_security_enabled']
        self._fake_networks[ret['id']] = ret
        return {'network': ret}

    def create_subnet(self, body):
        s = body.get('subnet')
        try:
            net = self._fake_networks[s.get('network_id')]
        except KeyError:
            msg = 'Network %s not found' % s.get('network_id')
            raise n_exc.NeutronClientException(message=msg, status_code=404)
        ret = {'name': s.get('name'), 'network_id': s.get('network_id'),
               'tenant_id': 'fake_tenant', 'cidr': s.get('cidr'),
               'id': uuidutils.generate_uuid(), 'gateway_ip': '10.0.0.1'}
        net['subnets'].append(ret['id'])
        self._fake_networks[net['id']] = net
        self._fake_subnets[ret['id']] = ret
        return {'subnet': ret}

    def create_port(self, body):
        p = body.get('port')
        ret = {'status': 'ACTIVE', 'id': uuidutils.generate_uuid(),
               'mac_address': p.get('mac_address', 'fa:16:3e:b8:f5:fb'),
               'device_id': p.get('device_id', uuidutils.generate_uuid()),
               'admin_state_up': p.get('admin_state_up', True),
               'security_groups': p.get('security_groups', []),
               'network_id': p.get('network_id'),
               'ip_allocation': p.get('ip_allocation'),
               'binding:vnic_type':
                   p.get('binding:vnic_type') or model.VNIC_TYPE_NORMAL}

        network = self._fake_networks[p['network_id']]
        if 'port_security_enabled' in p:
            ret['port_security_enabled'] = p['port_security_enabled']
        elif 'port_security_enabled' in network:
            ret['port_security_enabled'] = network['port_security_enabled']

        port_security = ret.get('port_security_enabled', True)
        # port_security must be True if security groups are present
        if not port_security and ret['security_groups']:
            raise exception.SecurityGroupCannotBeApplied()

        if network['subnets'] and p.get('ip_allocation') != 'deferred':
            ret['fixed_ips'] = [{'subnet_id': network['subnets'][0],
                                 'ip_address': '10.0.0.1'}]
        if not ret['security_groups'] and (port_security is None or
                                           port_security is True):
            for security_group in self._fake_security_groups.values():
                if security_group['name'] == 'default':
                    ret['security_groups'] = [security_group['id']]
                    break
        self._fake_ports[ret['id']] = ret
        return {'port': ret}

    def create_security_group_rule(self, body):
        # does not handle bulk case so just picks rule[0]
        r = body.get('security_group_rules')[0]
        fields = ['direction', 'protocol', 'port_range_min', 'port_range_max',
                  'ethertype', 'remote_ip_prefix', 'tenant_id',
                  'security_group_id', 'remote_group_id']
        ret = {}
        for field in fields:
            ret[field] = r.get(field)
        ret['id'] = uuidutils.generate_uuid()
        self._fake_security_group_rules[ret['id']] = ret
        return {'security_group_rules': [ret]}

    def show_security_group(self, security_group, **_params):
        try:
            sg = self._fake_security_groups[security_group]
        except KeyError:
            msg = 'Security Group %s not found' % security_group
            raise n_exc.NeutronClientException(message=msg, status_code=404)
        for security_group_rule in self._fake_security_group_rules.values():
            if security_group_rule['security_group_id'] == sg['id']:
                sg['security_group_rules'].append(security_group_rule)

        return {'security_group': sg}

    def show_security_group_rule(self, security_group_rule, **_params):
        try:
            return {'security_group_rule':
                    self._fake_security_group_rules[security_group_rule]}
        except KeyError:
            msg = 'Security Group rule %s not found' % security_group_rule
            raise n_exc.NeutronClientException(message=msg, status_code=404)

    def show_network(self, network, **_params):
        try:
            return {'network':
                    self._fake_networks[network]}
        except KeyError:
            msg = 'Network %s not found' % network
            raise n_exc.NeutronClientException(message=msg, status_code=404)

    def show_port(self, port, **_params):
        try:
            return {'port':
                    self._fake_ports[port]}
        except KeyError:
            msg = 'Port %s not found' % port
            raise n_exc.NeutronClientException(message=msg, status_code=404)

    def show_subnet(self, subnet, **_params):
        try:
            return {'subnet':
                    self._fake_subnets[subnet]}
        except KeyError:
            msg = 'Port %s not found' % subnet
            raise n_exc.NeutronClientException(message=msg, status_code=404)

    def list_security_groups(self, **_params):
        ret = []
        for security_group in self._fake_security_groups.values():
            names = _params.get('name')
            if names:
                if not isinstance(names, list):
                    names = [names]
                for name in names:
                    if security_group.get('name') == name:
                        ret.append(security_group)
            ids = _params.get('id')
            if ids:
                if not isinstance(ids, list):
                    ids = [ids]
                for id in ids:
                    if security_group.get('id') == id:
                        ret.append(security_group)
            elif not (names or ids):
                ret.append(security_group)
        return {'security_groups': ret}

    def list_networks(self, **_params):
        # neutronv2/api.py _get_available_networks calls this assuming
        # search_opts filter "shared" is implemented and not ignored
        shared = _params.get("shared", None)
        if shared:
            return {'networks': []}
        else:
            return {'networks':
                 [network for network in self._fake_networks.values()]}

    def list_ports(self, **_params):
        ret = []
        device_id = _params.get('device_id')
        for port in self._fake_ports.values():
            if device_id:
                if port['device_id'] in device_id:
                    ret.append(port)
            else:
                ret.append(port)
        return {'ports': ret}

    def list_subnets(self, **_params):
        return {'subnets':
                [subnet for subnet in self._fake_subnets.values()]}

    def list_floatingips(self, **_params):
        return {'floatingips': []}

    def delete_security_group(self, security_group):
        self.show_security_group(security_group)
        ports = self.list_ports()
        for port in ports.get('ports'):
            for sg_port in port['security_groups']:
                if sg_port == security_group:
                    msg = ('Unable to delete Security group %s in use'
                           % security_group)
                    raise n_exc.NeutronClientException(message=msg,
                                                       status_code=409)
        del self._fake_security_groups[security_group]

    def delete_security_group_rule(self, security_group_rule):
        self.show_security_group_rule(security_group_rule)
        del self._fake_security_group_rules[security_group_rule]

    def delete_network(self, network):
        self.show_network(network)
        self._check_ports_on_network(network)
        for subnet in self._fake_subnets.values():
            if subnet['network_id'] == network:
                del self._fake_subnets[subnet['id']]
        del self._fake_networks[network]

    def delete_port(self, port):
        self.show_port(port)
        del self._fake_ports[port]

    def update_port(self, port, body=None):
        self.show_port(port)
        self._fake_ports[port].update(body['port'])
        return {'port': self._fake_ports[port]}

    def list_extensions(self, **_parms):
        return {'extensions': []}

    def _check_ports_on_network(self, network):
        ports = self.list_ports()
        for port in ports:
            if port['network_id'] == network:
                msg = ('Unable to complete operation on network %s. There is '
                       'one or more ports still in use on the network'
                       % network)
            raise n_exc.NeutronClientException(message=msg, status_code=409)

    def find_resource(self, resource, name_or_id, project_id=None,
                      cmd_resource=None, parent_id=None, fields=None):
        if resource == 'security_group':
            # lookup first by unique id
            sg = self._fake_security_groups.get(name_or_id)
            if sg:
                return sg
            # lookup by name, raise an exception on duplicates
            res = None
            for sg in self._fake_security_groups.values():
                if sg['name'] == name_or_id:
                    if res:
                        raise n_exc.NeutronClientNoUniqueMatch(
                            resource=resource, name=name_or_id)
                    res = sg
            if res:
                return res
        raise n_exc.NotFound("Fake %s '%s' not found." %
                             (resource, name_or_id))

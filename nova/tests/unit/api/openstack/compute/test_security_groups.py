# Copyright 2011 OpenStack Foundation
# Copyright 2012 Justin Santa Barbara
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

import mock
from neutronclient.common import exceptions as n_exc
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import six
import webob

from nova.api.openstack.compute import security_groups as secgroups_v21
from nova import context as context_maker
import nova.db.api
from nova import exception
from nova.network import model
from nova.network import neutron as neutron_api
from nova.network import security_group_api
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF
FAKE_UUID1 = 'a47ae74e-ab08-447f-8eee-ffd43fc46c16'
FAKE_UUID2 = 'c6e6430a-6563-4efa-9542-5e93c9e97d18'
UUID_SERVER = uuids.server


class AttrDict(dict):
    def __getattr__(self, k):
        return self[k]


def security_group_request_template(**kwargs):
    sg = kwargs.copy()
    sg.setdefault('name', 'test')
    sg.setdefault('description', 'test-description')
    return sg


def security_group_template(**kwargs):
    sg = kwargs.copy()
    sg.setdefault('tenant_id', '123')
    sg.setdefault('name', 'test')
    sg.setdefault('description', 'test-description')
    return sg


def security_group_db(security_group, id=None):
    attrs = security_group.copy()
    if 'tenant_id' in attrs:
        attrs['project_id'] = attrs.pop('tenant_id')
    if id is not None:
        attrs['id'] = id
    attrs.setdefault('rules', [])
    attrs.setdefault('instances', [])
    return AttrDict(attrs)


def security_group_rule_template(**kwargs):
    rule = kwargs.copy()
    rule.setdefault('ip_protocol', 'tcp')
    rule.setdefault('from_port', 22)
    rule.setdefault('to_port', 22)
    rule.setdefault('parent_group_id', 2)
    return rule


def security_group_rule_db(rule, id=None):
    attrs = rule.copy()
    if 'ip_protocol' in attrs:
        attrs['protocol'] = attrs.pop('ip_protocol')
    return AttrDict(attrs)


def return_security_group_by_name(context, project_id, group_name,
                                  columns_to_join=None):
    return {'id': 1, 'name': group_name,
            "instances": [{'id': 1, 'uuid': UUID_SERVER}]}


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
                   'tenant_id': fakes.FAKE_PROJECT_ID,
                   'security_group_rules': [],
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
               'tenant_id': fakes.FAKE_PROJECT_ID, 'security_group_rules': [],
               'id': uuidutils.generate_uuid()}

        self._fake_security_groups[ret['id']] = ret
        return {'security_group': ret}

    def create_network(self, body):
        n = body.get('network')
        ret = {'status': 'ACTIVE', 'subnets': [], 'name': n.get('name'),
               'admin_state_up': n.get('admin_state_up', True),
               'tenant_id': fakes.FAKE_PROJECT_ID,
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
               'tenant_id': fakes.FAKE_PROJECT_ID, 'cidr': s.get('cidr'),
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
        # network/api.py _get_available_networks calls this assuming
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


def get_client(context=None, admin=False):
    return MockClient()


class TestSecurityGroupsV21(test.TestCase):
    secgrp_ctl_cls = secgroups_v21.SecurityGroupController
    server_secgrp_ctl_cls = secgroups_v21.ServerSecurityGroupController
    secgrp_act_ctl_cls = secgroups_v21.SecurityGroupActionController

    def setUp(self):
        super(TestSecurityGroupsV21, self).setUp()

        self.controller = self.secgrp_ctl_cls()
        self.server_controller = self.server_secgrp_ctl_cls()
        self.manager = self.secgrp_act_ctl_cls()

        # This needs to be done here to set fake_id because the derived
        # class needs to be called first if it wants to set
        # 'security_group_api' and this setUp method needs to be called.
        self.fake_id = '11111111-1111-1111-1111-111111111111'

        self.req = fakes.HTTPRequest.blank('')
        project_id = self.req.environ['nova.context'].project_id
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(
                          **{'power_state': 0x01,
                             'host': "localhost",
                             'uuid': UUID_SERVER,
                             'name': 'asdf',
                             'project_id': project_id}))

        self.original_client = neutron_api.get_client
        neutron_api.get_client = get_client

    def tearDown(self):
        neutron_api.get_client = self.original_client
        get_client()._reset()
        super(TestSecurityGroupsV21, self).tearDown()

    def _create_sg_template(self, **kwargs):
        sg = security_group_request_template(**kwargs)
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

    def _assert_security_groups_in_use(self, project_id, user_id, in_use):
        context = context_maker.get_admin_context()
        count = objects.Quotas.count_as_dict(context, 'security_groups',
                                             project_id, user_id)
        self.assertEqual(in_use, count['project']['security_groups'])
        self.assertEqual(in_use, count['user']['security_groups'])

    def test_create_security_group(self):
        sg = security_group_request_template()

        res_dict = self.controller.create(self.req, {'security_group': sg})
        self.assertEqual(res_dict['security_group']['name'], 'test')
        self.assertEqual(res_dict['security_group']['description'],
                         'test-description')

    def test_create_security_group_with_no_name(self):
        sg = security_group_request_template()
        del sg['name']

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req,
                          {'security_group': sg})

    def test_create_security_group_with_no_body(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, None)

    def test_create_security_group_with_no_security_group(self):
        body = {'no-securityGroup': None}

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body)

    def test_create_security_group_above_255_characters_name(self):
        sg = security_group_request_template(name='1234567890' * 26)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_above_255_characters_description(self):
        sg = security_group_request_template(description='1234567890' * 26)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_get_security_group_list(self):
        self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups' % fakes.FAKE_PROJECT_ID)
        list_dict = self.controller.index(req)
        self.assertEqual(len(list_dict['security_groups']), 2)

    def test_get_security_group_list_offset_and_limit(self):
        path = ('/v2/%s/os-security-groups?offset=1&limit=1' %
                fakes.FAKE_PROJECT_ID)
        self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(path)
        list_dict = self.controller.index(req)
        self.assertEqual(len(list_dict['security_groups']), 1)

    def test_get_security_group_list_missing_group_id_rule(self):
        groups = []
        rule1 = security_group_rule_template(cidr='10.2.3.124/24',
                                             parent_group_id=1,
                                             group_id={}, id=88,
                                             protocol='TCP')
        rule2 = security_group_rule_template(cidr='10.2.3.125/24',
                                             parent_group_id=1,
                                             id=99, protocol=88,
                                             group_id='HAS_BEEN_DELETED')
        sg = security_group_template(id=1,
                                     name='test',
                                     description='test-desc',
                                     rules=[rule1, rule2])

        groups.append(sg)
        # An expected rule here needs to be created as the api returns
        # different attributes on the rule for a response than what was
        # passed in. For example:
        #  "cidr": "0.0.0.0/0" ->"ip_range": {"cidr": "0.0.0.0/0"}
        expected_rule = security_group_rule_template(
            ip_range={'cidr': '10.2.3.124/24'}, parent_group_id=1,
            group={}, id=88, ip_protocol='TCP')
        expected = security_group_template(id=1,
                                     name='test',
                                     description='test-desc',
                                     rules=[expected_rule])

        expected = {'security_groups': [expected]}

        with mock.patch(
                'nova.network.security_group_api.list',
                return_value=[
                    security_group_db(
                        secgroup) for secgroup in groups]) as mock_list:
            res_dict = self.controller.index(self.req)

        self.assertEqual(res_dict, expected)
        mock_list.assert_called_once_with(self.req.environ['nova.context'],
                                          project=fakes.FAKE_PROJECT_ID,
                                          search_opts={})

    def test_get_security_group_by_instance(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=UUID_SERVER)
        expected = [{'rules': [], 'tenant_id': fakes.FAKE_PROJECT_ID,
                     'id': sg['id'], 'name': 'test',
                     'description': 'test-description'}]
        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/os-security-groups'
                % (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        res_dict = self.server_controller.index(
            req, UUID_SERVER)['security_groups']
        self.assertEqual(expected, res_dict)

    @mock.patch('nova.network.security_group_api.'
                'get_instances_security_groups_bindings')
    def test_get_security_group_empty_for_instance(self, neutron_sg_bind_mock):
        servers = [{'id': FAKE_UUID1}]
        neutron_sg_bind_mock.return_value = {}

        ctx = context_maker.get_admin_context()
        sgs = security_group_api.get_instance_security_groups(ctx,
                instance_obj.Instance(uuid=FAKE_UUID1))

        neutron_sg_bind_mock.assert_called_once_with(ctx, servers, False)
        self.assertEqual([], sgs)

    def test_get_security_group_by_instance_non_existing(self):
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id='1')):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.server_controller.index, self.req, '1')

    def test_get_security_group_by_id(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups/%s'
                % (fakes.FAKE_PROJECT_ID, sg['id']))
        res_dict = self.controller.show(req, sg['id'])
        expected = {'security_group': sg}
        self.assertEqual(res_dict, expected)

    def test_get_security_group_by_invalid_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_get_security_group_by_non_existing_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.fake_id)

    def test_update_default_security_group_fail(self):
        sg = security_group_template()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, '1', {'security_group': sg})

    def test_delete_security_group_by_id(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups/%s' %
                (fakes.FAKE_PROJECT_ID, sg['id']))
        self.controller.delete(req, sg['id'])

    def test_delete_security_group_by_admin(self):
        sg = self._create_sg_template().get('security_group')
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups/%s' %
                (fakes.FAKE_PROJECT_ID, sg['id']), use_admin_context=True)
        self.controller.delete(req, sg['id'])

    def test_delete_security_group_by_invalid_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_delete_security_group_by_non_existing_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.fake_id)

    @mock.patch('nova.compute.utils.refresh_info_cache_for_instance')
    def test_delete_security_group_in_use(self, refresh_info_cache_mock):
        sg = self._create_sg_template().get('security_group')
        self._create_network()
        db_inst = fakes.stub_instance(id=1, nw_cache=[], security_groups=[])
        _context = context_maker.get_admin_context()
        instance = instance_obj.Instance._from_db_object(
            _context, instance_obj.Instance(), db_inst,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)
        neutron = neutron_api.API()
        with mock.patch.object(nova.db.api, 'instance_get_by_uuid',
                               return_value=db_inst):
            neutron.allocate_for_instance(_context, instance, False, None,
                                          security_groups=[sg['id']])

        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups/%s'
                % (fakes.FAKE_PROJECT_ID, sg['id']))
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, sg['id'])

    def _test_list_with_invalid_filter(
        self, url, expected_exception=exception.ValidationError):
        prefix = '/os-security-groups'
        req = fakes.HTTPRequest.blank(prefix + url)
        self.assertRaises(expected_exception,
                          self.controller.index, req)

    def test_list_with_invalid_non_int_limit(self):
        self._test_list_with_invalid_filter('?limit=-9')

    def test_list_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('?limit=abc')

    def test_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter(
            '?limit=1&limit=abc')

    def test_list_with_invalid_non_int_offset(self):
        self._test_list_with_invalid_filter('?offset=-9')

    def test_list_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('?offset=abc')

    def test_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter(
            '?offset=1&offset=abc')

    def test_list_duplicate_query_parameters_validation(self):
        params = {
            'limit': 1,
            'offset': 1,
            'all_tenants': 1
        }

        for param, value in params.items():
            req = fakes.HTTPRequest.blank(
                '/os-security-groups' + '?%s=%s&%s=%s' %
                (param, value, param, value))
            self.controller.index(req)

    def test_list_with_additional_filter(self):
        req = fakes.HTTPRequest.blank(
            '/os-security-groups?limit=1&offset=1&additional=something')
        self.controller.index(req)

    def test_list_all_tenants_filter_as_string(self):
        req = fakes.HTTPRequest.blank(
            '/os-security-groups?all_tenants=abc')
        self.controller.index(req)

    def test_list_all_tenants_filter_as_positive_int(self):
        req = fakes.HTTPRequest.blank(
            '/os-security-groups?all_tenants=1')
        self.controller.index(req)

    def test_list_all_tenants_filter_as_negative_int(self):
        req = fakes.HTTPRequest.blank(
            '/os-security-groups?all_tenants=-1')
        self.controller.index(req)

    def test_associate_by_non_existing_security_group_name(self):
        body = dict(addSecurityGroup=dict(name='non-existing'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_without_body(self):
        body = dict(addSecurityGroup=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_no_security_group_name(self):
        body = dict(addSecurityGroup=dict())

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_security_group_name_with_whitespaces(self):
        body = dict(addSecurityGroup=dict(name="   "))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_non_existing_instance(self):
        body = dict(addSecurityGroup=dict(name="test"))
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id='1')):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.manager._addSecurityGroup,
                              self.req, '1', body)

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

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
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

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_associate_port_security_enabled_false(self):
        self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], port_security_enabled=False,
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
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

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_associate(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=UUID_SERVER)

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        self.manager._addSecurityGroup(req, UUID_SERVER, body)

    def test_disassociate_by_non_existing_security_group_name(self):
        body = dict(removeSecurityGroup=dict(name='non-existing'))

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup,
                          req, UUID_SERVER, body)

    def test_disassociate_without_body(self):
        body = dict(removeSecurityGroup=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_no_security_group_name(self):
        body = dict(removeSecurityGroup=dict())

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_security_group_name_with_whitespaces(self):
        body = dict(removeSecurityGroup=dict(name="   "))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_non_existing_instance(self):
        body = dict(removeSecurityGroup=dict(name="test"))
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id='1')):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.manager._removeSecurityGroup,
                              self.req, '1', body)

    def test_disassociate(self):
        sg = self._create_sg_template().get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg['id']],
            device_id=UUID_SERVER)

        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank(
                '/v2/%s/servers/%s/action' %
                (fakes.FAKE_PROJECT_ID, UUID_SERVER))
        self.manager._removeSecurityGroup(req, UUID_SERVER, body)

    def test_get_instances_security_groups_bindings(self):
        servers = [{'id': FAKE_UUID1}, {'id': FAKE_UUID2}]
        sg1 = self._create_sg_template(name='test1').get('security_group')
        sg2 = self._create_sg_template(name='test2').get('security_group')
        # test name='' is replaced with id
        sg3 = self._create_sg_template(name='').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id'],
                                                              sg2['id']],
            device_id=FAKE_UUID1)
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg2['id'],
                                                              sg3['id']],
            device_id=FAKE_UUID2)
        expected = {FAKE_UUID1: [{'name': sg1['name']}, {'name': sg2['name']}],
                    FAKE_UUID2: [{'name': sg2['name']}, {'name': sg3['id']}]}
        bindings = security_group_api.get_instances_security_groups_bindings(
                context_maker.get_admin_context(), servers)
        self.assertEqual(bindings, expected)

    def test_get_instance_security_groups(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        sg2 = self._create_sg_template(name='test2').get('security_group')
        # test name='' is replaced with id
        sg3 = self._create_sg_template(name='').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'],
            security_groups=[sg1['id'], sg2['id'], sg3['id']],
            device_id=FAKE_UUID1)

        expected = [{'name': sg1['name']}, {'name': sg2['name']},
                    {'name': sg3['id']}]
        sgs = security_group_api.get_instance_security_groups(
            context_maker.get_admin_context(),
            instance_obj.Instance(uuid=FAKE_UUID1))
        self.assertEqual(sgs, expected)

    def test_create_port_with_sg_and_port_security_enabled_true(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        net = self._create_network()
        self._create_port(
            network_id=net['network']['id'], security_groups=[sg1['id']],
            port_security_enabled=True,
            device_id=FAKE_UUID1)
        sgs = security_group_api.get_instance_security_groups(
            context_maker.get_admin_context(),
            instance_obj.Instance(uuid=FAKE_UUID1))
        self.assertEqual(sgs, [{'name': 'test1'}])

    def test_create_port_with_sg_and_port_security_enabled_false(self):
        sg1 = self._create_sg_template(name='test1').get('security_group')
        net = self._create_network()
        self.assertRaises(exception.SecurityGroupCannotBeApplied,
                          self._create_port,
                          network_id=net['network']['id'],
                          security_groups=[sg1['id']],
                          port_security_enabled=False,
                          device_id=FAKE_UUID1)


class TestSecurityGroupRulesV21(test.TestCase):
    secgrp_ctl_cls = secgroups_v21.SecurityGroupRulesController

    def setUp(self):
        super(TestSecurityGroupRulesV21, self).setUp()
        self.controller = self.secgrp_ctl_cls()
        self.controller_sg = secgroups_v21.SecurityGroupController()

        id1 = '11111111-1111-1111-1111-111111111111'
        id2 = '22222222-2222-2222-2222-222222222222'
        self.invalid_id = '33333333-3333-3333-3333-333333333333'

        self.sg1 = security_group_template(
            id=id1, security_group_rules=[])
        self.sg2 = security_group_template(
            id=id2, security_group_rules=[], name='authorize_revoke',
            description='authorize-revoke testing')

        self.parent_security_group = security_group_db(self.sg2)
        self.req = fakes.HTTPRequest.blank('')

        self.original_client = neutron_api.get_client
        neutron_api.get_client = get_client

        neutron = get_client()
        neutron._fake_security_groups[id1] = self.sg1
        neutron._fake_security_groups[id2] = self.sg2

    def tearDown(self):
        neutron_api.get_client = self.original_client
        get_client()._reset()
        super(TestSecurityGroupRulesV21, self).tearDown()

    def test_create_by_cidr(self):
        rule = security_group_rule_template(cidr='10.2.3.124/24',
                                            parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg2['id'])
        self.assertEqual(security_group_rule['ip_range']['cidr'],
                         "10.2.3.124/24")

    def test_create_by_group_id(self):
        rule = security_group_rule_template(group_id=self.sg1['id'],
                                            parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg2['id'])

    def test_create_by_same_group_id(self):
        rule1 = security_group_rule_template(group_id=self.sg1['id'],
                                             from_port=80, to_port=80,
                                             parent_group_id=self.sg2['id'])
        self.parent_security_group['rules'] = [security_group_rule_db(rule1)]

        rule2 = security_group_rule_template(group_id=self.sg1['id'],
                                             from_port=81, to_port=81,
                                             parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule2})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg2['id'])
        self.assertEqual(security_group_rule['from_port'], 81)
        self.assertEqual(security_group_rule['to_port'], 81)

    def test_create_none_value_from_to_port(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id']}
        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertIsNone(security_group_rule['from_port'])
        self.assertIsNone(security_group_rule['to_port'])
        self.assertEqual(security_group_rule['group']['name'], 'test')
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg1['id'])

    def test_create_none_value_from_to_port_icmp(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id'],
                'ip_protocol': 'ICMP'}
        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertEqual(security_group_rule['ip_protocol'], 'ICMP')
        self.assertEqual(security_group_rule['from_port'], -1)
        self.assertEqual(security_group_rule['to_port'], -1)
        self.assertEqual(security_group_rule['group']['name'], 'test')
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg1['id'])

    def test_create_none_value_from_to_port_tcp(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id'],
                'ip_protocol': 'TCP'}
        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertEqual(security_group_rule['ip_protocol'], 'TCP')
        self.assertEqual(security_group_rule['from_port'], 1)
        self.assertEqual(security_group_rule['to_port'], 65535)
        self.assertEqual(security_group_rule['group']['name'], 'test')
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg1['id'])

    def test_create_by_invalid_cidr_json(self):
        rule = security_group_rule_template(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/2433")
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_by_invalid_tcp_port_json(self):
        rule = security_group_rule_template(
                ip_protocol="tcp",
                from_port=75534,
                to_port=22,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/24")

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_by_invalid_icmp_port_json(self):
        rule = security_group_rule_template(
                ip_protocol="icmp",
                from_port=1,
                to_port=256,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/24")
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_cidr(self):
        sg = security_group_template()
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups' % fakes.FAKE_PROJECT_ID)
        self.controller_sg.create(req, {'security_group': sg})
        rule = security_group_rule_template(
            cidr='15.0.0.0/8', parent_group_id=self.sg2['id'])
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-group-rules' % fakes.FAKE_PROJECT_ID)
        self.controller.create(req, {'security_group_rule': rule})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_group_id(self):
        sg = security_group_template()
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups' % fakes.FAKE_PROJECT_ID)
        self.controller_sg.create(req, {'security_group': sg})
        rule = security_group_rule_template(
            group=self.sg1['id'], parent_group_id=self.sg2['id'])
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-group-rules' % fakes.FAKE_PROJECT_ID)
        self.controller.create(req, {'security_group_rule': rule})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_body(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, None)

    def test_create_with_no_security_group_rule_in_body(self):
        rules = {'test': 'test'}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, rules)

    def test_create_with_invalid_parent_group_id(self):
        rule = security_group_rule_template(parent_group_id='invalid')

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_non_existing_parent_group_id(self):
        rule = security_group_rule_template(group_id=None,
                                            parent_group_id=self.invalid_id)

        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_non_existing_group_id(self):
        rule = security_group_rule_template(group_id='invalid',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_invalid_protocol(self):
        rule = security_group_rule_template(ip_protocol='invalid-protocol',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_no_protocol(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['ip_protocol']

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_invalid_from_port(self):
        rule = security_group_rule_template(from_port='666666',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_invalid_to_port(self):
        rule = security_group_rule_template(to_port='666666',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_non_numerical_from_port(self):
        rule = security_group_rule_template(from_port='invalid',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_non_numerical_to_port(self):
        rule = security_group_rule_template(to_port='invalid',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_no_from_port(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['from_port']

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_no_to_port(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['to_port']

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_invalid_cidr(self):
        rule = security_group_rule_template(cidr='10.2.2222.0/24',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_no_cidr_group(self):
        rule = security_group_rule_template(parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.parent_security_group['id'])
        self.assertEqual(security_group_rule['ip_range']['cidr'],
                         "0.0.0.0/0")

    def test_create_with_invalid_group_id(self):
        rule = security_group_rule_template(group_id='invalid',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_empty_group_id(self):
        rule = security_group_rule_template(group_id='',
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_nonexist_group_id(self):
        rule = security_group_rule_template(group_id=self.invalid_id,
                                            parent_group_id=self.sg2['id'])

        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_with_same_group_parent_id_and_group_id(self):
        rule = security_group_rule_template(group_id=self.sg1['id'],
                                            parent_group_id=self.sg1['id'])
        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.sg1['id'])
        self.assertEqual(security_group_rule['group']['name'],
                         self.sg1['name'])

    def _test_create_with_no_ports_and_no_group(self, proto):
        rule = {'ip_protocol': proto, 'parent_group_id': self.sg2['id']}

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def _test_create_with_no_ports(self, proto):
        rule = {'ip_protocol': proto, 'parent_group_id': self.sg2['id'],
                 'group_id': self.sg1['id']}

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        expected_rule = {
            'from_port': 1, 'group': {'tenant_id': '123', 'name': 'test'},
            'ip_protocol': proto, 'to_port': 65535, 'parent_group_id':
             self.sg2['id'], 'ip_range': {}, 'id': security_group_rule['id']
        }
        if proto == 'icmp':
            expected_rule['to_port'] = -1
            expected_rule['from_port'] = -1
        self.assertEqual(expected_rule, security_group_rule)

    def test_create_with_no_ports_icmp(self):
        self._test_create_with_no_ports_and_no_group('icmp')
        self._test_create_with_no_ports('icmp')

    def test_create_with_no_ports_tcp(self):
        self._test_create_with_no_ports_and_no_group('tcp')
        self._test_create_with_no_ports('tcp')

    def test_create_with_no_ports_udp(self):
        self._test_create_with_no_ports_and_no_group('udp')
        self._test_create_with_no_ports('udp')

    def _test_create_with_ports(self, proto, from_port, to_port):
        rule = {
            'ip_protocol': proto, 'from_port': from_port, 'to_port': to_port,
            'parent_group_id': self.sg2['id'], 'group_id': self.sg1['id']
        }
        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        expected_rule = {
            'from_port': from_port,
            'group': {'tenant_id': '123', 'name': 'test'},
            'ip_protocol': proto, 'to_port': to_port, 'parent_group_id':
             self.sg2['id'], 'ip_range': {}, 'id': security_group_rule['id']
        }
        self.assertEqual(proto, security_group_rule['ip_protocol'])
        self.assertEqual(from_port, security_group_rule['from_port'])
        self.assertEqual(to_port, security_group_rule['to_port'])
        self.assertEqual(expected_rule, security_group_rule)

    def test_create_with_ports_icmp(self):
        self._test_create_with_ports('icmp', 0, 1)
        self._test_create_with_ports('icmp', 0, 0)
        self._test_create_with_ports('icmp', 1, 0)

    def test_create_with_ports_tcp(self):
        self._test_create_with_ports('tcp', 1, 1)
        self._test_create_with_ports('tcp', 1, 65535)
        self._test_create_with_ports('tcp', 65535, 65535)

    def test_create_with_ports_udp(self):
        self._test_create_with_ports('udp', 1, 1)
        self._test_create_with_ports('udp', 1, 65535)
        self._test_create_with_ports('udp', 65535, 65535)

    def test_delete(self):
        rule = security_group_rule_template(parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank(
            '/v2/%s/os-security-group-rules' % fakes.FAKE_PROJECT_ID)
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        req = fakes.HTTPRequest.blank('/v2/%s/os-security-group-rules/%s' % (
                fakes.FAKE_PROJECT_ID, security_group_rule['id']))
        self.controller.delete(req, security_group_rule['id'])

    def test_delete_invalid_rule_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_delete_non_existing_rule_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.invalid_id)

    def test_create_rule_cidr_allow_all(self):
        rule = security_group_rule_template(cidr='0.0.0.0/0',
                                            parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.parent_security_group['id'])
        self.assertEqual(security_group_rule['ip_range']['cidr'],
                         "0.0.0.0/0")

    def test_create_rule_cidr_ipv6_allow_all(self):
        rule = security_group_rule_template(cidr='::/0',
                                            parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.parent_security_group['id'])
        self.assertEqual(security_group_rule['ip_range']['cidr'],
                         "::/0")

    def test_create_rule_cidr_allow_some(self):
        rule = security_group_rule_template(cidr='15.0.0.0/8',
                                            parent_group_id=self.sg2['id'])

        res_dict = self.controller.create(self.req,
            {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEqual(security_group_rule['id'], 0)
        self.assertEqual(security_group_rule['parent_group_id'],
                         self.parent_security_group['id'])
        self.assertEqual(security_group_rule['ip_range']['cidr'],
                         "15.0.0.0/8")

    def test_create_rule_cidr_bad_netmask(self):
        rule = security_group_rule_template(cidr='15.0.0.0/0')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})


UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get_all(*args, **kwargs):
    base = {'id': 1, 'description': 'foo', 'user_id': 'bar',
            'project_id': 'baz', 'deleted': False, 'deleted_at': None,
            'updated_at': None, 'created_at': None}
    inst_list = [
        fakes.stub_instance_obj(
            None, 1, uuid=UUID1,
            security_groups=[dict(base, **{'name': 'fake-0-0'}),
                             dict(base, **{'name': 'fake-0-1'})]),
        fakes.stub_instance_obj(
            None, 2, uuid=UUID2,
            security_groups=[dict(base, **{'name': 'fake-1-0'}),
                             dict(base, **{'name': 'fake-1-1'})])
    ]

    return objects.InstanceList(objects=inst_list)


def fake_compute_get(*args, **kwargs):
    secgroups = objects.SecurityGroupList()
    secgroups.objects = [
        objects.SecurityGroup(name='fake-2-0'),
        objects.SecurityGroup(name='fake-2-1'),
    ]
    inst = fakes.stub_instance_obj(None, 1, uuid=UUID3)
    inst.security_groups = secgroups
    return inst


def fake_compute_create(*args, **kwargs):
    return ([fake_compute_get(*args, **kwargs)], '')


class SecurityGroupsOutputTest(test.TestCase):
    content_type = 'application/json'

    def setUp(self):
        super(SecurityGroupsOutputTest, self).setUp()

        self.controller = secgroups_v21.SecurityGroupController()
        self.original_client = neutron_api.get_client
        neutron_api.get_client = get_client

        fakes.stub_out_nw_api(self)
        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all', fake_compute_get_all)
        self.stub_out('nova.compute.api.API.create', fake_compute_create)
        self.stub_out(
            'nova.network.security_group_api.'
            'get_instances_security_groups_bindings',
            self._fake_get_instances_security_groups_bindings)

    def tearDown(self):
        neutron_api.get_client = self.original_client
        get_client()._reset()
        super(SecurityGroupsOutputTest, self).tearDown()

    def _fake_get_instances_security_groups_bindings(inst, context, servers):
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
        url = '/v2/%s/servers' % fakes.FAKE_PROJECT_ID
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups' % fakes.FAKE_PROJECT_ID)
        security_groups = [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}]
        for security_group in security_groups:
            sg = security_group_template(name=security_group['name'])
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
        url = '/v2/%s/servers' % fakes.FAKE_PROJECT_ID
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        res = self._make_request(url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        group = self._get_groups(server)[0]
        self.assertEqual(group.get('name'), 'default')

    def test_show(self):
        self.stub_out(
            'nova.network.security_group_api.get_instance_security_groups',
            lambda inst, context, id: [
                {'name': 'fake-2-0'}, {'name': 'fake-2-1'}])

        url = '/v2/%s/servers' % fakes.FAKE_PROJECT_ID
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        req = fakes.HTTPRequest.blank(
                '/v2/%s/os-security-groups' % fakes.FAKE_PROJECT_ID)
        security_groups = [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}]
        for security_group in security_groups:
            sg = security_group_template(name=security_group['name'])
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
        url = '/v2/%s/servers/%s' % (fakes.FAKE_PROJECT_ID, UUID3)
        res = self._make_request(url)
        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)

        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_detail(self):
        url = '/v2/%s/servers/detail' % fakes.FAKE_PROJECT_ID
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            for j, group in enumerate(self._get_groups(server)):
                name = 'fake-%s-%s' % (i, j)
                self.assertEqual(group.get('name'), name)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id='fake'))
    def test_no_instance_passthrough_404(self, mock_get):
        url = ('/v2/%s/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115' %
               fakes.FAKE_PROJECT_ID)
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class TestSecurityGroupsDeprecation(test.NoDBTestCase):

    def setUp(self):
        super(TestSecurityGroupsDeprecation, self).setUp()
        self.controller = secgroups_v21.SecurityGroupController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.update, self.req, fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})


class TestSecurityGroupRulesDeprecation(test.NoDBTestCase):

    def setUp(self):
        super(TestSecurityGroupRulesDeprecation, self).setUp()
        self.controller = secgroups_v21.SecurityGroupRulesController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)

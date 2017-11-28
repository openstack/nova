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
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from nova.api.openstack.compute import security_groups as \
    secgroups_v21
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import power_state
from nova import context as context_maker
import nova.db
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids

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


def return_server(context, server_id,
                  columns_to_join=None, use_slave=False):
    return fake_instance.fake_db_instance(
        **{'id': 1,
           'power_state': 0x01,
           'host': "localhost",
           'uuid': server_id,
           'name': 'asdf'})


def return_server_by_uuid(context, server_uuid,
                          columns_to_join=None,
                          use_slave=False):
    return fake_instance.fake_db_instance(
        **{'id': 1,
           'power_state': 0x01,
           'host': "localhost",
           'uuid': server_uuid,
           'name': 'asdf'})


def return_non_running_server(context, server_id, columns_to_join=None):
    return fake_instance.fake_db_instance(
        **{'id': 1, 'power_state': power_state.SHUTDOWN,
           'uuid': server_id, 'host': "localhost", 'name': 'asdf'})


def return_security_group_by_name(context, project_id, group_name,
                                  columns_to_join=None):
    return {'id': 1, 'name': group_name,
            "instances": [{'id': 1, 'uuid': UUID_SERVER}]}


def return_security_group_without_instances(context, project_id, group_name):
    return {'id': 1, 'name': group_name}


def return_server_nonexistent(context, server_id, columns_to_join=None):
    raise exception.InstanceNotFound(instance_id=server_id)


class TestSecurityGroupsV21(test.TestCase):
    secgrp_ctl_cls = secgroups_v21.SecurityGroupController
    server_secgrp_ctl_cls = secgroups_v21.ServerSecurityGroupController
    secgrp_act_ctl_cls = secgroups_v21.SecurityGroupActionController
    # This class is subclassed by Neutron security group API tests so we need
    # to be able to override this before creating the controller object.
    use_neutron = False

    def setUp(self):
        super(TestSecurityGroupsV21, self).setUp()
        # Neutron security groups are tested in test_neutron_security_groups.py
        self.flags(use_neutron=self.use_neutron)
        self.controller = self.secgrp_ctl_cls()
        self.server_controller = self.server_secgrp_ctl_cls()
        self.manager = self.secgrp_act_ctl_cls()

        # This needs to be done here to set fake_id because the derived
        # class needs to be called first if it wants to set
        # 'security_group_api' and this setUp method needs to be called.
        if self.controller.security_group_api.id_is_uuid:
            self.fake_id = '11111111-1111-1111-1111-111111111111'
        else:
            self.fake_id = '11111111'

        self.req = fakes.HTTPRequest.blank('')
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)

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

    def test_create_security_group_with_no_description(self):
        sg = security_group_request_template()
        del sg['description']

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_with_empty_description(self):
        sg = security_group_request_template()
        sg['description'] = ""

        try:
            self.controller.create(self.req, {'security_group': sg})
            self.fail('Should have raised BadRequest exception')
        except webob.exc.HTTPBadRequest as exc:
            self.assertEqual('description has a minimum character requirement'
                             ' of 1.', exc.explanation)
        except exception.InvalidInput:
            self.fail('Should have raised BadRequest exception instead of')

    def test_create_security_group_with_blank_name(self):
        sg = security_group_request_template(name='')

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_with_whitespace_name(self):
        sg = security_group_request_template(name=' ')

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_with_blank_description(self):
        sg = security_group_request_template(description='')

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_with_whitespace_description(self):
        sg = security_group_request_template(description=' ')

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_with_duplicate_name(self):
        sg = security_group_request_template()

        # FIXME: Stub out _get instead of creating twice
        self.controller.create(self.req, {'security_group': sg})

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

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

    def test_create_security_group_non_string_name(self):
        sg = security_group_request_template(name=12)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_non_string_description(self):
        sg = security_group_request_template(description=12)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group': sg})

    def test_create_security_group_quota_limit(self):
        for num in range(1, CONF.quota.security_groups):
            name = 'test%s' % num
            sg = security_group_request_template(name=name)
            res_dict = self.controller.create(self.req, {'security_group': sg})
            self.assertEqual(res_dict['security_group']['name'], name)

        sg = security_group_request_template()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, {'security_group': sg})

    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    def test_create_security_group_over_quota_during_recheck(self, check_mock):
        # Simulate a race where the first check passes and the recheck fails.
        check_mock.side_effect = [None,
                                  exception.OverQuota(overs='security_groups')]

        ctxt = self.req.environ['nova.context']
        sg = security_group_request_template()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, {'security_group': sg})

        self.assertEqual(2, check_mock.call_count)
        call1 = mock.call(ctxt, {'security_groups': 1}, ctxt.project_id,
                          user_id=ctxt.user_id)
        call2 = mock.call(ctxt, {'security_groups': 0}, ctxt.project_id,
                          user_id=ctxt.user_id)
        check_mock.assert_has_calls([call1, call2])

        # Verify we removed the security group that was added after the first
        # quota check passed.
        self.assertRaises(exception.SecurityGroupNotFound,
                          objects.SecurityGroup.get_by_name, ctxt,
                          ctxt.project_id, sg['name'])

    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    def test_create_security_group_no_quota_recheck(self, check_mock):
        # Disable recheck_quota.
        self.flags(recheck_quota=False, group='quota')

        ctxt = self.req.environ['nova.context']
        sg = security_group_request_template()
        self.controller.create(self.req, {'security_group': sg})

        # check_deltas should have been called only once.
        check_mock.assert_called_once_with(ctxt, {'security_groups': 1},
                                           ctxt.project_id,
                                           user_id=ctxt.user_id)

    def test_get_security_group_list(self):
        self._test_get_security_group_list()

    def test_get_security_group_list_offset_and_limit(self):
        self._test_get_security_group_list(limited=True)

    def _test_get_security_group_list(self, limited=False):
        groups = []
        for i, name in enumerate(['default', 'test']):
            sg = security_group_template(id=i + 1,
                                         name=name,
                                         description=name + '-desc',
                                         rules=[])
            groups.append(sg)
        if limited:
            expected = {'security_groups': [groups[1]]}
        else:
            expected = {'security_groups': groups}

        def return_security_groups(context, project_id):
            return [security_group_db(sg) for sg in groups]

        self.stub_out('nova.db.security_group_get_by_project',
                      return_security_groups)

        path = '/v2/fake/os-security-groups'
        if limited:
            path += '?offset=1&limit=1'
        req = fakes.HTTPRequest.blank(path, use_admin_context=True)

        res_dict = self.controller.index(req)

        self.assertEqual(res_dict, expected)

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

        def return_security_groups(context, project, search_opts):
            return [security_group_db(sg) for sg in groups]

        self.stubs.Set(self.controller.security_group_api, 'list',
                       return_security_groups)

        res_dict = self.controller.index(self.req)

        self.assertEqual(res_dict, expected)

    def test_get_security_group_list_all_tenants(self):
        all_groups = []
        tenant_groups = []

        for i, name in enumerate(['default', 'test']):
            sg = security_group_template(id=i + 1,
                                         name=name,
                                         description=name + '-desc',
                                         rules=[])
            all_groups.append(sg)
            if name == 'default':
                tenant_groups.append(sg)

        all = {'security_groups': all_groups}
        tenant_specific = {'security_groups': tenant_groups}

        def return_all_security_groups(context):
            return [security_group_db(sg) for sg in all_groups]

        self.stub_out('nova.db.security_group_get_all',
                      return_all_security_groups)

        def return_tenant_security_groups(context, project_id):
            return [security_group_db(sg) for sg in tenant_groups]

        self.stub_out('nova.db.security_group_get_by_project',
                      return_tenant_security_groups)

        path = '/v2/fake/os-security-groups'

        req = fakes.HTTPRequest.blank(path, use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, tenant_specific)

        req = fakes.HTTPRequest.blank('%s?all_tenants=1' % path,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, all)

    def test_get_security_group_by_instance(self):
        groups = []
        for i, name in enumerate(['default', 'test']):
            # Create two rules per group to test that we don't perform
            # redundant group lookups. For the default group, the rule group_id
            # is the group itself. For the test group, the rule group_id points
            # to a non-existent group.
            group_id = i + 1 if name == 'default' else 'HAS_BEEN_DELETED'
            rule1 = security_group_rule_template(
                cidr='10.2.3.125/24', parent_group_id=1, id=99, protocol='TCP',
                group_id=group_id)
            rule2 = security_group_rule_template(
                cidr='10.2.3.126/24', parent_group_id=1, id=77, protocol='UDP',
                group_id=group_id)
            sg = security_group_template(
                id=i + 1, name=name, description=name + '-desc',
                rules=[rule1, rule2], tenant_id='fake')
            groups.append(sg)

        # An expected rule here needs to be created as the api returns
        # different attributes on the rule for a response than what was
        # passed in.
        expected_rule1 = security_group_rule_template(
            ip_range={}, parent_group_id=1, ip_protocol='TCP',
            group={'name': 'default', 'tenant_id': 'fake'}, id=99)
        expected_rule2 = security_group_rule_template(
            ip_range={}, parent_group_id=1, ip_protocol='UDP',
            group={'name': 'default', 'tenant_id': 'fake'}, id=77)
        expected_group1 = security_group_template(
            id=1, name='default', description='default-desc',
            rules=[expected_rule1, expected_rule2], tenant_id='fake')
        expected_group2 = security_group_template(
            id=2, name='test', description='test-desc', rules=[],
            tenant_id='fake')

        expected = {'security_groups': [expected_group1, expected_group2]}

        def return_instance(context, server_id,
                            columns_to_join=None, use_slave=False):
            self.assertEqual(server_id, FAKE_UUID1)
            return return_server_by_uuid(context, server_id)

        self.stub_out('nova.db.instance_get_by_uuid',
                      return_instance)

        def return_security_groups(context, instance_uuid):
            self.assertEqual(instance_uuid, FAKE_UUID1)
            return [security_group_db(sg) for sg in groups]

        self.stub_out('nova.db.security_group_get_by_instance',
                      return_security_groups)

        # Stub out the security group API get() method to assert that we only
        # call it at most once per group ID.
        original_sg_get = self.server_controller.security_group_api.get
        queried_group_ids = []

        def fake_security_group_api_get(_self, context, name=None, id=None,
                                        map_exception=False):
            if id in queried_group_ids:
                self.fail('Queried security group %s more than once.' % id)
            queried_group_ids.append(id)
            return original_sg_get(context, id=id)

        self.stub_out('nova.compute.api.SecurityGroupAPI.get',
                      fake_security_group_api_get)

        res_dict = self.server_controller.index(self.req, FAKE_UUID1)

        self.assertEqual(expected, res_dict)

    @mock.patch('nova.db.instance_get_by_uuid')
    @mock.patch('nova.db.security_group_get_by_instance', return_value=[])
    def test_get_security_group_empty_for_instance(self, mock_sec_group,
                                                   mock_db_get_ins):
        expected = {'security_groups': []}

        def return_instance(context, server_id,
                            columns_to_join=None, use_slave=False):
            self.assertEqual(server_id, FAKE_UUID1)
            return return_server_by_uuid(context, server_id)
        mock_db_get_ins.side_effect = return_instance
        res_dict = self.server_controller.index(self.req, FAKE_UUID1)
        self.assertEqual(expected, res_dict)
        mock_sec_group.assert_called_once_with(
            self.req.environ['nova.context'], FAKE_UUID1)

    def test_get_security_group_by_instance_non_existing(self):
        self.stub_out('nova.db.instance_get', return_server_nonexistent)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_server_nonexistent)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.server_controller.index, self.req, '1')

    def test_get_security_group_by_instance_invalid_id(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.server_controller.index, self.req, 'invalid')

    def test_get_security_group_by_id(self):
        sg = security_group_template(id=2, rules=[])

        def return_security_group(context, group_id, columns_to_join=None):
            self.assertEqual(sg['id'], group_id)
            return security_group_db(sg)

        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        res_dict = self.controller.show(self.req, '2')

        expected = {'security_group': sg}
        self.assertEqual(res_dict, expected)

    def test_get_security_group_by_invalid_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_get_security_group_by_non_existing_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.fake_id)

    def test_update_security_group(self):
        sg = security_group_template(id=2, rules=[])
        sg_update = security_group_template(id=2, rules=[],
                        name='update_name', description='update_desc')

        def return_security_group(context, group_id, columns_to_join=None):
            self.assertEqual(sg['id'], group_id)
            return security_group_db(sg)

        def return_update_security_group(context, group_id, values,
                                         columns_to_join=None):
            self.assertEqual(sg_update['id'], group_id)
            self.assertEqual(sg_update['name'], values['name'])
            self.assertEqual(sg_update['description'], values['description'])
            return security_group_db(sg_update)

        self.stub_out('nova.db.security_group_update',
                      return_update_security_group)
        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        res_dict = self.controller.update(self.req, '2',
                                          {'security_group': sg_update})

        expected = {'security_group': sg_update}
        self.assertEqual(res_dict, expected)

    def test_update_security_group_name_to_default(self):
        sg = security_group_template(id=2, rules=[], name='default')

        def return_security_group(context, group_id, columns_to_join=None):
            self.assertEqual(sg['id'], group_id)
            return security_group_db(sg)

        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, '2', {'security_group': sg})

    def test_update_default_security_group_fail(self):
        sg = security_group_template()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, '1', {'security_group': sg})

    def test_delete_security_group_by_id(self):
        sg = security_group_template(id=1, project_id='fake_project',
                                     user_id='fake_user', rules=[])

        self.called = False

        def security_group_destroy(context, id):
            self.called = True

        def return_security_group(context, group_id, columns_to_join=None):
            self.assertEqual(sg['id'], group_id)
            return security_group_db(sg)

        self.stub_out('nova.db.security_group_destroy',
                      security_group_destroy)
        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        self.controller.delete(self.req, '1')

        self.assertTrue(self.called)

    def test_delete_security_group_by_admin(self):
        sg = security_group_request_template()

        self.controller.create(self.req, {'security_group': sg})
        context = self.req.environ['nova.context']

        # Ensure quota usage for security group is correct.
        self._assert_security_groups_in_use(context.project_id,
                                            context.user_id, 2)

        # Delete the security group by admin.
        self.controller.delete(self.admin_req, '2')

        # Ensure quota for security group in use is released.
        self._assert_security_groups_in_use(context.project_id,
                                            context.user_id, 1)

    def test_delete_security_group_by_invalid_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_delete_security_group_by_non_existing_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.fake_id)

    def test_delete_security_group_in_use(self):
        sg = security_group_template(id=1, rules=[])

        def security_group_in_use(context, id):
            return True

        def return_security_group(context, group_id, columns_to_join=None):
            self.assertEqual(sg['id'], group_id)
            return security_group_db(sg)

        self.stub_out('nova.db.security_group_in_use',
                      security_group_in_use)
        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, '1')

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
        self.stub_out('nova.db.instance_get', return_server)
        self.assertEqual(return_server(None, '1'),
                         nova.db.instance_get(None, '1'))
        body = dict(addSecurityGroup=dict(name='non-existing'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_by_invalid_server_id(self):
        body = dict(addSecurityGroup=dict(name='test'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, self.req,
                          'invalid', body)

    def test_associate_without_body(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(addSecurityGroup=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_no_security_group_name(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(addSecurityGroup=dict())

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_security_group_name_with_whitespaces(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(addSecurityGroup=dict(name="   "))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_non_existing_instance(self):
        self.stub_out('nova.db.instance_get', return_server_nonexistent)
        self.stub_out('nova.db.instance_get_by_uuid',
                       return_server_nonexistent)
        body = dict(addSecurityGroup=dict(name="test"))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, self.req, '1', body)

    def test_associate_non_running_instance(self):
        self.stub_out('nova.db.instance_get', return_non_running_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_non_running_server)
        self.stub_out('nova.db.security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(addSecurityGroup=dict(name="test"))

        self.manager._addSecurityGroup(self.req, UUID_SERVER, body)

    def test_associate_already_associated_security_group_to_instance(self):
        self.stub_out('nova.db.instance_get', return_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_server_by_uuid)
        self.stub_out('nova.db.security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(addSecurityGroup=dict(name="test"))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, self.req,
                          UUID_SERVER, body)

    @mock.patch.object(nova.db, 'instance_add_security_group')
    def test_associate(self, mock_add_security_group):
        self.stub_out('nova.db.instance_get', return_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                       return_server_by_uuid)

        self.stub_out('nova.db.security_group_get_by_name',
                       return_security_group_without_instances)

        body = dict(addSecurityGroup=dict(name="test"))

        self.manager._addSecurityGroup(self.req, UUID_SERVER, body)
        mock_add_security_group.assert_called_once_with(mock.ANY,
                                                        mock.ANY,
                                                        mock.ANY)

    def test_disassociate_by_non_existing_security_group_name(self):
        self.stub_out('nova.db.instance_get', return_server)
        self.assertEqual(return_server(None, '1'),
                         nova.db.instance_get(None, '1'))
        body = dict(removeSecurityGroup=dict(name='non-existing'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup, self.req,
                          UUID_SERVER, body)

    def test_disassociate_by_invalid_server_id(self):
        self.stub_out('nova.db.security_group_get_by_name',
                      return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name='test'))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup, self.req,
                          'invalid', body)

    def test_disassociate_without_body(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(removeSecurityGroup=None)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_no_security_group_name(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(removeSecurityGroup=dict())

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_security_group_name_with_whitespaces(self):
        self.stub_out('nova.db.instance_get', return_server)
        body = dict(removeSecurityGroup=dict(name="   "))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          '1', body)

    def test_disassociate_non_existing_instance(self):
        self.stub_out('nova.db.instance_get', return_server_nonexistent)
        self.stub_out('nova.db.security_group_get_by_name',
                      return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name="test"))

        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup,
                          self.req, '1', body)

    def test_disassociate_non_running_instance(self):
        self.stub_out('nova.db.instance_get', return_non_running_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_non_running_server)
        self.stub_out('nova.db.security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name="test"))

        self.manager._removeSecurityGroup(self.req, UUID_SERVER, body)

    def test_disassociate_already_associated_security_group_to_instance(self):
        self.stub_out('nova.db.instance_get', return_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_server_by_uuid)
        self.stub_out('nova.db.security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(removeSecurityGroup=dict(name="test"))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, self.req,
                          UUID_SERVER, body)

    @mock.patch.object(nova.db, 'instance_remove_security_group')
    def test_disassociate(self, mock_remove_sec_group):
        self.stub_out('nova.db.instance_get', return_server)
        self.stub_out('nova.db.instance_get_by_uuid',
                      return_server_by_uuid)
        self.stub_out('nova.db.security_group_get_by_name',
                      return_security_group_by_name)

        body = dict(removeSecurityGroup=dict(name="test"))

        self.manager._removeSecurityGroup(self.req, UUID_SERVER, body)
        mock_remove_sec_group.assert_called_once_with(mock.ANY,
                                                      mock.ANY,
                                                      mock.ANY)


class TestSecurityGroupRulesV21(test.TestCase):
    secgrp_ctl_cls = secgroups_v21.SecurityGroupRulesController
    # This class is subclassed by Neutron security group API tests so we need
    # to be able to override this before creating the controller object.
    use_neutron = False

    def setUp(self):
        super(TestSecurityGroupRulesV21, self).setUp()
        # Neutron security groups are tested in test_neutron_security_groups.py
        self.flags(use_neutron=self.use_neutron)
        self.controller = self.secgrp_ctl_cls()
        if self.controller.security_group_api.id_is_uuid:
            id1 = '11111111-1111-1111-1111-111111111111'
            id2 = '22222222-2222-2222-2222-222222222222'
            self.invalid_id = '33333333-3333-3333-3333-333333333333'
        else:
            id1 = 1
            id2 = 2
            self.invalid_id = '33333333'

        self.sg1 = security_group_template(id=id1)
        self.sg2 = security_group_template(
            id=id2, name='authorize_revoke',
            description='authorize-revoke testing')

        db1 = security_group_db(self.sg1)
        db2 = security_group_db(self.sg2)

        def return_security_group(context, group_id, columns_to_join=None):
            if group_id == db1['id']:
                return db1
            if group_id == db2['id']:
                return db2
            raise exception.SecurityGroupNotFound(security_group_id=group_id)

        self.stub_out('nova.db.security_group_get',
                      return_security_group)

        self.parent_security_group = db2
        self.req = fakes.HTTPRequest.blank('')

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
        rule = security_group_rule_template(cidr='10.0.0.0/24',
                                            parent_group_id=self.sg2['id'])

        self.parent_security_group['rules'] = [security_group_rule_db(rule)]

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_group_id(self):
        rule = security_group_rule_template(group_id=1)

        self.parent_security_group['rules'] = [security_group_rule_db(rule)]

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'security_group_rule': rule})

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
        rule = security_group_rule_template(id=self.sg2['id'],
                                            parent_group_id=self.sg2['id'])

        def security_group_rule_get(context, id):
            return security_group_rule_db(rule)

        def security_group_rule_destroy(context, id):
            pass

        self.stub_out('nova.db.security_group_rule_get',
                      security_group_rule_get)
        self.stub_out('nova.db.security_group_rule_destroy',
                      security_group_rule_destroy)

        self.controller.delete(self.req, self.sg2['id'])

    def test_delete_invalid_rule_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'invalid')

    def test_delete_non_existing_rule_id(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, self.invalid_id)

    def test_create_rule_quota_limit(self):
        for num in range(100, 100 + CONF.quota.security_group_rules):
            rule = {
                'ip_protocol': 'tcp', 'from_port': num,
                'to_port': num, 'parent_group_id': self.sg2['id'],
                'group_id': self.sg1['id']
            }
            self.controller.create(self.req, {'security_group_rule': rule})

        rule = {
            'ip_protocol': 'tcp', 'from_port': '121', 'to_port': '121',
            'parent_group_id': self.sg2['id'], 'group_id': self.sg1['id']
        }
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, {'security_group_rule': rule})

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_rule_over_quota_during_recheck(self, mock_check):
        # Simulate a race where the first check passes and the recheck fails.
        # First check occurs in compute/api.
        exc = exception.OverQuota(overs='security_group_rules',
                                  usages={'security_group_rules': 100})
        mock_check.side_effect = [None, exc]

        rule = {
            'ip_protocol': 'tcp', 'from_port': '121', 'to_port': '121',
            'parent_group_id': self.sg2['id'], 'group_id': self.sg1['id']
        }
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, {'security_group_rule': rule})

        ctxt = self.req.environ['nova.context']
        self.assertEqual(2, mock_check.call_count)
        # parent_group_id is used for adding the rules.
        call1 = mock.call(ctxt, {'security_group_rules': 1}, self.sg2['id'])
        call2 = mock.call(ctxt, {'security_group_rules': 0}, self.sg2['id'])
        mock_check.assert_has_calls([call1, call2])

        # Verify we removed the rule that was added after the first quota check
        # passed.
        rules = objects.SecurityGroupRuleList.get_by_security_group_id(
            ctxt, self.sg1['id'])
        self.assertEqual(0, len(rules))

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_rule_no_quota_recheck(self, mock_check):
        # Disable recheck_quota.
        self.flags(recheck_quota=False, group='quota')

        rule = {
            'ip_protocol': 'tcp', 'from_port': '121', 'to_port': '121',
            'parent_group_id': self.sg2['id'], 'group_id': self.sg1['id']
        }
        self.controller.create(self.req, {'security_group_rule': rule})

        ctxt = self.req.environ['nova.context']
        # check_deltas should have been called only once.
        # parent_group_id is used for adding the rules.
        mock_check.assert_called_once_with(ctxt, {'security_group_rules': 1},
                                           self.sg2['id'])

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


def fake_get_instances_security_groups_bindings(inst, context, servers):
    groups = {UUID1: [{'name': 'fake-0-0'}, {'name': 'fake-0-1'}],
              UUID2: [{'name': 'fake-1-0'}, {'name': 'fake-1-1'}],
              UUID3: [{'name': 'fake-2-0'}, {'name': 'fake-2-1'}]}
    result = {}
    for server in servers:
        result[server['id']] = groups.get(server['id'])
    return result


class SecurityGroupsOutputTestV21(test.TestCase):
    base_url = '/v2/fake/servers'
    content_type = 'application/json'

    def setUp(self):
        super(SecurityGroupsOutputTestV21, self).setUp()
        # Neutron security groups are tested in test_neutron_security_groups.py
        self.flags(use_neutron=False)
        fakes.stub_out_nw_api(self)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(compute.api.API, 'create', fake_compute_create)
        self.app = self._setup_app()

    def _setup_app(self):
        return fakes.wsgi_app_v21()

    def _make_request(self, url, body=None):
        req = fakes.HTTPRequest.blank(url)
        if body:
            req.method = 'POST'
            req.body = encodeutils.safe_encode(self._encode_body(body))
        req.content_type = self.content_type
        req.headers['Accept'] = self.content_type
        res = req.get_response(self.app)
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
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        res = self._make_request(self.base_url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_show(self):
        url = self.base_url + '/' + UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)
        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_detail(self):
        url = self.base_url + '/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            for j, group in enumerate(self._get_groups(server)):
                name = 'fake-%s-%s' % (i, j)
                self.assertEqual(group.get('name'), name)

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        url = self.base_url + '/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class SecurityGroupsOutputPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(SecurityGroupsOutputPolicyEnforcementV21, self).setUp()
        self.controller = secgroups_v21.SecurityGroupsOutputController()
        self.req = fakes.HTTPRequest.blank('')
        self.rule_name = "os_compute_api:os-security-groups"
        self.rule = {self.rule_name: "project:non_fake"}
        self.policy.set_rules(self.rule)
        self.fake_res = wsgi.ResponseObject({
            'server': {'id': '0'},
            'servers': [{'id': '0'}, {'id': '2'}]})

    @mock.patch('nova.policy.authorize')
    def test_show_policy_softauth_is_called(self, mock_authorize):
        mock_authorize.return_value = False
        self.controller.show(self.req, self.fake_res, FAKE_UUID1)
        self.assertTrue(mock_authorize.called)

    @mock.patch.object(nova.network.security_group.openstack_driver,
        "is_neutron_security_groups")
    def test_show_policy_failed(self, is_neutron_security_groups):
        self.controller.show(self.req, self.fake_res, FAKE_UUID1)
        self.assertFalse(is_neutron_security_groups.called)

    @mock.patch('nova.policy.authorize')
    def test_create_policy_softauth_is_called(self, mock_authorize):
        mock_authorize.return_value = False
        self.controller.show(self.req, self.fake_res, {})
        self.assertTrue(mock_authorize.called)

    @mock.patch.object(nova.network.security_group.openstack_driver,
        "is_neutron_security_groups")
    def test_create_policy_failed(self, is_neutron_security_groups):
        self.controller.create(self.req, self.fake_res, {})
        self.assertFalse(is_neutron_security_groups.called)

    @mock.patch('nova.policy.authorize')
    def test_detail_policy_softauth_is_called(self, mock_authorize):
        mock_authorize.return_value = False
        self.controller.detail(self.req, self.fake_res)
        self.assertTrue(mock_authorize.called)

    @mock.patch.object(nova.network.security_group.openstack_driver,
        "is_neutron_security_groups")
    def test_detail_policy_failed(self, is_neutron_security_groups):
        self.controller.detail(self.req, self.fake_res)
        self.assertFalse(is_neutron_security_groups.called)


class PolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(PolicyEnforcementV21, self).setUp()
        self.req = fakes.HTTPRequest.blank('')
        self.rule_name = "os_compute_api:os-security-groups"
        self.rule = {self.rule_name: "project:non_fake"}

    def _common_policy_check(self, func, *arg, **kwarg):
        self.policy.set_rules(self.rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % self.rule_name,
            exc.format_message())


class SecurityGroupPolicyEnforcementV21(PolicyEnforcementV21):

    def setUp(self):
        super(SecurityGroupPolicyEnforcementV21, self).setUp()
        self.controller = secgroups_v21.SecurityGroupController()

    def test_create_policy_failed(self):
        self._common_policy_check(self.controller.create, self.req, {})

    def test_show_policy_failed(self):
        self._common_policy_check(self.controller.show, self.req, FAKE_UUID1)

    def test_delete_policy_failed(self):
        self._common_policy_check(self.controller.delete, self.req, FAKE_UUID1)

    def test_index_policy_failed(self):
        self._common_policy_check(self.controller.index, self.req)

    def test_update_policy_failed(self):
        self._common_policy_check(
            self.controller.update, self.req, FAKE_UUID1, {})


class ServerSecurityGroupPolicyEnforcementV21(PolicyEnforcementV21):

    def setUp(self):
        super(ServerSecurityGroupPolicyEnforcementV21, self).setUp()
        self.controller = secgroups_v21.ServerSecurityGroupController()

    def test_index_policy_failed(self):
        self._common_policy_check(self.controller.index, self.req, FAKE_UUID1)


class SecurityGroupRulesPolicyEnforcementV21(PolicyEnforcementV21):

    def setUp(self):
        super(SecurityGroupRulesPolicyEnforcementV21, self).setUp()
        self.controller = secgroups_v21.SecurityGroupRulesController()

    def test_create_policy_failed(self):
        self._common_policy_check(self.controller.create, self.req, {})

    def test_delete_policy_failed(self):
        self._common_policy_check(self.controller.delete, self.req, FAKE_UUID1)


class SecurityGroupActionPolicyEnforcementV21(PolicyEnforcementV21):

    def setUp(self):
        super(SecurityGroupActionPolicyEnforcementV21, self).setUp()
        self.controller = secgroups_v21.SecurityGroupActionController()

    def test_add_security_group_policy_failed(self):
        self._common_policy_check(
            self.controller._addSecurityGroup, self.req, FAKE_UUID1, {})

    def test_remove_security_group_policy_failed(self):
        self._common_policy_check(
            self.controller._removeSecurityGroup, self.req, FAKE_UUID1, {})


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

# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from lxml import etree
import mox
from oslo.config import cfg
import webob

from nova.api.openstack.compute.contrib import security_groups
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova.compute import power_state
import nova.db
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import quota
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests import utils

CONF = cfg.CONF
FAKE_UUID1 = 'a47ae74e-ab08-447f-8eee-ffd43fc46c16'
FAKE_UUID2 = 'c6e6430a-6563-4efa-9542-5e93c9e97d18'


class AttrDict(dict):
    def __getattr__(self, k):
        return self[k]


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


def return_server(context, server_id, columns_to_join=None):
    return fake_instance.fake_db_instance(
        **{'id': int(server_id),
           'power_state': 0x01,
           'host': "localhost",
           'uuid': FAKE_UUID1,
           'name': 'asdf'})


def return_server_by_uuid(context, server_uuid, columns_to_join=None):
    return fake_instance.fake_db_instance(
        **{'id': 1,
           'power_state': 0x01,
           'host': "localhost",
           'uuid': server_uuid,
           'name': 'asdf'})


def return_non_running_server(context, server_id, columns_to_join=None):
    return fake_instance.fake_db_instance(
        **{'id': server_id, 'power_state': power_state.SHUTDOWN,
           'uuid': FAKE_UUID1, 'host': "localhost", 'name': 'asdf'})


def return_security_group_by_name(context, project_id, group_name):
    return {'id': 1, 'name': group_name,
            "instances": [{'id': 1, 'uuid': FAKE_UUID1}]}


def return_security_group_without_instances(context, project_id, group_name):
    return {'id': 1, 'name': group_name}


def return_server_nonexistent(context, server_id, columns_to_join=None):
    raise exception.InstanceNotFound(instance_id=server_id)


class TestSecurityGroups(test.TestCase):
    def setUp(self):
        super(TestSecurityGroups, self).setUp()

        self.controller = security_groups.SecurityGroupController()
        self.server_controller = (
            security_groups.ServerSecurityGroupController())
        self.manager = security_groups.SecurityGroupActionController()

        # This needs to be done here to set fake_id because the derived
        # class needs to be called first if it wants to set
        # 'security_group_api' and this setUp method needs to be called.
        if self.controller.security_group_api.id_is_uuid:
            self.fake_id = '11111111-1111-1111-1111-111111111111'
        else:
            self.fake_id = '11111111'

    def _assert_no_security_groups_reserved(self, context):
        """Check that no reservations are leaked during tests."""
        result = quota.QUOTAS.get_project_quotas(context, context.project_id)
        self.assertEqual(result['security_groups']['reserved'], 0)

    def test_create_security_group(self):
        sg = security_group_template()

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        res_dict = self.controller.create(req, {'security_group': sg})
        self.assertEqual(res_dict['security_group']['name'], 'test')
        self.assertEqual(res_dict['security_group']['description'],
                         'test-description')

    def test_create_security_group_with_no_name(self):
        sg = security_group_template()
        del sg['name']

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, sg)

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_no_description(self):
        sg = security_group_template()
        del sg['description']

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_blank_name(self):
        sg = security_group_template(name='')

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_whitespace_name(self):
        sg = security_group_template(name=' ')

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_blank_description(self):
        sg = security_group_template(description='')

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_whitespace_description(self):
        sg = security_group_template(description=' ')

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_duplicate_name(self):
        sg = security_group_template()

        # FIXME: Stub out _get instead of creating twice
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.controller.create(req, {'security_group': sg})

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_no_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, None)

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_with_no_security_group(self):
        body = {'no-securityGroup': None}

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, body)

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_above_255_characters_name(self):
        sg = security_group_template(name='1234567890' * 26)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_above_255_characters_description(self):
        sg = security_group_template(description='1234567890' * 26)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_non_string_name(self):
        sg = security_group_template(name=12)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_non_string_description(self):
        sg = security_group_template(description=12)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group': sg})

        self._assert_no_security_groups_reserved(req.environ['nova.context'])

    def test_create_security_group_quota_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        for num in range(1, CONF.quota_security_groups + 1):
            name = 'test%s' % num
            sg = security_group_template(name=name)
            res_dict = self.controller.create(req, {'security_group': sg})
            self.assertEqual(res_dict['security_group']['name'], name)

        sg = security_group_template()
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create,
                          req, {'security_group': sg})

    def test_get_security_group_list(self):
        groups = []
        for i, name in enumerate(['default', 'test']):
            sg = security_group_template(id=i + 1,
                                         name=name,
                                         description=name + '-desc',
                                         rules=[])
            groups.append(sg)
        expected = {'security_groups': groups}

        def return_security_groups(context, project_id):
            return [security_group_db(sg) for sg in groups]

        self.stubs.Set(nova.db, 'security_group_get_by_project',
                       return_security_groups)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups')
        res_dict = self.controller.index(req)

        self.assertEquals(res_dict, expected)

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

        self.stubs.Set(nova.db, 'security_group_get_all',
                       return_all_security_groups)

        def return_tenant_security_groups(context, project_id):
            return [security_group_db(sg) for sg in tenant_groups]

        self.stubs.Set(nova.db, 'security_group_get_by_project',
                       return_tenant_security_groups)

        path = '/v2/fake/os-security-groups'

        req = fakes.HTTPRequest.blank(path, use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEquals(res_dict, tenant_specific)

        req = fakes.HTTPRequest.blank('%s?all_tenants=1' % path,
                                      use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEquals(res_dict, all)

    def test_get_security_group_by_instance(self):
        groups = []
        for i, name in enumerate(['default', 'test']):
            sg = security_group_template(id=i + 1,
                                         name=name,
                                         description=name + '-desc',
                                         rules=[])
            groups.append(sg)
        expected = {'security_groups': groups}

        def return_instance(context, server_id, columns_to_join=None):
            self.assertEquals(server_id, FAKE_UUID1)
            return return_server_by_uuid(context, server_id)

        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_instance)

        def return_security_groups(context, instance_uuid):
            self.assertEquals(instance_uuid, FAKE_UUID1)
            return [security_group_db(sg) for sg in groups]

        self.stubs.Set(nova.db, 'security_group_get_by_instance',
                       return_security_groups)

        req = fakes.HTTPRequest.blank('/v2/%s/servers/%s/os-security-groups' %
                                      ('fake', FAKE_UUID1))
        res_dict = self.server_controller.index(req, FAKE_UUID1)

        self.assertEquals(res_dict, expected)

    def test_get_security_group_by_instance_non_existing(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistent)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_nonexistent)
        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/os-security-groups')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.server_controller.index, req, '1')

    def test_get_security_group_by_instance_invalid_id(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/servers/invalid/os-security-groups')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.server_controller.index, req, 'invalid')

    def test_get_security_group_by_id(self):
        sg = security_group_template(id=2, rules=[])

        def return_security_group(context, group_id):
            self.assertEquals(sg['id'], group_id)
            return security_group_db(sg)

        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/2')
        res_dict = self.controller.show(req, '2')

        expected = {'security_group': sg}
        self.assertEquals(res_dict, expected)

    def test_get_security_group_by_invalid_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, 'invalid')

    def test_get_security_group_by_non_existing_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s' %
                                      self.fake_id)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.fake_id)

    def test_update_security_group(self):
        sg = security_group_template(id=2, rules=[])
        sg_update = security_group_template(id=2, rules=[],
                        name='update_name', description='update_desc')

        def return_security_group(context, group_id):
            self.assertEquals(sg['id'], group_id)
            return security_group_db(sg)

        def return_update_security_group(context, group_id, values):
            self.assertEquals(sg_update['id'], group_id)
            self.assertEquals(sg_update['name'], values['name'])
            self.assertEquals(sg_update['description'], values['description'])
            return security_group_db(sg_update)

        self.stubs.Set(nova.db, 'security_group_update',
                       return_update_security_group)
        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/2')
        res_dict = self.controller.update(req, '2',
                                          {'security_group': sg_update})

        expected = {'security_group': sg_update}
        self.assertEquals(res_dict, expected)

    def test_update_security_group_name_to_default(self):
        sg = security_group_template(id=2, rules=[], name='default')

        def return_security_group(context, group_id):
            self.assertEquals(sg['id'], group_id)
            return security_group_db(sg)

        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/2')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, '2', {'security_group': sg})

    def test_update_default_security_group_fail(self):
        sg = security_group_template()

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/1')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, '1', {'security_group': sg})

    def test_delete_security_group_by_id(self):
        sg = security_group_template(id=1, rules=[])

        self.called = False

        def security_group_destroy(context, id):
            self.called = True

        def return_security_group(context, group_id):
            self.assertEquals(sg['id'], group_id)
            return security_group_db(sg)

        self.stubs.Set(nova.db, 'security_group_destroy',
                       security_group_destroy)
        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/1')
        self.controller.delete(req, '1')

        self.assertTrue(self.called)

    def test_delete_security_group_by_invalid_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, 'invalid')

    def test_delete_security_group_by_non_existing_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/%s'
                                      % self.fake_id)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.fake_id)

    def test_delete_security_group_in_use(self):
        sg = security_group_template(id=1, rules=[])

        def security_group_in_use(context, id):
            return True

        def return_security_group(context, group_id):
            self.assertEquals(sg['id'], group_id)
            return security_group_db(sg)

        self.stubs.Set(nova.db, 'security_group_in_use',
                       security_group_in_use)
        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-groups/1')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, '1')

    def test_associate_by_non_existing_security_group_name(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.assertEquals(return_server(None, '1'),
                          nova.db.instance_get(None, '1'))
        body = dict(addSecurityGroup=dict(name='non-existing'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate_by_invalid_server_id(self):
        body = dict(addSecurityGroup=dict(name='test'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/invalid/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, req, 'invalid', body)

    def test_associate_without_body(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(addSecurityGroup=None)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate_no_security_group_name(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(addSecurityGroup=dict())

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate_security_group_name_with_whitespaces(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(addSecurityGroup=dict(name="   "))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate_non_existing_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistent)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_nonexistent)
        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate_non_running_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_non_running_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_non_running_server)
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.manager._addSecurityGroup(req, '1', body)

    def test_associate_already_associated_security_group_to_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._addSecurityGroup, req, '1', body)

    def test_associate(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)
        self.mox.StubOutWithMock(nova.db, 'instance_add_security_group')
        nova.db.instance_add_security_group(mox.IgnoreArg(),
                                            mox.IgnoreArg(),
                                            mox.IgnoreArg())
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_without_instances)
        self.mox.ReplayAll()

        body = dict(addSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.manager._addSecurityGroup(req, '1', body)

    def test_disassociate_by_non_existing_security_group_name(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.assertEquals(return_server(None, '1'),
                          nova.db.instance_get(None, '1'))
        body = dict(removeSecurityGroup=dict(name='non-existing'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate_by_invalid_server_id(self):
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name='test'))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/invalid/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup, req, 'invalid',
                          body)

    def test_disassociate_without_body(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(removeSecurityGroup=None)

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate_no_security_group_name(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(removeSecurityGroup=dict())

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate_security_group_name_with_whitespaces(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        body = dict(removeSecurityGroup=dict(name="   "))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate_non_existing_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_server_nonexistent)
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate_non_running_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_non_running_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_non_running_server)
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_by_name)
        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.manager._removeSecurityGroup(req, '1', body)

    def test_disassociate_already_associated_security_group_to_instance(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.manager._removeSecurityGroup, req, '1', body)

    def test_disassociate(self):
        self.stubs.Set(nova.db, 'instance_get', return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid)
        self.mox.StubOutWithMock(nova.db, 'instance_remove_security_group')
        nova.db.instance_remove_security_group(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg())
        self.stubs.Set(nova.db, 'security_group_get_by_name',
                       return_security_group_by_name)
        self.mox.ReplayAll()

        body = dict(removeSecurityGroup=dict(name="test"))

        req = fakes.HTTPRequest.blank('/v2/fake/servers/1/action')
        self.manager._removeSecurityGroup(req, '1', body)


class TestSecurityGroupRules(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupRules, self).setUp()

        self.controller = security_groups.SecurityGroupController()
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
            raise exception.NotFound()

        self.stubs.Set(nova.db, 'security_group_get',
                       return_security_group)

        self.parent_security_group = db2

        self.controller = security_groups.SecurityGroupRulesController()

    def test_create_by_cidr(self):
        rule = security_group_rule_template(cidr='10.2.3.124/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg2['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "10.2.3.124/24")

    def test_create_by_group_id(self):
        rule = security_group_rule_template(group_id=self.sg1['id'],
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg2['id'])

    def test_create_by_same_group_id(self):
        rule1 = security_group_rule_template(group_id=self.sg1['id'],
                                             from_port=80, to_port=80,
                                             parent_group_id=self.sg2['id'])
        self.parent_security_group['rules'] = [security_group_rule_db(rule1)]

        rule2 = security_group_rule_template(group_id=self.sg1['id'],
                                             from_port=81, to_port=81,
                                             parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule2})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg2['id'])
        self.assertEquals(security_group_rule['from_port'], 81)
        self.assertEquals(security_group_rule['to_port'], 81)

    def test_create_none_value_from_to_port(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id']}
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertEquals(security_group_rule['from_port'], None)
        self.assertEquals(security_group_rule['to_port'], None)
        self.assertEquals(security_group_rule['group']['name'], 'test')
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg1['id'])

    def test_create_none_value_from_to_port_icmp(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id'],
                'ip_protocol': 'ICMP'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertEquals(security_group_rule['ip_protocol'], 'ICMP')
        self.assertEquals(security_group_rule['from_port'], -1)
        self.assertEquals(security_group_rule['to_port'], -1)
        self.assertEquals(security_group_rule['group']['name'], 'test')
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg1['id'])

    def test_create_none_value_from_to_port_tcp(self):
        rule = {'parent_group_id': self.sg1['id'],
                'group_id': self.sg1['id'],
                'ip_protocol': 'TCP'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertEquals(security_group_rule['ip_protocol'], 'TCP')
        self.assertEquals(security_group_rule['from_port'], 1)
        self.assertEquals(security_group_rule['to_port'], 65535)
        self.assertEquals(security_group_rule['group']['name'], 'test')
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg1['id'])

    def test_create_by_invalid_cidr_json(self):
        rule = security_group_rule_template(
                ip_protocol="tcp",
                from_port=22,
                to_port=22,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/2433")
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_by_invalid_tcp_port_json(self):
        rule = security_group_rule_template(
                ip_protocol="tcp",
                from_port=75534,
                to_port=22,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/24")

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_by_invalid_icmp_port_json(self):
        rule = security_group_rule_template(
                ip_protocol="icmp",
                from_port=1,
                to_port=256,
                parent_group_id=self.sg2['id'],
                cidr="10.2.3.124/24")
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_cidr(self):
        rule = security_group_rule_template(cidr='10.0.0.0/24',
                                            parent_group_id=self.sg2['id'])

        self.parent_security_group['rules'] = [security_group_rule_db(rule)]

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_add_existing_rules_by_group_id(self):
        rule = security_group_rule_template(group_id=1)

        self.parent_security_group['rules'] = [security_group_rule_db(rule)]

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, None)

    def test_create_with_no_security_group_rule_in_body(self):
        rules = {'test': 'test'}
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, rules)

    def test_create_with_invalid_parent_group_id(self):
        rule = security_group_rule_template(parent_group_id='invalid')

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_non_existing_parent_group_id(self):
        rule = security_group_rule_template(group_id='invalid',
                                            parent_group_id=self.invalid_id)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_invalid_protocol(self):
        rule = security_group_rule_template(ip_protocol='invalid-protocol',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_protocol(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['ip_protocol']

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_invalid_from_port(self):
        rule = security_group_rule_template(from_port='666666',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_invalid_to_port(self):
        rule = security_group_rule_template(to_port='666666',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_non_numerical_from_port(self):
        rule = security_group_rule_template(from_port='invalid',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_non_numerical_to_port(self):
        rule = security_group_rule_template(to_port='invalid',
                                            cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_from_port(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['from_port']

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_to_port(self):
        rule = security_group_rule_template(cidr='10.2.2.0/24',
                                            parent_group_id=self.sg2['id'])
        del rule['to_port']

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_invalid_cidr(self):
        rule = security_group_rule_template(cidr='10.2.2222.0/24',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_no_cidr_group(self):
        rule = security_group_rule_template(parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.parent_security_group['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "0.0.0.0/0")

    def test_create_with_invalid_group_id(self):
        rule = security_group_rule_template(group_id='invalid',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_empty_group_id(self):
        rule = security_group_rule_template(group_id='',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_nonexist_group_id(self):
        rule = security_group_rule_template(group_id=self.invalid_id,
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_with_same_group_parent_id_and_group_id(self):
        rule = security_group_rule_template(group_id=self.sg1['id'],
                                            parent_group_id=self.sg1['id'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.sg1['id'])
        self.assertEquals(security_group_rule['group']['name'],
                          self.sg1['name'])

    def _test_create_with_no_ports_and_no_group(self, proto):
        rule = {'ip_protocol': proto, 'parent_group_id': self.sg2['id']}

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})

    def _test_create_with_no_ports(self, proto):
        rule = {'ip_protocol': proto, 'parent_group_id': self.sg2['id'],
                 'group_id': self.sg1['id']}

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})
        security_group_rule = res_dict['security_group_rule']
        expected_rule = {
            'from_port': 1, 'group': {'tenant_id': '123', 'name': 'test'},
            'ip_protocol': proto, 'to_port': 65535, 'parent_group_id':
             self.sg2['id'], 'ip_range': {}, 'id': security_group_rule['id']
        }
        if proto == 'icmp':
            expected_rule['to_port'] = -1
            expected_rule['from_port'] = -1
        self.assertTrue(security_group_rule == expected_rule)

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
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        expected_rule = {
            'from_port': from_port,
            'group': {'tenant_id': '123', 'name': 'test'},
            'ip_protocol': proto, 'to_port': to_port, 'parent_group_id':
             self.sg2['id'], 'ip_range': {}, 'id': security_group_rule['id']
        }
        self.assertTrue(security_group_rule['ip_protocol'] == proto)
        self.assertTrue(security_group_rule['from_port'] == from_port)
        self.assertTrue(security_group_rule['to_port'] == to_port)
        self.assertTrue(security_group_rule == expected_rule)

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

        self.stubs.Set(nova.db, 'security_group_rule_get',
                       security_group_rule_get)
        self.stubs.Set(nova.db, 'security_group_rule_destroy',
                       security_group_rule_destroy)

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules/%s'
                                      % self.sg2['id'])
        self.controller.delete(req, self.sg2['id'])

    def test_delete_invalid_rule_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules' +
                                      '/invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          req, 'invalid')

    def test_delete_non_existing_rule_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules/%s'
                                      % self.invalid_id)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.invalid_id)

    def test_create_rule_quota_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        for num in range(100, 100 + CONF.quota_security_group_rules):
            rule = {
                'ip_protocol': 'tcp', 'from_port': num,
                'to_port': num, 'parent_group_id': self.sg2['id'],
                'group_id': self.sg1['id']
            }
            self.controller.create(req, {'security_group_rule': rule})

        rule = {
            'ip_protocol': 'tcp', 'from_port': '121', 'to_port': '121',
            'parent_group_id': self.sg2['id'], 'group_id': self.sg1['id']
        }
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create,
                          req, {'security_group_rule': rule})

    def test_create_rule_cidr_allow_all(self):
        rule = security_group_rule_template(cidr='0.0.0.0/0',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.parent_security_group['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "0.0.0.0/0")

    def test_create_rule_cidr_ipv6_allow_all(self):
        rule = security_group_rule_template(cidr='::/0',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.parent_security_group['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "::/0")

    def test_create_rule_cidr_allow_some(self):
        rule = security_group_rule_template(cidr='15.0.0.0/8',
                                            parent_group_id=self.sg2['id'])

        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        res_dict = self.controller.create(req, {'security_group_rule': rule})

        security_group_rule = res_dict['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.parent_security_group['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "15.0.0.0/8")

    def test_create_rule_cidr_bad_netmask(self):
        rule = security_group_rule_template(cidr='15.0.0.0/0')
        req = fakes.HTTPRequest.blank('/v2/fake/os-security-group-rules')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_rule': rule})


class TestSecurityGroupRulesXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestSecurityGroupRulesXMLDeserializer, self).setUp()
        self.deserializer = security_groups.SecurityGroupRulesXMLDeserializer()

    def test_create_request(self):
        serial_request = """
<security_group_rule>
  <parent_group_id>12</parent_group_id>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <group_id></group_id>
  <ip_protocol>tcp</ip_protocol>
  <cidr>10.0.0.0/24</cidr>
</security_group_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_rule": {
                "parent_group_id": "12",
                "from_port": "22",
                "to_port": "22",
                "ip_protocol": "tcp",
                "group_id": "",
                "cidr": "10.0.0.0/24",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_protocol_request(self):
        serial_request = """
<security_group_rule>
  <parent_group_id>12</parent_group_id>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <group_id></group_id>
  <cidr>10.0.0.0/24</cidr>
</security_group_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_rule": {
                "parent_group_id": "12",
                "from_port": "22",
                "to_port": "22",
                "group_id": "",
                "cidr": "10.0.0.0/24",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_corrupt_xml(self):
        """Should throw a 400 error on corrupt xml."""
        self.assertRaises(
                exception.MalformedRequestBody,
                self.deserializer.deserialize,
                utils.killer_xml_body())


class TestSecurityGroupXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestSecurityGroupXMLDeserializer, self).setUp()
        self.deserializer = security_groups.SecurityGroupXMLDeserializer()

    def test_create_request(self):
        serial_request = """
<security_group name="test">
   <description>test</description>
</security_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group": {
                "name": "test",
                "description": "test",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_description_request(self):
        serial_request = """
<security_group name="test">
</security_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group": {
                "name": "test",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_name_request(self):
        serial_request = """
<security_group>
<description>test</description>
</security_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group": {
                "description": "test",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_corrupt_xml(self):
        """Should throw a 400 error on corrupt xml."""
        self.assertRaises(
                exception.MalformedRequestBody,
                self.deserializer.deserialize,
                utils.killer_xml_body())


class TestSecurityGroupXMLSerializer(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupXMLSerializer, self).setUp()
        self.namespace = wsgi.XMLNS_V11
        self.rule_serializer = security_groups.SecurityGroupRuleTemplate()
        self.index_serializer = security_groups.SecurityGroupsTemplate()
        self.default_serializer = security_groups.SecurityGroupTemplate()

    def _tag(self, elem):
        tagname = elem.tag
        self.assertEqual(tagname[0], '{')
        tmp = tagname.partition('}')
        namespace = tmp[0][1:]
        self.assertEqual(namespace, self.namespace)
        return tmp[2]

    def _verify_security_group_rule(self, raw_rule, tree):
        self.assertEqual(raw_rule['id'], tree.get('id'))
        self.assertEqual(raw_rule['parent_group_id'],
                         tree.get('parent_group_id'))

        seen = set()
        expected = set(['ip_protocol', 'from_port', 'to_port',
                        'group', 'group/name', 'group/tenant_id',
                        'ip_range', 'ip_range/cidr'])

        for child in tree:
            child_tag = self._tag(child)
            self.assertTrue(child_tag in raw_rule)
            seen.add(child_tag)
            if child_tag in ('group', 'ip_range'):
                for gr_child in child:
                    gr_child_tag = self._tag(gr_child)
                    self.assertTrue(gr_child_tag in raw_rule[child_tag])
                    seen.add('%s/%s' % (child_tag, gr_child_tag))
                    self.assertEqual(gr_child.text,
                                     raw_rule[child_tag][gr_child_tag])
            else:
                self.assertEqual(child.text, raw_rule[child_tag])
        self.assertEqual(seen, expected)

    def _verify_security_group(self, raw_group, tree):
        rules = raw_group['rules']
        self.assertEqual('security_group', self._tag(tree))
        self.assertEqual(raw_group['id'], tree.get('id'))
        self.assertEqual(raw_group['tenant_id'], tree.get('tenant_id'))
        self.assertEqual(raw_group['name'], tree.get('name'))
        self.assertEqual(2, len(tree))
        for child in tree:
            child_tag = self._tag(child)
            if child_tag == 'rules':
                self.assertEqual(2, len(child))
                for idx, gr_child in enumerate(child):
                    self.assertEqual(self._tag(gr_child), 'rule')
                    self._verify_security_group_rule(rules[idx], gr_child)
            else:
                self.assertEqual('description', child_tag)
                self.assertEqual(raw_group['description'], child.text)

    def test_rule_serializer(self):
        raw_rule = dict(
            id='123',
            parent_group_id='456',
            ip_protocol='tcp',
            from_port='789',
            to_port='987',
            group=dict(name='group', tenant_id='tenant'),
            ip_range=dict(cidr='10.0.0.0/8'))
        rule = dict(security_group_rule=raw_rule)
        text = self.rule_serializer.serialize(rule)

        tree = etree.fromstring(text)

        self.assertEqual('security_group_rule', self._tag(tree))
        self._verify_security_group_rule(raw_rule, tree)

    def test_group_serializer(self):
        rules = [dict(
                id='123',
                parent_group_id='456',
                ip_protocol='tcp',
                from_port='789',
                to_port='987',
                group=dict(name='group1', tenant_id='tenant1'),
                ip_range=dict(cidr='10.55.44.0/24')),
                 dict(
                id='654',
                parent_group_id='321',
                ip_protocol='udp',
                from_port='234',
                to_port='567',
                group=dict(name='group2', tenant_id='tenant2'),
                ip_range=dict(cidr='10.44.55.0/24'))]
        raw_group = dict(
            id='890',
            description='description',
            name='name',
            tenant_id='tenant',
            rules=rules)
        sg_group = dict(security_group=raw_group)
        text = self.default_serializer.serialize(sg_group)

        tree = etree.fromstring(text)

        self._verify_security_group(raw_group, tree)

    def test_groups_serializer(self):
        rules = [dict(
                id='123',
                parent_group_id='1234',
                ip_protocol='tcp',
                from_port='12345',
                to_port='123456',
                group=dict(name='group1', tenant_id='tenant1'),
                ip_range=dict(cidr='10.123.0.0/24')),
                 dict(
                id='234',
                parent_group_id='2345',
                ip_protocol='udp',
                from_port='23456',
                to_port='234567',
                group=dict(name='group2', tenant_id='tenant2'),
                ip_range=dict(cidr='10.234.0.0/24')),
                 dict(
                id='345',
                parent_group_id='3456',
                ip_protocol='tcp',
                from_port='34567',
                to_port='345678',
                group=dict(name='group3', tenant_id='tenant3'),
                ip_range=dict(cidr='10.345.0.0/24')),
                 dict(
                id='456',
                parent_group_id='4567',
                ip_protocol='udp',
                from_port='45678',
                to_port='456789',
                group=dict(name='group4', tenant_id='tenant4'),
                ip_range=dict(cidr='10.456.0.0/24'))]
        groups = [dict(
                id='567',
                description='description1',
                name='name1',
                tenant_id='tenant1',
                rules=rules[0:2]),
                  dict(
                id='678',
                description='description2',
                name='name2',
                tenant_id='tenant2',
                rules=rules[2:4])]
        sg_groups = dict(security_groups=groups)
        text = self.index_serializer.serialize(sg_groups)

        tree = etree.fromstring(text)

        self.assertEqual('security_groups', self._tag(tree))
        self.assertEqual(len(groups), len(tree))
        for idx, child in enumerate(tree):
            self._verify_security_group(groups[idx], child)


UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get_all(*args, **kwargs):
    base = {'id': 1, 'description': 'foo', 'user_id': 'bar',
            'project_id': 'baz', 'deleted': False, 'deleted_at': None,
            'updated_at': None, 'created_at': None}
    db_list = [
        fakes.stub_instance(
            1, uuid=UUID1,
            security_groups=[dict(base, **{'name': 'fake-0-0'}),
                             dict(base, **{'name': 'fake-0-1'})]),
        fakes.stub_instance(
            2, uuid=UUID2,
            security_groups=[dict(base, **{'name': 'fake-1-0'}),
                             dict(base, **{'name': 'fake-1-1'})])
    ]

    return instance_obj._make_instance_list(args[1],
                                            instance_obj.InstanceList(),
                                            db_list,
                                            ['metadata', 'system_metadata',
                                             'security_groups', 'info_cache'])


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3,
                               security_groups=[{'name': 'fake-2-0'},
                                                {'name': 'fake-2-1'}])
    return fake_instance.fake_instance_obj(args[1],
               expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS, **inst)


def fake_compute_create(*args, **kwargs):
    return ([fake_compute_get(*args, **kwargs)], '')


def fake_get_instances_security_groups_bindings(inst, context):
    return {UUID1: [{'name': 'fake-0-0'}, {'name': 'fake-0-1'}],
            UUID2: [{'name': 'fake-1-0'}, {'name': 'fake-1-1'}]}


class SecurityGroupsOutputTest(test.TestCase):
    content_type = 'application/json'

    def setUp(self):
        super(SecurityGroupsOutputTest, self).setUp()
        self.controller = security_groups.SecurityGroupController()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(compute.api.API, 'create', fake_compute_create)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Security_groups'])

    def _make_request(self, url, body=None):
        req = webob.Request.blank(url)
        if body:
            req.method = 'POST'
            req.body = self._encode_body(body)
        req.content_type = self.content_type
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=('servers',)))
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
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        res = self._make_request(url, {'server': server})
        self.assertEqual(res.status_int, 202)
        server = self._get_server(res.body)
        for i, group in enumerate(self._get_groups(server)):
            name = 'fake-2-%s' % i
            self.assertEqual(group.get('name'), name)

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID3
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

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        url = '/v2/fake/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class SecurityGroupsOutputXmlTest(SecurityGroupsOutputTest):
    content_type = 'application/xml'

    class MinimalCreateServerTemplate(xmlutil.TemplateBuilder):
        def construct(self):
            root = xmlutil.TemplateElement('server', selector='server')
            root.set('name')
            root.set('id')
            root.set('imageRef')
            root.set('flavorRef')
            return xmlutil.MasterTemplate(root, 1,
                                          nsmap={None: xmlutil.XMLNS_V11})

    def _encode_body(self, body):
        serializer = self.MinimalCreateServerTemplate()
        return serializer.serialize(body)

    def _get_server(self, body):
        return etree.XML(body)

    def _get_servers(self, body):
        return etree.XML(body).getchildren()

    def _get_groups(self, server):
        # NOTE(vish): we are adding security groups without an extension
        #             namespace so we don't break people using the existing
        #             functionality, but that means we need to use find with
        #             the existing server namespace.
        namespace = server.nsmap[None]
        return server.find('{%s}security_groups' % namespace).getchildren()

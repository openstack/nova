# Copyright (c) 2014 Cisco Systems, Inc.
# All Rights Reserved.
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

import copy
from unittest import mock

from oslo_utils.fixture import uuidsentinel
from oslo_utils import uuidutils
import webob

from nova.api.openstack import api_version_request as avr
from nova.api.openstack.compute import server_groups as sg_v21
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures
from nova.tests.unit.api.openstack import fakes


class AttrDict(dict):
    def __getattr__(self, k):
        return self[k]


def server_group_template(**kwargs):
    sgroup = kwargs.copy()
    sgroup.setdefault('name', 'test')
    return sgroup


def server_group_resp_template(**kwargs):
    sgroup = kwargs.copy()
    sgroup.setdefault('name', 'test')
    if 'policy' not in kwargs:
        sgroup.setdefault('policies', [])
    sgroup.setdefault('members', [])
    return sgroup


def server_group_db(sg):
    attrs = copy.deepcopy(sg)
    if 'id' in attrs:
        attrs['uuid'] = attrs.pop('id')
    if 'policies' in attrs:
        policies = attrs.pop('policies')
        attrs['policies'] = policies
    else:
        attrs['policies'] = []
    if 'policy' in attrs:
        del attrs['policies']
    if 'members' in attrs:
        members = attrs.pop('members')
        attrs['members'] = members
    else:
        attrs['members'] = []
    attrs['deleted'] = 0
    attrs['deleted_at'] = None
    attrs['created_at'] = None
    attrs['updated_at'] = None
    if 'user_id' not in attrs:
        attrs['user_id'] = fakes.FAKE_USER_ID
    if 'project_id' not in attrs:
        attrs['project_id'] = fakes.FAKE_PROJECT_ID
    attrs['id'] = 7

    return AttrDict(attrs)


class ServerGroupTestV21(test.NoDBTestCase):
    USES_DB_SELF = True
    validation_error = exception.ValidationError
    wsgi_api_version = '2.1'

    def setUp(self):
        super(ServerGroupTestV21, self).setUp()
        self._setup_controller()
        self.member_req = fakes.HTTPRequest.member_req('')
        self.reader_req = fakes.HTTPRequest.reader_req('')
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.foo_req = fakes.HTTPRequest.blank('', project_id='foo')
        self.policy = self.useFixture(fixtures.RealPolicyFixture())

        self.useFixture(fixtures.Database(database='api'))
        cells = fixtures.CellDatabases()
        cells.add_cell_database(uuidsentinel.cell1)
        cells.add_cell_database(uuidsentinel.cell2)
        self.useFixture(cells)

        ctxt = context.get_admin_context()
        self.cells = {}
        for uuid in (uuidsentinel.cell1, uuidsentinel.cell2):
            cm = objects.CellMapping(context=ctxt,
                                uuid=uuid,
                                database_connection=uuid,
                                transport_url=uuid)
            cm.create()
            self.cells[cm.uuid] = cm

    def _setup_controller(self):
        self.controller = sg_v21.ServerGroupController()

    def test_create_server_group_with_no_policies(self):
        sgroup = server_group_template()
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def _create_server_group_normal(self, policies=None, policy=None,
                                    rules=None):
        sgroup = server_group_template()
        sgroup['policies'] = policies
        res_dict = self.controller.create(self.member_req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policies'], policies)

    def test_create_server_group_with_new_policy_before_264(self):
        req = fakes.HTTPRequest.member_req('', version='2.63')
        policy = 'anti-affinity'
        rules = {'max_server_per_host': 3}
        # 'policy' isn't an acceptable request key before 2.64
        sgroup = server_group_template(policy=policy)
        result = self.assertRaises(
            self.validation_error, self.controller.create,
            req, body={'server_group': sgroup})
        self.assertIn(
            "Invalid input for field/attribute server_group",
            str(result)
        )
        # 'rules' isn't an acceptable request key before 2.64
        sgroup = server_group_template(rules=rules)
        result = self.assertRaises(
            self.validation_error, self.controller.create,
            req, body={'server_group': sgroup})
        self.assertIn(
            "Invalid input for field/attribute server_group",
            str(result)
        )

    def test_create_server_group(self):
        policies = ['affinity', 'anti-affinity']
        for policy in policies:
            self._create_server_group_normal(policies=[policy])

    def test_create_server_group_rbac_default(self):
        sgroup = server_group_template()
        sgroup['policies'] = ['affinity']

        # test as admin
        self.controller.create(self.admin_req, body={'server_group': sgroup})

        # test as non-admin
        self.controller.create(self.member_req, body={'server_group': sgroup})

    def _create_instance(self, ctx, cell, host='host1'):
        with context.target_cell(ctx, cell) as cctx:
            instance = objects.Instance(context=cctx,
                                        image_ref=uuidsentinel.fake_image_ref,
                                        compute_id=123,
                                        node='node1', reservation_id='a',
                                        host=host,
                                        project_id=fakes.FAKE_PROJECT_ID,
                                        vm_state='fake',
                                        system_metadata={'key': 'value'})
            instance.create()
        im = objects.InstanceMapping(context=ctx,
                                     project_id=ctx.project_id,
                                     user_id=ctx.user_id,
                                     cell_mapping=cell,
                                     instance_uuid=instance.uuid)
        im.create()
        return instance

    def _create_instance_group(self, context, members, policy=None):
        ig = objects.InstanceGroup(context=context, name='fake_name',
                  user_id='fake_user', project_id=fakes.FAKE_PROJECT_ID,
                  members=members, policy=policy)
        ig.create()
        return ig.uuid

    def _create_groups_and_instances(self, ctx):
        cell1 = self.cells[uuidsentinel.cell1]
        cell2 = self.cells[uuidsentinel.cell2]
        instances = [self._create_instance(ctx, cell=cell1),
                     self._create_instance(ctx, cell=cell2),
                     self._create_instance(ctx, cell=None)]
        members = [instance.uuid for instance in instances]
        ig_uuid = self._create_instance_group(ctx, members)
        return (ig_uuid, instances, members)

    def _test_list_server_group_all(self, api_version='2.1'):
        self._test_list_server_group(api_version=api_version,
            limited='',
            path='/os-server-groups?all_projects=True')

    def _test_list_server_group_offset_and_limit(self, api_version='2.1'):
        self._test_list_server_group(api_version=api_version,
            limited='&offset=1&limit=1',
            path='/os-server-groups?all_projects=True')

    @mock.patch('nova.objects.InstanceGroupList.get_by_project_id')
    @mock.patch('nova.objects.InstanceGroupList.get_all')
    def _test_list_server_group(self, mock_get_all, mock_get_by_project,
                                path, api_version='2.1', limited=None):
        policies = ['anti-affinity']
        policy = "anti-affinity"
        members = []
        metadata = {}  # always empty
        names = ['default-x', 'test']
        p_id = fakes.FAKE_PROJECT_ID
        u_id = fakes.FAKE_USER_ID
        ver = avr.APIVersionRequest(api_version)
        if ver >= avr.APIVersionRequest("2.64"):
            sg1 = server_group_resp_template(id=uuidsentinel.sg1_id,
                                             name=names[0],
                                             policy=policy,
                                             rules={},
                                             members=members,
                                             project_id=p_id,
                                             user_id=u_id)
            sg2 = server_group_resp_template(id=uuidsentinel.sg2_id,
                                             name=names[1],
                                             policy=policy,
                                             rules={},
                                             members=members,
                                             project_id=p_id,
                                             user_id=u_id)
        elif ver >= avr.APIVersionRequest("2.13"):
            sg1 = server_group_resp_template(id=uuidsentinel.sg1_id,
                                            name=names[0],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata,
                                            project_id=p_id,
                                            user_id=u_id)
            sg2 = server_group_resp_template(id=uuidsentinel.sg2_id,
                                            name=names[1],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata,
                                            project_id=p_id,
                                            user_id=u_id)
        else:
            sg1 = server_group_resp_template(id=uuidsentinel.sg1_id,
                                            name=names[0],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata)
            sg2 = server_group_resp_template(id=uuidsentinel.sg2_id,
                                            name=names[1],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata)
        tenant_groups = [sg2]
        all_groups = [sg1, sg2]

        if limited:
            all = {'server_groups': [sg2]}
            tenant_specific = {'server_groups': []}
        else:
            all = {'server_groups': all_groups}
            tenant_specific = {'server_groups': tenant_groups}

        def return_all_server_groups():
            return objects.InstanceGroupList(
                objects=[objects.InstanceGroup(
                    **server_group_db(sg)) for sg in all_groups])

        mock_get_all.return_value = return_all_server_groups()

        def return_tenant_server_groups():
            return objects.InstanceGroupList(
                objects=[objects.InstanceGroup(
                    **server_group_db(sg)) for sg in tenant_groups])

        mock_get_by_project.return_value = return_tenant_server_groups()

        path = path or '/os-server-groups?all_projects=True'
        if limited:
            path += limited
        reader_req = fakes.HTTPRequest.reader_req(path, version=api_version)
        admin_req = fakes.HTTPRequest.blank(path, use_admin_context=True,
                                            version=api_version)

        # test as admin
        res_dict = self.controller.index(admin_req)
        self.assertEqual(all, res_dict)

        # test as non-admin
        res_dict = self.controller.index(reader_req)
        self.assertEqual(tenant_specific, res_dict)

    @mock.patch('nova.objects.InstanceGroupList.get_by_project_id')
    def _test_list_server_group_by_tenant(self, mock_get_by_project,
                                         api_version='2.1'):
        policies = ['anti-affinity']
        members = []
        metadata = {}  # always empty
        names = ['default-x', 'test']
        p_id = fakes.FAKE_PROJECT_ID
        u_id = fakes.FAKE_USER_ID
        if api_version >= '2.13':
            sg1 = server_group_resp_template(id=uuidsentinel.sg1_id,
                                            name=names[0],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata,
                                            project_id=p_id,
                                            user_id=u_id)
            sg2 = server_group_resp_template(id=uuidsentinel.sg2_id,
                                            name=names[1],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata,
                                            project_id=p_id,
                                            user_id=u_id)
        else:
            sg1 = server_group_resp_template(id=uuidsentinel.sg1_id,
                                            name=names[0],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata)
            sg2 = server_group_resp_template(id=uuidsentinel.sg2_id,
                                            name=names[1],
                                            policies=policies,
                                            members=members,
                                            metadata=metadata)
        groups = [sg1, sg2]
        expected = {'server_groups': groups}

        def return_server_groups():
            return objects.InstanceGroupList(
                objects=[objects.InstanceGroup(
                    **server_group_db(sg)) for sg in groups])

        return_get_by_project = return_server_groups()
        mock_get_by_project.return_value = return_get_by_project
        path = '/os-server-groups'
        req = fakes.HTTPRequest.reader_req(path, version=api_version)
        res_dict = self.controller.index(req)
        self.assertEqual(expected, res_dict)

    def test_display_members(self):
        ctx = context.RequestContext('fake_user', fakes.FAKE_PROJECT_ID)
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        res_dict = self.controller.show(self.reader_req, ig_uuid)
        result_members = res_dict['server_group']['members']
        self.assertEqual(3, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_display_members_with_nonexistent_group(self):
        self.assertRaises(
            webob.exc.HTTPNotFound,
            self.controller.show, self.reader_req, uuidsentinel.group)

    def test_display_active_members_only(self):
        ctx = context.RequestContext('fake_user', fakes.FAKE_PROJECT_ID,
                                     roles=['member', 'reader'])
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)

        # delete an instance
        im = objects.InstanceMapping.get_by_instance_uuid(ctx,
                                                          instances[1].uuid)
        with context.target_cell(ctx, im.cell_mapping) as cctxt:
            instances[1]._context = cctxt
            instances[1].destroy()

        # check that the instance does not exist
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid,
                          ctx, instances[1].uuid)
        res_dict = self.controller.show(self.reader_req, ig_uuid)
        result_members = res_dict['server_group']['members']
        # check that only the active instance is displayed
        self.assertEqual(2, len(result_members))
        self.assertIn(instances[0].uuid, result_members)

    def test_display_members_rbac_default(self):
        ctx = context.RequestContext('fake_user', fakes.FAKE_PROJECT_ID)
        ig_uuid = self._create_groups_and_instances(ctx)[0]

        # test as admin
        self.controller.show(self.admin_req, ig_uuid)

        # test as non-admin, same project
        self.controller.show(self.reader_req, ig_uuid)

        # test as non-admin, different project
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.foo_req, ig_uuid)

    def test_create_server_group_with_non_alphanumeric_in_name(self):
        # The fix for bug #1434335 expanded the allowable character set
        # for server group names to include non-alphanumeric characters
        # if they are printable.

        sgroup = server_group_template(name='good* $%name',
                                       policies=['affinity'])
        res_dict = self.controller.create(self.member_req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'good* $%name')

    def test_create_server_group_with_illegal_name(self):
        # blank name
        sgroup = server_group_template(name='', policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with length 256
        sgroup = server_group_template(name='1234567890' * 26,
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # non-string name
        sgroup = server_group_template(name=12, policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with leading spaces
        sgroup = server_group_template(name='  leading spaces',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with trailing spaces
        sgroup = server_group_template(name='trailing space ',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with all spaces
        sgroup = server_group_template(name='    ',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with unprintable character
        sgroup = server_group_template(name='bad\x00name',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # name with out of range char U0001F4A9
        sgroup = server_group_template(name=u"\U0001F4A9",
                                       policies=['affinity'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def test_create_server_group_with_illegal_policies(self):
        # blank policy
        sgroup = server_group_template(name='fake-name', policies='')
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # policy as integer
        sgroup = server_group_template(name='fake-name', policies=7)
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # policy as string
        sgroup = server_group_template(name='fake-name', policies='invalid')
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

        # policy as None
        sgroup = server_group_template(name='fake-name', policies=None)
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def test_create_server_group_conflicting_policies(self):
        sgroup = server_group_template()
        policies = ['anti-affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def test_create_server_group_with_duplicate_policies(self):
        sgroup = server_group_template()
        policies = ['affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def test_create_server_group_not_supported(self):
        sgroup = server_group_template()
        policies = ['storage-affinity', 'anti-affinity', 'rack-affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.member_req, body={'server_group': sgroup})

    def test_create_server_group_with_no_body(self):
        self.assertRaises(self.validation_error,
                          self.controller.create, self.member_req, body=None)

    def test_create_server_group_with_no_server_group(self):
        body = {'no-instanceGroup': None}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.member_req, body=body)

    def test_list_server_group_by_tenant(self):
        self._test_list_server_group_by_tenant(
            api_version=self.wsgi_api_version)

    def test_list_server_group_all_v20(self):
        self._test_list_server_group_all(api_version='2.0')

    def test_list_server_group_all(self):
        self._test_list_server_group_all(
            api_version=self.wsgi_api_version)

    def test_list_server_group_offset_and_limit(self):
        self._test_list_server_group_offset_and_limit(
            api_version=self.wsgi_api_version)

    def test_list_server_groups_rbac_default(self):
        # test as admin
        self.controller.index(self.admin_req)

        # test as non-admin
        self.controller.index(self.reader_req)

    def test_list_server_group_multiple_param(self):
        self._test_list_server_group(api_version=self.wsgi_api_version,
            limited='&offset=2&limit=2&limit=1&offset=1',
            path='/os-server-groups?all_projects=False&all_projects=True')

    def test_list_server_group_additional_param(self):
        self._test_list_server_group(api_version=self.wsgi_api_version,
            limited='&offset=1&limit=1',
            path='/os-server-groups?dummy=False&all_projects=True')

    def test_list_server_group_param_as_int(self):
        self._test_list_server_group(api_version=self.wsgi_api_version,
            limited='&offset=1&limit=1',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_negative_int_as_offset(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&offset=-1',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_string_int_as_offset(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&offset=dummy',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_multiparam_string_as_offset(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&offset=dummy&offset=1',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_negative_int_as_limit(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&limit=-1',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_string_int_as_limit(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&limit=dummy',
            path='/os-server-groups?all_projects=1')

    def test_list_server_group_multiparam_string_as_limit(self):
        self.assertRaises(exception.ValidationError,
            self._test_list_server_group,
            api_version=self.wsgi_api_version,
            limited='&limit=dummy&limit=1',
            path='/os-server-groups?all_projects=1')

    @mock.patch('nova.objects.InstanceGroup.destroy')
    def test_delete_server_group_by_id(self, mock_destroy):
        sg = server_group_template(id=uuidsentinel.sg1_id)

        def return_server_group(_cls, context, group_id):
            self.assertEqual(sg['id'], group_id)
            return objects.InstanceGroup(**server_group_db(sg))

        self.stub_out('nova.objects.InstanceGroup.get_by_uuid',
                      return_server_group)

        resp = self.controller.delete(self.member_req, uuidsentinel.sg1_id)
        mock_destroy.assert_called_once_with()

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller, sg_v21.ServerGroupController):
            status_int = self.controller.delete.wsgi_code
        else:
            status_int = resp.status_int
        self.assertEqual(204, status_int)

    def test_delete_non_existing_server_group(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.member_req, 'invalid')

    def test_delete_server_group_rbac_default(self):
        ctx = context.RequestContext('fake_user', fakes.FAKE_PROJECT_ID)

        # test as admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        self.controller.delete(self.admin_req, ig_uuid)

        # test as non-admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        self.controller.delete(self.member_req, ig_uuid)


class ServerGroupTestV213(ServerGroupTestV21):
    wsgi_api_version = '2.13'

    def _setup_controller(self):
        self.controller = sg_v21.ServerGroupController()

    def test_list_server_group_all(self):
        self._test_list_server_group_all(api_version='2.13')

    def test_list_server_group_offset_and_limit(self):
        self._test_list_server_group_offset_and_limit(api_version='2.13')

    def test_list_server_group_by_tenant(self):
        self._test_list_server_group_by_tenant(api_version='2.13')


class ServerGroupTestV264(ServerGroupTestV213):
    wsgi_api_version = '2.64'

    def _setup_controller(self):
        self.controller = sg_v21.ServerGroupController()

    def _create_server_group_normal(self, policies=None, policy=None,
                                    rules=None):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        sgroup = server_group_template()
        sgroup['rules'] = rules or {}
        sgroup['policy'] = policy
        res_dict = self.controller.create(req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policy'], policy)
        self.assertEqual(res_dict['server_group']['rules'], rules or {})
        return res_dict['server_group']['id']

    def test_list_server_group_all(self):
        self._test_list_server_group_all(api_version=self.wsgi_api_version)

    def test_create_and_show_server_group(self):
        policies = ['affinity', 'anti-affinity']
        for policy in policies:
            g_uuid = self._create_server_group_normal(
                policy=policy)
            res_dict = self._display_server_group(g_uuid)
            self.assertEqual(res_dict['server_group']['policy'], policy)
            self.assertEqual(res_dict['server_group']['rules'], {})

    def _display_server_group(self, uuid):
        req = fakes.HTTPRequest.reader_req('', version=self.wsgi_api_version)
        group = self.controller.show(req, uuid)
        return group

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=33)
    def test_create_and_show_server_group_with_rules(self, mock_get_v):
        policy = 'anti-affinity'
        rules = {'max_server_per_host': 3}
        g_uuid = self._create_server_group_normal(
            policy=policy, rules=rules)
        res_dict = self._display_server_group(g_uuid)
        self.assertEqual(res_dict['server_group']['policy'], policy)
        self.assertEqual(res_dict['server_group']['rules'], rules)

    def test_create_affinity_server_group_with_invalid_policy(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        sgroup = server_group_template(policy='affinity',
                                       rules={'max_server_per_host': 3})
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.create, req, body={'server_group': sgroup})
        self.assertIn("Only anti-affinity policy supports rules", str(result))

    def test_create_anti_affinity_server_group_with_invalid_rules(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        # A negative test for key is unknown, the value is not positive
        # and not integer
        invalid_rules = [{'unknown_key': '3'},
                         {'max_server_per_host': 0},
                         {'max_server_per_host': 'foo'}]

        for r in invalid_rules:
            sgroup = server_group_template(policy='anti-affinity', rules=r)
            result = self.assertRaises(
                self.validation_error, self.controller.create,
                req, body={'server_group': sgroup})
            self.assertIn(
                "Invalid input for field/attribute", str(result)
            )

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=32)
    def test_create_server_group_with_low_version_compute_service(self,
                                                                  mock_get_v):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        sgroup = server_group_template(policy='anti-affinity',
                                       rules={'max_server_per_host': 3})
        result = self.assertRaises(
            webob.exc.HTTPConflict,
            self.controller.create, req, body={'server_group': sgroup})
        self.assertIn("Creating an anti-affinity group with rule "
                      "max_server_per_host > 1 is not yet supported.",
                      str(result))

    def test_create_server_group(self):
        policies = ['affinity', 'anti-affinity']
        for policy in policies:
            self._create_server_group_normal(policy=policy)

    def test_policies_since_264(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        # 'policies' isn't allowed in request >= 2.64
        sgroup = server_group_template(policies=['anti-affinity'])
        self.assertRaises(
            self.validation_error, self.controller.create,
            req, body={'server_group': sgroup})

    def test_create_server_group_without_policy(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        # 'policy' is required request key in request >= 2.64
        sgroup = server_group_template()
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

    def test_create_server_group_with_illegal_policies(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        # blank policy
        sgroup = server_group_template(policy='')
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

        # policy as integer
        sgroup = server_group_template(policy=7)
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

        # policy as string
        sgroup = server_group_template(policy='invalid')
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

        # policy as None
        sgroup = server_group_template(policy=None)
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

    def test_additional_params(self):
        req = fakes.HTTPRequest.member_req('', version=self.wsgi_api_version)
        sgroup = server_group_template(unknown='unknown')
        self.assertRaises(self.validation_error, self.controller.create,
                          req, body={'server_group': sgroup})

    def test_update_server_group_not_found(self):
        """We raise a 404 if the server group does not exist."""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller.update, req, uuidsentinel.group1, body={})

    def test_update_server_group_empty(self):
        """We do not fail if the user doesn't request any changes"""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        res_dict = self.controller.update(req, ig_uuid, body={})
        result_members = res_dict['server_group']['members']
        self.assertEqual(3, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_update_server_group_add_remove_overlap(self):
        """We do not accept changes, if there's a server to be both added and
        removed, because the result would depend on implementation details if
        we remove first or add first.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        body = {
            'add_members': [uuidsentinel.uuid1, uuidsentinel.uuid2],
            'remove_members': [uuidsentinel.uuid2, uuidsentinel.uuid3],
        }
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, ig_uuid, body=body)
        self.assertIn('Parameters "add_members" and "remove_members" are '
                      'overlapping in {}'.format(uuidsentinel.uuid2),
                      str(result))

    def test_update_server_group_remove_nonexisting(self):
        """Don't fail if the user tries to remove a server not being member of
        the server group.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        body = {
            'remove_members': [uuidsentinel.uuid4],
        }
        res_dict = self.controller.update(req, ig_uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(3, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_update_server_group_add_already_added(self):
        """Don't fail if the user adds a server that's already a member of the
        server group.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        body = {
            'add_members': [members[0]],
        }
        res_dict = self.controller.update(req, ig_uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(3, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_update_server_group_add_against_policy_affinity(self):
        """Fail if adding the server would break the policy."""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1')]

        ig_uuid = self._create_instance_group(ctx, [i.uuid for i in instances],
                                         policy='affinity')

        cell1 = self.cells[uuidsentinel.cell1]
        new_instance = self._create_instance(ctx, cell1, host='host2')

        body = {
            'add_members': [new_instance.uuid],
        }
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, ig_uuid, body=body)
        self.assertIn("Adding instance(s) {} would violate policy 'affinity'."
                      .format(new_instance.uuid),
                      str(result))

    def test_update_server_group_add_against_policy_anti_affinity(self):
        """Fail if adding the server would break the policy."""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1')]

        ig_uuid = self._create_instance_group(ctx, [i.uuid for i in instances],
                                         policy='anti-affinity')

        cell1 = self.cells[uuidsentinel.cell1]
        new_instance = self._create_instance(ctx, cell1, host='host1')

        body = {
            'add_members': [new_instance.uuid],
        }
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, ig_uuid, body=body)
        self.assertIn("Adding instance(s) {} would violate policy "
                      "'anti-affinity'.".format(new_instance.uuid),
                      str(result))

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_update_server_group_add_with_remove_fixes_policy(self,
                                                              mock_req_spec):
        """Don't fail if adding a server would break the policy, but the remove
        in the same request fixes that.
        """
        """Fail if adding the server would break the policy."""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1'),
                     self._create_instance(ctx, cell1, host='host2')]

        ig_uuid = self._create_instance_group(ctx, [i.uuid for i in instances],
                                         policy='anti-affinity')

        cell1 = self.cells[uuidsentinel.cell1]
        new_instance = self._create_instance(ctx, cell1, host='host2')

        body = {
            'add_members': [new_instance.uuid],
            'remove_members': [instances[1].uuid],
        }
        res_dict = self.controller.update(req, ig_uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(2, len(result_members))
        for member in [instances[0].uuid, new_instance.uuid]:
            self.assertIn(member, result_members)

    def test_update_server_group_add_nonexisting_instance(self):
        """Fail if the instances the user tries to add does not exist."""
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        body = {
            'add_members': [uuidsentinel.uuid1],
        }
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, ig_uuid, body=body)
        self.assertIn('One or more members in add_members cannot be found: '
                      '{}'.format(uuidsentinel.uuid1),
                      str(result))

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_update_server_group_add_instance_multiple_cells(self,
                                                             mock_req_spec):
        """Don't fail if the instance the user tries to add is in another cell.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        cell1 = self.cells[uuidsentinel.cell1]
        cell2 = self.cells[uuidsentinel.cell2]
        new_instances = [self._create_instance(ctx, cell1),
                         self._create_instance(ctx, cell2)]
        body = {
            'add_members': [i.uuid for i in new_instances],
        }
        res_dict = self.controller.update(req, ig_uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(5, len(result_members))
        for member in members:
            self.assertIn(member, result_members)
        for instance in new_instances:
            self.assertIn(instance.uuid, result_members)

    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_update_server_group_add_against_soft_policy(self, mock_req_spec):
        """Don't fail if the policy would fail, but it's a soft-* policy - they
        are best-effort by design.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1')]

        ig_uuid = self._create_instance_group(ctx, [i.uuid for i in instances],
                                         policy='soft-anti-affinity')

        cell1 = self.cells[uuidsentinel.cell1]
        new_instance = self._create_instance(ctx, cell1, host='host1')

        body = {
            'add_members': [new_instance.uuid],
        }
        res_dict = self.controller.update(req, ig_uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(2, len(result_members))
        for member in [instances[0].uuid, new_instance.uuid]:
            self.assertIn(member, result_members)

    @mock.patch('nova.objects.InstanceGroupList.get_by_instance_uuids')
    def test_update_server_group_add_already_in_other(self, mock_gbiu):
        """If any of the servers is already part of another server-group, we
        fail.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1')]

        ig_uuid = self._create_instance_group(ctx, [i.uuid for i in instances])

        cell1 = self.cells[uuidsentinel.cell1]
        new_instance = self._create_instance(ctx, cell1, host='host1')
        ig_uuid2 = self._create_instance_group(ctx, [new_instance.uuid])

        mock_gbiu.return_value = objects.InstanceGroupList(
                objects=[objects.InstanceGroup(
                    **server_group_db({'id': ig_uuid}))])

        body = {
            'add_members': [instances[0].uuid],
        }
        result = self.assertRaises(webob.exc.HTTPBadRequest,
            self.controller.update, req, ig_uuid2, body=body)
        self.assertIn('One ore more members in add_members is already '
                      'assigned to another server group. Server groups: {}'
                      .format(ig_uuid), str(result))

    @mock.patch('nova.objects.InstanceGroupList.get_by_instance_uuids')
    @mock.patch.object(objects.RequestSpec, 'get_by_instance_uuid')
    def test_update_server_group_updates_request_spec(self, mock_req_spec,
                                                      mock_gbiu):
        """If we update the server-group membership of a server, we also have
        to update the appropriate RequestSpec attribute.
        """
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      version=self.wsgi_api_version)
        ctx = context.RequestContext('fake_user', 'fake')

        cell1 = self.cells[uuidsentinel.cell1]
        instances = [self._create_instance(ctx, cell1, host='host1')]

        ig = objects.InstanceGroup(context=ctx, name='fake_name',
                  user_id='fake_user', project_id='fake',
                  members=[i.uuid for i in instances], policy='anti-affinity')
        ig.create()

        new_instance = self._create_instance(ctx, cell1, host='host2')

        mock_gbiu.return_value = objects.InstanceGroupList(
                objects=[objects.InstanceGroup(
                    **server_group_db({'id': ig.uuid}))])

        fake_spec_remove = mock.Mock(instance_group=ig)
        fake_spec_add = mock.Mock(instance_group=None)

        def _get_req_spec(context, instance_uuid):
            if instance_uuid == new_instance.uuid:
                return fake_spec_add
            else:
                return fake_spec_remove

        mock_req_spec.side_effect = _get_req_spec

        self.assertEqual(ig.uuid, fake_spec_remove.instance_group.uuid)
        self.assertIsNone(fake_spec_add.instance_group)

        body = {
            'add_members': [new_instance.uuid],
            'remove_members': [instances[0].uuid]
        }
        res_dict = self.controller.update(req, ig.uuid, body=body)
        result_members = res_dict['server_group']['members']
        self.assertEqual(1, len(result_members))
        for member in [new_instance.uuid]:
            self.assertIn(member, result_members)

        fake_spec_remove.save.assert_called()
        self.assertIsNone(fake_spec_remove.instance_group)
        ig.members = [new_instance.uuid]
        self.assertEqual(ig.uuid, fake_spec_add.instance_group.uuid)
        fake_spec_add.save.assert_called()


class ServerGroupTestV275(ServerGroupTestV264):
    wsgi_api_version = '2.75'

    def test_list_server_group_additional_param_old_version(self):
        self._test_list_server_group(api_version='2.74',
            limited='&offset=1&limit=1',
            path='/os-server-groups?dummy=False&all_projects=True')

    def test_list_server_group_additional_param(self):
        req = fakes.HTTPRequest.reader_req('/os-server-groups?dummy=False',
                                           version=self.wsgi_api_version)
        self.assertRaises(self.validation_error, self.controller.index,
                          req)

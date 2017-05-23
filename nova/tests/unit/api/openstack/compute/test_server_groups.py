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

import mock
from oslo_utils import uuidutils
import webob

from nova.api.openstack.compute import server_groups as sg_v21
from nova import context
import nova.db
from nova import exception
from nova import objects
from nova.policies import server_groups as sg_policies
from nova import test
from nova.tests import fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import policy_fixture
from nova.tests import uuidsentinel


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
    sgroup.setdefault('policies', [])
    sgroup.setdefault('members', [])
    return sgroup


def server_group_db(sg):
    attrs = sg.copy()
    if 'id' in attrs:
        attrs['uuid'] = attrs.pop('id')
    if 'policies' in attrs:
        policies = attrs.pop('policies')
        attrs['policies'] = policies
    else:
        attrs['policies'] = []
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

    def setUp(self):
        super(ServerGroupTestV21, self).setUp()
        self._setup_controller()
        self.req = fakes.HTTPRequest.blank('')
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.foo_req = fakes.HTTPRequest.blank('', project_id='foo')
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())

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
                          self.req, body={'server_group': sgroup})

    def _create_server_group_normal(self, policies):
        sgroup = server_group_template()
        sgroup['policies'] = policies
        res_dict = self.controller.create(self.req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policies'], policies)

    def test_create_server_group(self):
        policies = ['affinity', 'anti-affinity']
        for policy in policies:
            self._create_server_group_normal([policy])

    def test_create_server_group_rbac_default(self):
        sgroup = server_group_template()
        sgroup['policies'] = ['affinity']

        # test as admin
        self.controller.create(self.admin_req, body={'server_group': sgroup})

        # test as non-admin
        self.controller.create(self.req, body={'server_group': sgroup})

    def test_create_server_group_rbac_admin_only(self):
        sgroup = server_group_template()
        sgroup['policies'] = ['affinity']

        # override policy to restrict to admin
        rule_name = sg_policies.POLICY_ROOT % 'create'
        rules = {rule_name: 'is_admin:True'}
        self.policy.set_rules(rules, overwrite=False)

        # check for success as admin
        self.controller.create(self.admin_req, body={'server_group': sgroup})

        # check for failure as non-admin
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.create, self.req,
                                body={'server_group': sgroup})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def _create_instance(self, ctx, cell):
        with context.target_cell(ctx, cell) as cctx:
            instance = objects.Instance(context=cctx,
                                        image_ref=uuidsentinel.fake_image_ref,
                                        node='node1', reservation_id='a',
                                        host='host1', project_id='fake',
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

    def _create_instance_group(self, context, members):
        ig = objects.InstanceGroup(context=context, name='fake_name',
                  user_id='fake_user', project_id='fake',
                  members=members)
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
        self._test_list_server_group(api_version=api_version, limited=False)

    def _test_list_server_group_offset_and_limit(self, api_version='2.1'):
        self._test_list_server_group(api_version=api_version, limited=True)

    @mock.patch.object(nova.db, 'instance_group_get_all_by_project_id')
    @mock.patch.object(nova.db, 'instance_group_get_all')
    def _test_list_server_group(self, mock_get_all, mock_get_by_project,
                                api_version='2.1', limited=False):
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
        tenant_groups = [sg2]
        all_groups = [sg1, sg2]

        if limited:
            all = {'server_groups': [sg2]}
            tenant_specific = {'server_groups': []}
        else:
            all = {'server_groups': all_groups}
            tenant_specific = {'server_groups': tenant_groups}

        def return_all_server_groups():
            return [server_group_db(sg) for sg in all_groups]

        mock_get_all.return_value = return_all_server_groups()

        def return_tenant_server_groups():
            return [server_group_db(sg) for sg in tenant_groups]

        mock_get_by_project.return_value = return_tenant_server_groups()

        path = '/os-server-groups?all_projects=True'
        if limited:
            path += '&offset=1&limit=1'
        req = fakes.HTTPRequest.blank(path, version=api_version)
        admin_req = fakes.HTTPRequest.blank(path, use_admin_context=True,
                                            version=api_version)

        # test as admin
        res_dict = self.controller.index(admin_req)
        self.assertEqual(all, res_dict)

        # test as non-admin
        res_dict = self.controller.index(req)
        self.assertEqual(tenant_specific, res_dict)

    @mock.patch.object(nova.db, 'instance_group_get_all_by_project_id')
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
            return [server_group_db(sg) for sg in groups]

        return_get_by_project = return_server_groups()
        mock_get_by_project.return_value = return_get_by_project
        path = '/os-server-groups'
        req = fakes.HTTPRequest.blank(path, version=api_version)
        res_dict = self.controller.index(req)
        self.assertEqual(expected, res_dict)

    def test_display_members(self):
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        res_dict = self.controller.show(self.req, ig_uuid)
        result_members = res_dict['server_group']['members']
        self.assertEqual(3, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_display_members_with_nonexistent_group(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, uuidsentinel.group)

    def test_display_active_members_only(self):
        ctx = context.RequestContext('fake_user', 'fake')
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
        res_dict = self.controller.show(self.req, ig_uuid)
        result_members = res_dict['server_group']['members']
        # check that only the active instance is displayed
        self.assertEqual(2, len(result_members))
        self.assertIn(instances[0].uuid, result_members)

    def test_display_members_rbac_default(self):
        ctx = context.RequestContext('fake_user', 'fake')
        ig_uuid = self._create_groups_and_instances(ctx)[0]

        # test as admin
        self.controller.show(self.admin_req, ig_uuid)

        # test as non-admin, same project
        self.controller.show(self.req, ig_uuid)

        # test as non-admin, different project
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.foo_req, ig_uuid)

    def test_display_members_rbac_admin_only(self):
        ctx = context.RequestContext('fake_user', 'fake')
        ig_uuid = self._create_groups_and_instances(ctx)[0]

        # override policy to restrict to admin
        rule_name = sg_policies.POLICY_ROOT % 'show'
        rules = {rule_name: 'is_admin:True'}
        self.policy.set_rules(rules, overwrite=False)

        # check for success as admin
        self.controller.show(self.admin_req, ig_uuid)

        # check for failure as non-admin
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.show, self.req, ig_uuid)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_create_server_group_with_non_alphanumeric_in_name(self):
        # The fix for bug #1434335 expanded the allowable character set
        # for server group names to include non-alphanumeric characters
        # if they are printable.

        sgroup = server_group_template(name='good* $%name',
                                       policies=['affinity'])
        res_dict = self.controller.create(self.req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'good* $%name')

    def test_create_server_group_with_illegal_name(self):
        # blank name
        sgroup = server_group_template(name='', policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with length 256
        sgroup = server_group_template(name='1234567890' * 26,
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # non-string name
        sgroup = server_group_template(name=12, policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with leading spaces
        sgroup = server_group_template(name='  leading spaces',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with trailing spaces
        sgroup = server_group_template(name='trailing space ',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with all spaces
        sgroup = server_group_template(name='    ',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with unprintable character
        sgroup = server_group_template(name='bad\x00name',
                                       policies=['test_policy'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # name with out of range char U0001F4A9
        sgroup = server_group_template(name=u"\U0001F4A9",
                                       policies=['affinity'])
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

    def test_create_server_group_with_illegal_policies(self):
        # blank policy
        sgroup = server_group_template(name='fake-name', policies='')
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # policy as integer
        sgroup = server_group_template(name='fake-name', policies=7)
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # policy as string
        sgroup = server_group_template(name='fake-name', policies='invalid')
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

        # policy as None
        sgroup = server_group_template(name='fake-name', policies=None)
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

    def test_create_server_group_conflicting_policies(self):
        sgroup = server_group_template()
        policies = ['anti-affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

    def test_create_server_group_with_duplicate_policies(self):
        sgroup = server_group_template()
        policies = ['affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

    def test_create_server_group_not_supported(self):
        sgroup = server_group_template()
        policies = ['storage-affinity', 'anti-affinity', 'rack-affinity']
        sgroup['policies'] = policies
        self.assertRaises(self.validation_error, self.controller.create,
                          self.req, body={'server_group': sgroup})

    def test_create_server_group_with_no_body(self):
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=None)

    def test_create_server_group_with_no_server_group(self):
        body = {'no-instanceGroup': None}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_list_server_group_by_tenant(self):
        self._test_list_server_group_by_tenant(api_version='2.1')

    def test_list_server_group_all(self):
        self._test_list_server_group_all(api_version='2.1')

    def test_list_server_group_offset_and_limit(self):
        self._test_list_server_group_offset_and_limit(api_version='2.1')

    def test_list_server_groups_rbac_default(self):
        # test as admin
        self.controller.index(self.admin_req)

        # test as non-admin
        self.controller.index(self.req)

    def test_list_server_groups_rbac_admin_only(self):
        # override policy to restrict to admin
        rule_name = sg_policies.POLICY_ROOT % 'index'
        rules = {rule_name: 'is_admin:True'}
        self.policy.set_rules(rules, overwrite=False)

        # check for success as admin
        self.controller.index(self.admin_req)

        # check for failure as non-admin
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_server_group_by_id(self):
        sg = server_group_template(id=uuidsentinel.sg1_id)

        self.called = False

        def server_group_delete(context, id):
            self.called = True

        def return_server_group(context, group_id):
            self.assertEqual(sg['id'], group_id)
            return server_group_db(sg)

        self.stub_out('nova.db.instance_group_delete',
                      server_group_delete)
        self.stub_out('nova.db.instance_group_get',
                      return_server_group)

        resp = self.controller.delete(self.req, uuidsentinel.sg1_id)
        self.assertTrue(self.called)

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller, sg_v21.ServerGroupController):
            status_int = self.controller.delete.wsgi_code
        else:
            status_int = resp.status_int
        self.assertEqual(204, status_int)

    def test_delete_non_existing_server_group(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, 'invalid')

    def test_delete_server_group_rbac_default(self):
        ctx = context.RequestContext('fake_user', 'fake')

        # test as admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        self.controller.delete(self.admin_req, ig_uuid)

        # test as non-admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        self.controller.delete(self.req, ig_uuid)

    def test_delete_server_group_rbac_admin_only(self):
        ctx = context.RequestContext('fake_user', 'fake')

        # override policy to restrict to admin
        rule_name = sg_policies.POLICY_ROOT % 'delete'
        rules = {rule_name: 'is_admin:True'}
        self.policy.set_rules(rules, overwrite=False)

        # check for success as admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        self.controller.delete(self.admin_req, ig_uuid)

        # check for failure as non-admin
        ig_uuid = self._create_groups_and_instances(ctx)[0]
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.delete, self.req, ig_uuid)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


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

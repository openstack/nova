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

import webob

from nova.api.openstack.compute.contrib import server_groups
from nova.api.openstack.compute.plugins.v3 import server_groups as sg_v3
from nova.api.openstack import extensions
from nova import context
import nova.db
from nova import exception
from nova import objects
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit.api.openstack import fakes

FAKE_UUID1 = 'a47ae74e-ab08-447f-8eee-ffd43fc46c16'
FAKE_UUID2 = 'c6e6430a-6563-4efa-9542-5e93c9e97d18'
FAKE_UUID3 = 'b8713410-9ba3-e913-901b-13410ca90121'


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
        attrs['user_id'] = 'user_id'
    if 'project_id' not in attrs:
        attrs['project_id'] = 'project_id'
    attrs['id'] = 7

    return AttrDict(attrs)


class ServerGroupTestV21(test.TestCase):

    def setUp(self):
        super(ServerGroupTestV21, self).setUp()
        self._setup_controller()
        self.req = fakes.HTTPRequest.blank('')

    def _setup_controller(self):
        self.controller = sg_v3.ServerGroupController()

    def test_create_server_group_with_no_policies(self):
        sgroup = server_group_template()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_normal(self):
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        res_dict = self.controller.create(self.req, {'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policies'], policies)

    def _create_instance(self, context):
        instance = objects.Instance(context=context, image_ref=1, node='node1',
                reservation_id='a', host='host1', project_id='fake',
                vm_state='fake', system_metadata={'key': 'value'})
        instance.create()
        return instance

    def _create_instance_group(self, context, members):
        ig = objects.InstanceGroup(context=context, name='fake_name',
                  user_id='fake_user', project_id='fake',
                  members=members)
        ig.create()
        return ig.uuid

    def _create_groups_and_instances(self, ctx):
        instances = [self._create_instance(ctx), self._create_instance(ctx)]
        members = [instance.uuid for instance in instances]
        ig_uuid = self._create_instance_group(ctx, members)
        return (ig_uuid, instances, members)

    def test_display_members(self):
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        res_dict = self.controller.show(self.req, ig_uuid)
        result_members = res_dict['server_group']['members']
        self.assertEqual(2, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_display_active_members_only(self):
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)

        # delete an instance
        instances[1].destroy()
        # check that the instance does not exist
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid,
                          ctx, instances[1].uuid)
        res_dict = self.controller.show(self.req, ig_uuid)
        result_members = res_dict['server_group']['members']
        # check that only the active instance is displayed
        self.assertEqual(1, len(result_members))
        self.assertIn(instances[0].uuid, result_members)

    def test_create_server_group_with_illegal_name(self):
        # blank name
        sgroup = server_group_template(name='', policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # name with length 256
        sgroup = server_group_template(name='1234567890' * 26,
                                       policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # non-string name
        sgroup = server_group_template(name=12, policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # name with leading spaces
        sgroup = server_group_template(name='  leading spaces',
                                       policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # name with trailing spaces
        sgroup = server_group_template(name='trailing space ',
                                       policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # name with all spaces
        sgroup = server_group_template(name='    ',
                                       policies=['test_policy'])
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_with_illegal_policies(self):
        # blank policy
        sgroup = server_group_template(name='fake-name', policies='')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # policy as integer
        sgroup = server_group_template(name='fake-name', policies=7)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # policy as string
        sgroup = server_group_template(name='fake-name', policies='invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

        # policy as None
        sgroup = server_group_template(name='fake-name', policies=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_conflicting_policies(self):
        sgroup = server_group_template()
        policies = ['anti-affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_with_duplicate_policies(self):
        sgroup = server_group_template()
        policies = ['affinity', 'affinity']
        sgroup['policies'] = policies
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_not_supported(self):
        sgroup = server_group_template()
        policies = ['storage-affinity', 'anti-affinity', 'rack-affinity']
        sgroup['policies'] = policies
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, {'server_group': sgroup})

    def test_create_server_group_with_no_body(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, None)

    def test_create_server_group_with_no_server_group(self):
        body = {'no-instanceGroup': None}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body)

    def test_list_server_group_by_tenant(self):
        groups = []
        policies = ['anti-affinity']
        members = []
        metadata = {}  # always empty
        names = ['default-x', 'test']
        sg1 = server_group_resp_template(id=str(1345),
                                           name=names[0],
                                           policies=policies,
                                           members=members,
                                           metadata=metadata)
        sg2 = server_group_resp_template(id=str(891),
                                           name=names[1],
                                           policies=policies,
                                           members=members,
                                           metadata=metadata)
        groups = [sg1, sg2]
        expected = {'server_groups': groups}

        def return_server_groups(context, project_id):
            return [server_group_db(sg) for sg in groups]

        self.stubs.Set(nova.db, 'instance_group_get_all_by_project_id',
                       return_server_groups)

        res_dict = self.controller.index(self.req)
        self.assertEqual(res_dict, expected)

    def test_list_server_group_all(self):
        all_groups = []
        tenant_groups = []
        policies = ['anti-affinity']
        members = []
        metadata = {}  # always empty
        names = ['default-x', 'test']
        sg1 = server_group_resp_template(id=str(1345),
                                           name=names[0],
                                           policies=[],
                                           members=members,
                                           metadata=metadata)
        sg2 = server_group_resp_template(id=str(891),
                                           name=names[1],
                                           policies=policies,
                                           members=members,
                                           metadata={})
        tenant_groups = [sg2]
        all_groups = [sg1, sg2]

        all = {'server_groups': all_groups}
        tenant_specific = {'server_groups': tenant_groups}

        def return_all_server_groups(context):
            return [server_group_db(sg) for sg in all_groups]

        self.stubs.Set(nova.db, 'instance_group_get_all',
                       return_all_server_groups)

        def return_tenant_server_groups(context, project_id):
            return [server_group_db(sg) for sg in tenant_groups]

        self.stubs.Set(nova.db, 'instance_group_get_all_by_project_id',
                       return_tenant_server_groups)

        path = '/os-server-groups?all_projects=True'

        req = fakes.HTTPRequest.blank(path, use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, all)
        req = fakes.HTTPRequest.blank(path)
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, tenant_specific)

    def test_delete_server_group_by_id(self):
        sg = server_group_template(id='123')

        self.called = False

        def server_group_delete(context, id):
            self.called = True

        def return_server_group(context, group_id):
            self.assertEqual(sg['id'], group_id)
            return server_group_db(sg)

        self.stubs.Set(nova.db, 'instance_group_delete',
                       server_group_delete)
        self.stubs.Set(nova.db, 'instance_group_get',
                       return_server_group)

        resp = self.controller.delete(self.req, '123')
        self.assertTrue(self.called)

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller, sg_v3.ServerGroupController):
            status_int = self.controller.delete.wsgi_code
        else:
            status_int = resp.status_int
        self.assertEqual(204, status_int)

    def test_delete_non_existing_server_group(self):
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          self.req, 'invalid')


class ServerGroupTestV2(ServerGroupTestV21):

    def _setup_controller(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {}
        self.controller = server_groups.ServerGroupController(ext_mgr)

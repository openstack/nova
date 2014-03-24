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

from lxml import etree
import webob

from nova.api.openstack.compute.contrib import server_groups
from nova.api.openstack import wsgi
from nova import context
import nova.db
from nova import exception
from nova.objects import instance as instance_obj
from nova.objects import instance_group as instance_group_obj
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import utils

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
    sgroup.setdefault('metadata', {})
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
    if 'metadata' in attrs:
        attrs['metadetails'] = attrs.pop('metadata')
    else:
        attrs['metadetails'] = {}
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


class ServerGroupTest(test.TestCase):
    def setUp(self):
        super(ServerGroupTest, self).setUp()
        self.controller = server_groups.ServerGroupController()
        self.app = fakes.wsgi_app(init_only=('os-server-groups',))

    def test_create_server_group_with_no_policies(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        sgroup = server_group_template()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

    def test_create_server_group_normal(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        res_dict = self.controller.create(req, {'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policies'], policies)

    def _create_instance(self, context):
        instance = instance_obj.Instance(image_ref=1, node='node1',
                reservation_id='a', host='host1', project_id='fake',
                vm_state='fake', system_metadata={'key': 'value'})
        instance.create(context)
        return instance

    def _create_instance_group(self, context, members):
        ig = instance_group_obj.InstanceGroup(name='fake_name',
                  user_id='fake_user', project_id='fake',
                  members=members)
        ig.create(context)
        return ig.uuid

    def _create_groups_and_instances(self, ctx):
        instances = [self._create_instance(ctx), self._create_instance(ctx)]
        members = [instance.uuid for instance in instances]
        ig_uuid = self._create_instance_group(ctx, members)
        return (ig_uuid, instances, members)

    def test_display_members(self):
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        res_dict = self.controller.show(req, ig_uuid)
        result_members = res_dict['server_group']['members']
        self.assertEqual(2, len(result_members))
        for member in members:
            self.assertIn(member, result_members)

    def test_display_active_members_only(self):
        ctx = context.RequestContext('fake_user', 'fake')
        (ig_uuid, instances, members) = self._create_groups_and_instances(ctx)
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')

        # delete an instance
        instances[1].destroy(ctx)
        # check that the instance does not exist
        self.assertRaises(exception.InstanceNotFound,
                          instance_obj.Instance.get_by_uuid,
                          ctx, instances[1].uuid)
        res_dict = self.controller.show(req, ig_uuid)
        result_members = res_dict['server_group']['members']
        # check that only the active instance is displayed
        self.assertEqual(1, len(result_members))
        self.assertIn(instances[0].uuid, result_members)

    def test_create_server_group_with_illegal_name(self):
        # blank name
        sgroup = server_group_template(name='', policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # name with length 256
        sgroup = server_group_template(name='1234567890' * 26,
                                       policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # non-string name
        sgroup = server_group_template(name=12, policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # name with leading spaces
        sgroup = server_group_template(name='  leading spaces',
                                       policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # name with trailing spaces
        sgroup = server_group_template(name='trailing space ',
                                       policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # name with all spaces
        sgroup = server_group_template(name='    ',
                                       policies=['test_policy'])
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

    def test_create_server_group_with_illegal_policies(self):
        # blank policy
        sgroup = server_group_template(name='fake-name', policies='')
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # policy as integer
        sgroup = server_group_template(name='fake-name', policies=7)
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # policy as string
        sgroup = server_group_template(name='fake-name', policies='invalid')
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

        # policy as None
        sgroup = server_group_template(name='fake-name', policies=None)
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

    def test_create_server_group_conflicting_policies(self):
        sgroup = server_group_template()
        policies = ['anti-affinity', 'affinity']
        sgroup['policies'] = policies
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

    def test_create_server_group_not_supported(self):
        sgroup = server_group_template()
        policies = ['storage-affinity', 'anti-affinity', 'rack-affinity']
        sgroup['policies'] = policies
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'server_group': sgroup})

    def test_create_server_group_with_no_body(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, None)

    def test_create_server_group_with_no_server_group(self):
        body = {'no-instanceGroup': None}
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_list_server_group_by_tenant(self):
        groups = []
        policies = ['anti-affinity']
        members = []
        metadata = {'key1': 'value1'}
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

        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups')
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, expected)

    def test_list_server_group_all(self):
        all_groups = []
        tenant_groups = []
        policies = ['anti-affinity']
        members = []
        metadata = {'key1': 'value1'}
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

        path = '/v2/fake/os-server-groups?all_projects=True'

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

        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups/123')
        resp = self.controller.delete(req, '123')
        self.assertTrue(self.called)
        self.assertEqual(resp.status_int, 204)

    def test_delete_non_existing_server_group(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-server-groups/invalid')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, 'invalid')


class TestServerGroupXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerGroupXMLDeserializer, self).setUp()
        self.deserializer = server_groups.ServerGroupXMLDeserializer()

    def test_create_request(self):
        serial_request = """
<server_group name="test">
</server_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server_group": {
                "name": "test",
                "policies": []
            },
        }
        self.assertEqual(request['body'], expected)

    def test_update_request(self):
        serial_request = """
<server_group name="test">
<policies>
<policy>policy-1</policy>
<policy>policy-2</policy>
</policies>
</server_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server_group": {
                "name": 'test',
                "policies": ['policy-1', 'policy-2']
            },
        }
        self.assertEqual(request['body'], expected)

    def test_create_request_no_name(self):
        serial_request = """
<server_group>
</server_group>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server_group": {
            "policies": []
            },
        }
        self.assertEqual(request['body'], expected)

    def test_corrupt_xml(self):
        """Should throw a 400 error on corrupt xml."""
        self.assertRaises(
                exception.MalformedRequestBody,
                self.deserializer.deserialize,
                utils.killer_xml_body())


class TestServerGroupXMLSerializer(test.TestCase):
    def setUp(self):
        super(TestServerGroupXMLSerializer, self).setUp()
        self.namespace = wsgi.XMLNS_V11
        self.index_serializer = server_groups.ServerGroupsTemplate()
        self.default_serializer = server_groups.ServerGroupTemplate()

    def _tag(self, elem):
        tagname = elem.tag
        self.assertEqual(tagname[0], '{')
        tmp = tagname.partition('}')
        namespace = tmp[0][1:]
        self.assertEqual(namespace, self.namespace)
        return tmp[2]

    def _verify_server_group(self, raw_group, tree):
        policies = raw_group['policies']
        members = raw_group['members']
        metadata = raw_group['metadata']
        self.assertEqual('server_group', self._tag(tree))
        self.assertEqual(raw_group['id'], tree.get('id'))
        self.assertEqual(raw_group['name'], tree.get('name'))
        self.assertEqual(3, len(tree))
        for child in tree:
            child_tag = self._tag(child)
            if child_tag == 'policies':
                self.assertEqual(len(policies), len(child))
                for idx, gr_child in enumerate(child):
                    self.assertEqual(self._tag(gr_child), 'policy')
                    self.assertEqual(policies[idx],
                                     gr_child.text)
            elif child_tag == 'members':
                self.assertEqual(len(members), len(child))
                for idx, gr_child in enumerate(child):
                    self.assertEqual(self._tag(gr_child), 'member')
                    self.assertEqual(members[idx],
                                     gr_child.text)
            elif child_tag == 'metadata':
                self.assertEqual(len(metadata), len(child))
                metas = {}
                for idx, gr_child in enumerate(child):
                    self.assertEqual(self._tag(gr_child), 'meta')
                    key = gr_child.get('key')
                    self.assertTrue(key in ['key1', 'key2'])
                    metas[key] = gr_child.text
                self.assertEqual(len(metas), len(metadata))
                for k in metadata:
                    self.assertEqual(metadata[k], metas[k])

    def _verify_server_group_brief(self, raw_group, tree):
        self.assertEqual('server_group', self._tag(tree))
        self.assertEqual(raw_group['id'], tree.get('id'))
        self.assertEqual(raw_group['name'], tree.get('name'))

    def test_group_serializer(self):
        policies = ["policy-1", "policy-2"]
        members = ["1", "2"]
        metadata = dict(key1="value1", key2="value2")
        raw_group = dict(
            id='890',
            name='name',
            policies=policies,
            members=members,
            metadata=metadata)
        sg_group = dict(server_group=raw_group)
        text = self.default_serializer.serialize(sg_group)

        tree = etree.fromstring(text)

        self._verify_server_group(raw_group, tree)

    def test_groups_serializer(self):
        policies = ["policy-1", "policy-2",
                    "policy-3"]
        members = ["1", "2", "3"]
        metadata = dict(key1="value1", key2="value2")
        groups = [dict(
                 id='890',
                 name='test',
                 policies=policies[0:2],
                 members=members[0:2],
                 metadata=metadata),
                 dict(
                 id='123',
                 name='default',
                 policies=policies[2:],
                 members=members[2:],
                 metadata=metadata)]
        sg_groups = dict(server_groups=groups)
        text = self.index_serializer.serialize(sg_groups)

        tree = etree.fromstring(text)

        self.assertEqual('server_groups', self._tag(tree))
        self.assertEqual(len(groups), len(tree))
        for idx, child in enumerate(tree):
            self._verify_server_group_brief(groups[idx], child)

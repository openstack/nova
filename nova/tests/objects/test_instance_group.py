# Copyright (c) 2013 OpenStack Foundation
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

from nova import context
from nova import db
from nova import exception
from nova.objects import instance_group
from nova import test
from nova.tests.objects import test_objects


class _TestInstanceGroupObjects(test.TestCase):

    def setUp(self):
        super(_TestInstanceGroupObjects, self).setUp()
        self.user_id = 'fake_user'
        self.project_id = 'fake_project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def _get_default_values(self):
        return {'name': 'fake_name',
                'user_id': self.user_id,
                'project_id': self.project_id}

    def _create_instance_group(self, context, values, policies=None,
                               metadata=None, members=None):
        return db.instance_group_create(context, values, policies=policies,
                                        metadata=metadata, members=members)

    def test_get_by_uuid(self):
        values = self._get_default_values()
        metadata = {'key11': 'value1',
                    'key12': 'value2'}
        policies = ['policy1', 'policy2']
        members = ['instance_id1', 'instance_id2']
        db_result = self._create_instance_group(self.context, values,
                                                metadata=metadata,
                                                policies=policies,
                                                members=members)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        self.assertEqual(obj_result.metadetails, metadata)
        self.assertEqual(obj_result.members, members)
        self.assertEqual(obj_result.policies, policies)

    def test_refresh(self):
        values = self._get_default_values()
        db_result = self._create_instance_group(self.context, values)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        self.assertEqual(obj_result.name, 'fake_name')
        values = {'name': 'new_name', 'user_id': 'new_user',
                  'project_id': 'new_project'}
        db.instance_group_update(self.context, db_result['uuid'],
                                 values)
        obj_result.refresh()
        self.assertEqual(obj_result.name, 'new_name')
        self.assertEqual(set([]), obj_result.obj_what_changed())

    def test_save_simple(self):
        values = self._get_default_values()
        db_result = self._create_instance_group(self.context, values)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        self.assertEqual(obj_result.name, 'fake_name')
        obj_result.name = 'new_name'
        obj_result.save()
        result = db.instance_group_get(self.context, db_result['uuid'])
        self.assertEqual(result['name'], 'new_name')

    def test_save_policies(self):
        values = self._get_default_values()
        db_result = self._create_instance_group(self.context, values)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        policies = ['policy1', 'policy2']
        obj_result.policies = policies
        obj_result.save()
        result = db.instance_group_get(self.context, db_result['uuid'])
        self.assertEqual(result['policies'], policies)

    def test_save_members(self):
        values = self._get_default_values()
        db_result = self._create_instance_group(self.context, values)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        members = ['instance1', 'instance2']
        obj_result.members = members
        obj_result.save()
        result = db.instance_group_get(self.context, db_result['uuid'])
        self.assertEqual(result['members'], members)

    def test_save_metadata(self):
        values = self._get_default_values()
        db_result = self._create_instance_group(self.context, values)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        metadata = {'foo': 'bar'}
        obj_result.metadetails = metadata
        obj_result.save()
        metadata1 = db.instance_group_metadata_get(self.context,
                                                   db_result['uuid'])
        for key, value in metadata.iteritems():
            self.assertEqual(value, metadata[key])

    def test_create(self):
        group1 = instance_group.InstanceGroup()
        group1.uuid = 'fake-uuid'
        group1.name = 'fake-name'
        group1.create(self.context)
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        self.assertEqual(group1.uuid, group2.uuid)
        self.assertEqual(group1.name, group2.name)
        result = db.instance_group_get(self.context, group1.uuid)
        self.assertEqual(group1.id, result.id)
        self.assertEqual(group1.uuid, result.uuid)
        self.assertEqual(group1.name, result.name)

    def test_create_with_policies(self):
        group1 = instance_group.InstanceGroup()
        group1.policies = ['policy1', 'policy2']
        group1.create(self.context)
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        self.assertEqual(group1.policies, group2.policies)

    def test_create_with_members(self):
        group1 = instance_group.InstanceGroup()
        group1.members = ['instance1', 'instance2']
        group1.create(self.context)
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        self.assertEqual(group1.members, group2.members)

    def test_create_with_metadata(self):
        group1 = instance_group.InstanceGroup()
        metadata = {'foo': 'bar'}
        group1.metadetails = metadata
        group1.create(self.context)
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        for key, value in metadata.iteritems():
            self.assertEqual(value, group2.metadetails[key])

    def test_recreate_fails(self):
        group = instance_group.InstanceGroup()
        group.create(self.context)
        self.assertRaises(exception.ObjectActionError, group.create,
                          self.context)

    def test_destroy(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        group = instance_group.InstanceGroup()
        group.id = result.id
        group.uuid = result.uuid
        group.destroy(self.context)
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_get, self.context, result['uuid'])

    def _populate_instances(self):
        instances = [('f1', 'p1'), ('f2', 'p1'),
                     ('f3', 'p2'), ('f4', 'p2')]
        for instance in instances:
            values = self._get_default_values()
            values['uuid'] = instance[0]
            values['project_id'] = instance[1]
            self._create_instance_group(self.context, values)

    def test_list_all(self):
        self._populate_instances()
        inst_list = instance_group.InstanceGroupList.get_all(self.context)
        groups = db.instance_group_get_all(self.context)
        self.assertEqual(len(groups), len(inst_list.objects))
        self.assertEqual(len(groups), 4)
        for i in range(0, len(groups)):
            self.assertIsInstance(inst_list.objects[i],
                                  instance_group.InstanceGroup)
            self.assertEqual(inst_list.objects[i].uuid, groups[i]['uuid'])

    def test_list_by_project_id(self):
        self._populate_instances()
        project_ids = ['p1', 'p2']
        for id in project_ids:
            il = instance_group.InstanceGroupList.get_by_project_id(
                    self.context, id)
            groups = db.instance_group_get_all_by_project_id(self.context, id)
            self.assertEqual(len(groups), len(il.objects))
            self.assertEqual(len(groups), 2)
            for i in range(0, len(groups)):
                self.assertIsInstance(il.objects[i],
                                      instance_group.InstanceGroup)
                self.assertEqual(il.objects[i].uuid, groups[i]['uuid'])
                self.assertEqual(il.objects[i].project_id, id)

    def test_add_members(self):
        instance_ids = ['fakeid1', 'fakeid2']
        values = self._get_default_values()
        group = self._create_instance_group(self.context, values)
        members = instance_group.InstanceGroup.add_members(self.context,
                group.uuid, instance_ids)
        group = instance_group.InstanceGroup.get_by_uuid(self.context,
                group.uuid)
        for instance in instance_ids:
            self.assertIn(instance, members)
            self.assertIn(instance, group.members)


class TestInstanceGroupObject(test_objects._LocalTest,
                              _TestInstanceGroupObjects):
    pass


class TestRemoteInstanceGroupObject(test_objects._RemoteTest,
                                    _TestInstanceGroupObjects):
    pass

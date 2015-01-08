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

import uuid

from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova.objects import instance_group
from nova.tests.unit import fake_notifier
from nova.tests.unit.objects import test_objects
from nova.tests.unit import utils as tests_utils


class _TestInstanceGroupObjects(object):

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
                               members=None):
        return db.instance_group_create(context, values, policies=policies,
                                        members=members)

    def test_get_by_uuid(self):
        values = self._get_default_values()
        policies = ['policy1', 'policy2']
        members = ['instance_id1', 'instance_id2']
        db_result = self._create_instance_group(self.context, values,
                                                policies=policies,
                                                members=members)
        obj_result = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                              db_result.uuid)
        self.assertEqual(obj_result.members, members)
        self.assertEqual(obj_result.policies, policies)

    def test_get_by_instance_uuid(self):
        values = self._get_default_values()
        policies = ['policy1', 'policy2']
        members = ['instance_id1', 'instance_id2']
        db_result = self._create_instance_group(self.context, values,
                                                policies=policies,
                                                members=members)
        obj_result = instance_group.InstanceGroup.get_by_instance_uuid(
                self.context, 'instance_id1')
        self.assertEqual(obj_result.uuid, db_result.uuid)

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
        fake_notifier.NOTIFICATIONS = []
        obj_result.save()
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('servergroup.update', msg.event_type)
        self.assertEqual(members, msg.payload['members'])
        result = db.instance_group_get(self.context, db_result['uuid'])
        self.assertEqual(result['members'], members)

    def test_create(self):
        group1 = instance_group.InstanceGroup(context=self.context)
        group1.uuid = 'fake-uuid'
        group1.name = 'fake-name'
        fake_notifier.NOTIFICATIONS = []
        group1.create()
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(group1.name, msg.payload['name'])
        self.assertEqual(group1.uuid, msg.payload['server_group_id'])
        self.assertEqual('servergroup.create', msg.event_type)
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
        group1 = instance_group.InstanceGroup(context=self.context)
        group1.policies = ['policy1', 'policy2']
        group1.create()
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        self.assertEqual(group1.policies, group2.policies)

    def test_create_with_members(self):
        group1 = instance_group.InstanceGroup(context=self.context)
        group1.members = ['instance1', 'instance2']
        group1.create()
        group2 = instance_group.InstanceGroup.get_by_uuid(self.context,
                                                          group1.uuid)
        self.assertEqual(group1.id, group2.id)
        self.assertEqual(group1.members, group2.members)

    def test_recreate_fails(self):
        group = instance_group.InstanceGroup(context=self.context)
        group.create()
        self.assertRaises(exception.ObjectActionError, group.create,
                          self.context)

    def test_destroy(self):
        values = self._get_default_values()
        result = self._create_instance_group(self.context, values)
        group = instance_group.InstanceGroup(context=self.context)
        group.id = result.id
        group.uuid = result.uuid
        fake_notifier.NOTIFICATIONS = []
        group.destroy()
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('servergroup.delete', msg.event_type)
        self.assertEqual(group.uuid, msg.payload['server_group_id'])
        self.assertRaises(exception.InstanceGroupNotFound,
                          db.instance_group_get, self.context, result['uuid'])

    def _populate_instances(self):
        instances = [(str(uuid.uuid4()), 'f1', 'p1'),
                     (str(uuid.uuid4()), 'f2', 'p1'),
                     (str(uuid.uuid4()), 'f3', 'p2'),
                     (str(uuid.uuid4()), 'f4', 'p2')]
        for instance in instances:
            values = self._get_default_values()
            values['uuid'] = instance[0]
            values['name'] = instance[1]
            values['project_id'] = instance[2]
            self._create_instance_group(self.context, values)
        return instances

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
                self.assertEqual(il.objects[i].name, groups[i]['name'])
                self.assertEqual(il.objects[i].project_id, id)

    def test_get_by_name(self):
        self._populate_instances()
        ctxt = context.RequestContext('fake_user', 'p1')
        ig = instance_group.InstanceGroup.get_by_name(ctxt, 'f1')
        self.assertEqual('f1', ig.name)

    def test_get_by_hint(self):
        instances = self._populate_instances()
        for instance in instances:
            ctxt = context.RequestContext('fake_user', instance[2])
            ig = instance_group.InstanceGroup.get_by_hint(ctxt, instance[1])
            self.assertEqual(instance[1], ig.name)
            ig = instance_group.InstanceGroup.get_by_hint(ctxt, instance[0])
            self.assertEqual(instance[0], ig.uuid)

    def test_add_members(self):
        instance_ids = ['fakeid1', 'fakeid2']
        values = self._get_default_values()
        group = self._create_instance_group(self.context, values)
        fake_notifier.NOTIFICATIONS = []
        members = instance_group.InstanceGroup.add_members(self.context,
                group.uuid, instance_ids)
        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('servergroup.addmember', msg.event_type)
        self.assertEqual(group.uuid, msg.payload['server_group_id'])
        self.assertEqual(instance_ids, msg.payload['instance_uuids'])
        group = instance_group.InstanceGroup.get_by_uuid(self.context,
                group.uuid)
        for instance in instance_ids:
            self.assertIn(instance, members)
            self.assertIn(instance, group.members)

    def test_get_hosts(self):
        instance1 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance1.host = 'hostA'
        instance1.save()
        instance2 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance2.host = 'hostB'
        instance2.save()
        instance3 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance3.host = 'hostB'
        instance3.save()

        instance_ids = [instance1.uuid, instance2.uuid, instance3.uuid]
        values = self._get_default_values()
        group = self._create_instance_group(self.context, values)
        instance_group.InstanceGroup.add_members(self.context, group.uuid,
                instance_ids)

        group = instance_group.InstanceGroup.get_by_uuid(self.context,
                group.uuid)
        hosts = group.get_hosts(self.context)
        self.assertEqual(2, len(hosts))
        self.assertIn('hostA', hosts)
        self.assertIn('hostB', hosts)
        hosts = group.get_hosts(self.context, exclude=[instance1.uuid])
        self.assertEqual(1, len(hosts))
        self.assertIn('hostB', hosts)

    def test_get_hosts_with_some_none(self):
        instance1 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance1.host = None
        instance1.save()
        instance2 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance2.host = 'hostB'
        instance2.save()

        instance_ids = [instance1.uuid, instance2.uuid]
        values = self._get_default_values()
        group = self._create_instance_group(self.context, values)
        instance_group.InstanceGroup.add_members(self.context, group.uuid,
                instance_ids)

        group = instance_group.InstanceGroup.get_by_uuid(self.context,
                group.uuid)
        hosts = group.get_hosts(self.context)
        self.assertEqual(1, len(hosts))
        self.assertIn('hostB', hosts)

    def test_obj_make_compatible(self):
        group = instance_group.InstanceGroup(context=self.context,
                                             uuid='fake-uuid',
                                             name='fake-name')
        group.create()
        group_primitive = group.obj_to_primitive()
        group.obj_make_compatible(group_primitive, '1.6')
        self.assertEqual({}, group_primitive['metadetails'])

    def test_count_members_by_user(self):
        instance1 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance1.user_id = 'user1'
        instance1.save()
        instance2 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance2.user_id = 'user2'
        instance2.save()
        instance3 = tests_utils.get_test_instance(self.context,
                flavor=flavors.get_default_flavor(), obj=True)
        instance3.user_id = 'user2'
        instance3.save()

        instance_ids = [instance1.uuid, instance2.uuid, instance3.uuid]
        values = self._get_default_values()
        group = self._create_instance_group(self.context, values)
        instance_group.InstanceGroup.add_members(self.context, group.uuid,
                instance_ids)

        group = instance_group.InstanceGroup.get_by_uuid(self.context,
                group.uuid)
        count_user1 = group.count_members_by_user(self.context, 'user1')
        count_user2 = group.count_members_by_user(self.context, 'user2')
        count_user3 = group.count_members_by_user(self.context, 'user3')
        self.assertEqual(1, count_user1)
        self.assertEqual(2, count_user2)
        self.assertEqual(0, count_user3)


class TestInstanceGroupObject(test_objects._LocalTest,
                              _TestInstanceGroupObjects):
    pass


class TestRemoteInstanceGroupObject(test_objects._RemoteTest,
                                    _TestInstanceGroupObjects):
    pass

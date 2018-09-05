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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_versionedobjects import fixture as ovo_fixture

from nova import context
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova import test


class InstanceGroupObjectTestCase(test.TestCase):
    def setUp(self):
        super(InstanceGroupObjectTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _api_group(self, **values):
        group = objects.InstanceGroup(context=self.context,
                                      user_id=self.context.user_id,
                                      project_id=self.context.project_id,
                                      name='foogroup',
                                      policy='anti-affinity',
                                      rules={'max_server_per_host': 1},
                                      members=['memberfoo'])
        group.update(values)
        group.create()
        return group

    def test_create(self):
        create_group = self._api_group()
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                      create_group.uuid)
        self.assertIsInstance(db_group.policy, api_models.InstanceGroupPolicy)
        self.assertEqual(create_group.policies[0], db_group.policy.policy)
        self.assertEqual(create_group.id, db_group.policy.group_id)
        ovo_fixture.compare_obj(
            self, create_group, db_group,
            comparators={'policy': lambda a, b: b == a.policy},
            allow_missing=('deleted', 'deleted_at', 'policies', '_rules'))
        self.assertEqual({'max_server_per_host': 1}, create_group.rules)

    def test_destroy(self):
        create_group = self._api_group()
        create_group.destroy()
        self.assertRaises(exception.InstanceGroupNotFound,
                          create_group._get_from_db_by_uuid, self.context,
                          create_group.uuid)

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    def test_save(self, _mock_notify):
        create_group = self._api_group()
        create_group.members = ['memberbar1', 'memberbar2']
        create_group.name = 'anewname'
        create_group.save()
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        ovo_fixture.compare_obj(
            self, create_group, db_group,
            comparators={'policy': lambda a, b: b == a.policy},
            allow_missing=('deleted', 'deleted_at', 'policies', '_rules'))
        self.assertEqual({'max_server_per_host': 1}, create_group.rules)

    def test_add_members(self):
        create_group = self._api_group()
        new_member = ['memberbar']
        objects.InstanceGroup.add_members(self.context, create_group.uuid,
                                          new_member)
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        self.assertEqual(create_group.members + new_member, db_group.members)

    def test_add_members_to_group_with_no_members(self):
        create_group = self._api_group(members=[])
        new_member = ['memberbar']
        objects.InstanceGroup.add_members(self.context, create_group.uuid,
                                          new_member)
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        self.assertEqual(new_member, db_group.members)

    def test_remove_members(self):
        create_group = self._api_group(members=[])
        # Add new members.
        new_members = [uuids.instance1, uuids.instance2, uuids.instance3]
        objects.InstanceGroup.add_members(self.context, create_group.uuid,
                                          new_members)
        # We already have tests for adding members, so we don't have to
        # verify they were added.

        # Remove the first two members we added.
        objects.InstanceGroup._remove_members_in_db(self.context,
                                                    create_group.id,
                                                    new_members[:2])
        # Refresh the group from the database.
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        # We should have one new member left.
        self.assertEqual([uuids.instance3], db_group.members)

    def test_get_by_uuid(self):
        create_group = self._api_group()
        get_group = objects.InstanceGroup.get_by_uuid(self.context,
                                                      create_group.uuid)
        self.assertTrue(base.obj_equal_prims(create_group, get_group))

    def test_get_by_name(self):
        create_group = self._api_group()
        get_group = objects.InstanceGroup.get_by_name(self.context,
                                                      create_group.name)
        self.assertTrue(base.obj_equal_prims(create_group, get_group))

    def test_get_by_instance_uuid(self):
        create_group = self._api_group(members=[uuids.instance])
        get_group = objects.InstanceGroup.get_by_instance_uuid(self.context,
                                                               uuids.instance)
        self.assertTrue(base.obj_equal_prims(create_group, get_group))

    def test_get_by_project_id(self):
        create_group = self._api_group()
        get_groups = objects.InstanceGroupList.get_by_project_id(
                self.context, self.context.project_id)
        self.assertEqual(1, len(get_groups))
        self.assertTrue(base.obj_equal_prims(create_group, get_groups[0]))
        ovo_fixture.compare_obj(self, get_groups[0], create_group)

    def test_get_all(self):
        create_group = self._api_group()
        get_groups = objects.InstanceGroupList.get_all(self.context)
        self.assertEqual(1, len(get_groups))
        self.assertTrue(base.obj_equal_prims(create_group, get_groups[0]))
        ovo_fixture.compare_obj(self, get_groups[0], create_group)

    def test_get_counts(self):
        # _api_group() creates a group with project_id and user_id from
        # self.context by default
        self._api_group()
        self._api_group(project_id='foo')
        self._api_group(user_id='bar')

        # Count only across a project
        counts = objects.InstanceGroupList.get_counts(self.context, 'foo')
        self.assertEqual(1, counts['project']['server_groups'])
        self.assertNotIn('user', counts)

        # Count across a project and a user
        counts = objects.InstanceGroupList.get_counts(
            self.context, self.context.project_id,
            user_id=self.context.user_id)

        self.assertEqual(2, counts['project']['server_groups'])
        self.assertEqual(1, counts['user']['server_groups'])

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
from oslo_versionedobjects import fixture as ovo_fixture

from nova import context
from nova.db.sqlalchemy import api as db_api
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import instance_group
from nova import test
from nova.tests import uuidsentinel as uuids


class InstanceGroupObjectTestCase(test.TestCase):
    def setUp(self):
        super(InstanceGroupObjectTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _api_group(self, **values):
        group = objects.InstanceGroup(context=self.context,
                                      user_id=self.context.user_id,
                                      project_id=self.context.project_id,
                                      name='foogroup',
                                      policies=['foo1', 'foo2'],
                                      members=['memberfoo'])
        group.update(values)
        group.create()
        return group

    def _main_group(self, policies=None, members=None, **values):
        vals = {
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            'name': 'foogroup',
        }
        vals.update(values)
        policies = policies or ['foo1', 'foo2']
        members = members or ['memberfoo']
        return db_api.instance_group_create(self.context, vals,
                                            policies=policies,
                                            members=members)

    def test_create(self):
        create_group = self._api_group()
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                      create_group.uuid)
        ovo_fixture.compare_obj(self, create_group, db_group,
                                allow_missing=('deleted', 'deleted_at'))

    def test_create_duplicate_in_main(self):
        self._main_group(uuid=uuids.main)
        self.assertRaises(exception.ObjectActionError,
                          self._api_group, uuid=uuids.main)

    def test_destroy(self):
        create_group = self._api_group()
        create_group.destroy()
        self.assertRaises(exception.InstanceGroupNotFound,
                          create_group._get_from_db_by_uuid, self.context,
                          create_group.uuid)

    def test_destroy_main(self):
        db_group = self._main_group()
        create_group = objects.InstanceGroup._from_db_object(
                self.context, objects.InstanceGroup(), db_group)
        create_group.destroy()
        self.assertRaises(exception.InstanceGroupNotFound,
                          db_api.instance_group_get, self.context,
                          create_group.uuid)

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    def test_save(self, _mock_notify):
        create_group = self._api_group()
        create_group.policies = ['bar1', 'bar2']
        create_group.members = ['memberbar1', 'memberbar2']
        create_group.name = 'anewname'
        create_group.save()
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        ovo_fixture.compare_obj(self, create_group, db_group,
                                allow_missing=('deleted', 'deleted_at'))

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    def test_save_main(self, _mock_notify):
        db_group = self._main_group()
        create_group = objects.InstanceGroup._from_db_object(
                self.context, objects.InstanceGroup(), db_group)
        create_group.policies = ['bar1', 'bar2']
        create_group.members = ['memberbar1', 'memberbar2']
        create_group.name = 'anewname'
        create_group.save()
        db_group = db_api.instance_group_get(self.context, create_group.uuid)
        ovo_fixture.compare_obj(self, create_group, db_group)

    def test_add_members(self):
        create_group = self._api_group()
        new_member = ['memberbar']
        objects.InstanceGroup.add_members(self.context, create_group.uuid,
                                          new_member)
        db_group = create_group._get_from_db_by_uuid(self.context,
                                                     create_group.uuid)
        self.assertEqual(create_group.members + new_member, db_group.members)

    def test_add_members_main(self):
        db_group = self._main_group()
        create_group = objects.InstanceGroup._from_db_object(
                self.context, objects.InstanceGroup(), db_group)
        new_member = ['memberbar']
        objects.InstanceGroup.add_members(self.context, create_group.uuid,
                                          new_member)
        db_group = db_api.instance_group_get(self.context, create_group.uuid)
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

    def test_get_by_uuid_main(self):
        db_group = self._main_group()
        get_group = objects.InstanceGroup.get_by_uuid(self.context,
                                                      db_group.uuid)
        ovo_fixture.compare_obj(self, get_group, db_group)

    def test_get_by_name(self):
        create_group = self._api_group()
        get_group = objects.InstanceGroup.get_by_name(self.context,
                                                      create_group.name)
        self.assertTrue(base.obj_equal_prims(create_group, get_group))

    def test_get_by_name_main(self):
        db_group = self._main_group()
        get_group = objects.InstanceGroup.get_by_name(self.context,
                                                      db_group.name)
        ovo_fixture.compare_obj(self, get_group, db_group)

    def test_get_by_instance_uuid(self):
        create_group = self._api_group(members=[uuids.instance])
        get_group = objects.InstanceGroup.get_by_instance_uuid(self.context,
                                                               uuids.instance)
        self.assertTrue(base.obj_equal_prims(create_group, get_group))

    def test_get_by_instance_uuid_main(self):
        db_group = self._main_group(members=[uuids.instance])
        get_group = objects.InstanceGroup.get_by_instance_uuid(self.context,
                                                               uuids.instance)
        ovo_fixture.compare_obj(self, get_group, db_group)

    def test_get_by_project_id(self):
        create_group = self._api_group()
        db_group = self._main_group()
        get_groups = objects.InstanceGroupList.get_by_project_id(
                self.context, self.context.project_id)
        self.assertEqual(2, len(get_groups))
        self.assertTrue(base.obj_equal_prims(create_group, get_groups[0]))
        ovo_fixture.compare_obj(self, get_groups[1], db_group)

    def test_get_all(self):
        create_group = self._api_group()
        db_group = self._main_group()
        get_groups = objects.InstanceGroupList.get_all(self.context)
        self.assertEqual(2, len(get_groups))
        self.assertTrue(base.obj_equal_prims(create_group, get_groups[0]))
        ovo_fixture.compare_obj(self, get_groups[1], db_group)

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

    def test_migrate_instance_groups(self):
        self._api_group(name='apigroup')
        orig_main_models = []
        orig_main_models.append(self._main_group(name='maingroup1'))
        orig_main_models.append(self._main_group(name='maingroup2'))
        orig_main_models.append(self._main_group(name='maingroup3'))

        total, done = instance_group.migrate_instance_groups_to_api_db(
                        self.context, 2)
        self.assertEqual(2, total)
        self.assertEqual(2, done)

        # This only fetches from the api db
        api_groups = objects.InstanceGroupList._get_from_db(self.context)
        self.assertEqual(3, len(api_groups))

        # This only fetches from the main db
        main_groups = db_api.instance_group_get_all(self.context)
        self.assertEqual(1, len(main_groups))

        self.assertEqual((1, 1),
                         instance_group.migrate_instance_groups_to_api_db(
                                self.context, 100))
        self.assertEqual((0, 0),
                         instance_group.migrate_instance_groups_to_api_db(
                                self.context, 100))

        # Verify the api_models have all their attributes set properly
        api_models = objects.InstanceGroupList._get_from_db(self.context)
        # Filter out the group that was created in the api db originally
        api_models = [x for x in api_models if x.name != 'apigroup']
        key_func = lambda model: model.uuid
        api_models = sorted(api_models, key=key_func)
        orig_main_models = sorted(orig_main_models, key=key_func)
        ignore_fields = ('id', 'hosts', 'deleted', 'deleted_at', 'created_at',
                         'updated_at')
        for i in range(len(api_models)):
            for field in instance_group.InstanceGroup.fields:
                if field not in ignore_fields:
                    self.assertEqual(orig_main_models[i][field],
                                     api_models[i][field])

    def test_migrate_instance_groups_skips_existing(self):
        self._api_group(uuid=uuids.group)
        self._main_group(uuid=uuids.group)
        total, done = instance_group.migrate_instance_groups_to_api_db(
                        self.context, 100)
        self.assertEqual(1, total)
        self.assertEqual(1, done)
        total, done = instance_group.migrate_instance_groups_to_api_db(
                        self.context, 100)
        self.assertEqual(0, total)
        self.assertEqual(0, done)

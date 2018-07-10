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

from nova.objects import tag
from nova.tests.unit.objects import test_objects

RESOURCE_ID = '123'
TAG_NAME1 = 'fake-tag1'
TAG_NAME2 = 'fake-tag2'

fake_tag1 = {
    'resource_id': RESOURCE_ID,
    'tag': TAG_NAME1,
    }

fake_tag2 = {
    'resource_id': RESOURCE_ID,
    'tag': TAG_NAME1,
    }

fake_tag_list = [fake_tag1, fake_tag2]


def _get_tag(resource_id, tag_name, context=None):
    t = tag.Tag(context=context)
    t.resource_id = resource_id
    t.tag = tag_name
    return t


class _TestTagObject(object):
    @mock.patch('nova.db.api.instance_tag_add')
    def test_create(self, tag_add):
        tag_add.return_value = fake_tag1
        tag_obj = _get_tag(RESOURCE_ID, TAG_NAME1, context=self.context)
        tag_obj.create()

        tag_add.assert_called_once_with(self.context, RESOURCE_ID, TAG_NAME1)
        self.compare_obj(tag_obj, fake_tag1)

    @mock.patch('nova.db.api.instance_tag_delete')
    def test_destroy(self, tag_delete):
        tag.Tag.destroy(self.context, RESOURCE_ID, TAG_NAME1)
        tag_delete.assert_called_once_with(self.context,
                                           RESOURCE_ID, TAG_NAME1)

    @mock.patch('nova.db.api.instance_tag_exists')
    def test_exists(self, instance_tag_exists):
        tag.Tag.exists(self.context, RESOURCE_ID, TAG_NAME1)
        instance_tag_exists.assert_called_once_with(
            self.context, RESOURCE_ID, TAG_NAME1)


class TestMigrationObject(test_objects._LocalTest,
                          _TestTagObject):
    pass


class TestRemoteMigrationObject(test_objects._RemoteTest,
                                _TestTagObject):
    pass


class _TestTagList(object):
    def _compare_tag_list(self, tag_list, tag_list_obj):
        self.assertEqual(len(tag_list), len(tag_list_obj))

        for obj, fake in zip(tag_list_obj, tag_list):
            self.assertIsInstance(obj, tag.Tag)
            self.assertEqual(obj.tag, fake['tag'])
            self.assertEqual(obj.resource_id, fake['resource_id'])

    @mock.patch('nova.db.api.instance_tag_get_by_instance_uuid')
    def test_get_by_resource_id(self, get_by_inst):
        get_by_inst.return_value = fake_tag_list

        tag_list_obj = tag.TagList.get_by_resource_id(
            self.context, RESOURCE_ID)

        get_by_inst.assert_called_once_with(self.context, RESOURCE_ID)
        self._compare_tag_list(fake_tag_list, tag_list_obj)

    @mock.patch('nova.db.api.instance_tag_set')
    def test_create(self, tag_set):
        tag_set.return_value = fake_tag_list
        tag_list_obj = tag.TagList.create(
            self.context, RESOURCE_ID, [TAG_NAME1, TAG_NAME2])

        tag_set.assert_called_once_with(self.context,
                                        RESOURCE_ID, [TAG_NAME1, TAG_NAME2])
        self._compare_tag_list(fake_tag_list, tag_list_obj)

    @mock.patch('nova.db.api.instance_tag_delete_all')
    def test_destroy(self, tag_delete_all):
        tag.TagList.destroy(self.context, RESOURCE_ID)
        tag_delete_all.assert_called_once_with(self.context, RESOURCE_ID)


class TestTagList(test_objects._LocalTest, _TestTagList):
    pass


class TestTagListRemote(test_objects._RemoteTest, _TestTagList):
    pass

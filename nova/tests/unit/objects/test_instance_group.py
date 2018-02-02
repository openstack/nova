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

import copy

import mock
from oslo_utils import timeutils

from nova import exception
from nova import objects
from nova.tests.unit.objects import test_objects
from nova.tests.unit import utils as test_utils
from nova.tests import uuidsentinel as uuids


_TS_NOW = timeutils.utcnow(with_timezone=True)
# o.vo.fields.DateTimeField converts to tz-aware and
# in process we lose microsecond resolution.
_TS_NOW = _TS_NOW.replace(microsecond=0)
_DB_UUID = uuids.fake
_INST_GROUP_DB = {
    'id': 1,
    'uuid': _DB_UUID,
    'user_id': 'fake_user',
    'project_id': 'fake_project',
    'name': 'fake_name',
    'policies': ['policy1', 'policy2'],
    'members': ['instance_id1', 'instance_id2'],
    'deleted': False,
    'created_at': _TS_NOW,
    'updated_at': _TS_NOW,
    'deleted_at': None,
}


class _TestInstanceGroupObject(object):

    @mock.patch('nova.db.instance_group_get', return_value=_INST_GROUP_DB)
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid',
            side_effect=exception.InstanceGroupNotFound(group_uuid=_DB_UUID))
    def test_get_by_uuid_main(self, mock_api_get, mock_db_get):
        obj = objects.InstanceGroup.get_by_uuid(self.context,
                                                       _DB_UUID)
        mock_db_get.assert_called_once_with(self.context, _DB_UUID)
        self.assertEqual(_INST_GROUP_DB['members'], obj.members)
        self.assertEqual(_INST_GROUP_DB['policies'], obj.policies)
        self.assertEqual(_DB_UUID, obj.uuid)
        self.assertEqual(_INST_GROUP_DB['project_id'], obj.project_id)
        self.assertEqual(_INST_GROUP_DB['user_id'], obj.user_id)
        self.assertEqual(_INST_GROUP_DB['name'], obj.name)

    @mock.patch('nova.db.instance_group_get_by_instance',
                return_value=_INST_GROUP_DB)
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_instance')
    def test_get_by_instance_uuid_main(self, mock_api_get, mock_db_get):
        error = exception.InstanceGroupNotFound(group_uuid='')
        mock_api_get.side_effect = error
        objects.InstanceGroup.get_by_instance_uuid(
                self.context, mock.sentinel.instance_uuid)
        mock_db_get.assert_called_once_with(
                self.context, mock.sentinel.instance_uuid)

    @mock.patch('nova.db.instance_group_get')
    def test_refresh(self, mock_db_get):
        changed_group = copy.deepcopy(_INST_GROUP_DB)
        changed_group['name'] = 'new_name'
        mock_db_get.side_effect = [_INST_GROUP_DB, changed_group]
        obj = objects.InstanceGroup.get_by_uuid(self.context,
                                                       _DB_UUID)
        self.assertEqual(_INST_GROUP_DB['name'], obj.name)
        obj.refresh()
        self.assertEqual('new_name', obj.name)
        self.assertEqual(set([]), obj.obj_what_changed())

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.db.instance_group_update')
    @mock.patch('nova.db.instance_group_get')
    def test_save_main(self, mock_db_get, mock_db_update, mock_notify):
        changed_group = copy.deepcopy(_INST_GROUP_DB)
        changed_group['name'] = 'new_name'
        mock_db_get.side_effect = [_INST_GROUP_DB, changed_group]
        obj = objects.InstanceGroup.get_by_uuid(self.context,
                                                       _DB_UUID)
        self.assertEqual(obj.name, 'fake_name')
        obj.name = 'new_name'
        obj.policies = ['policy1']  # Remove policy 2
        obj.members = ['instance_id1']  # Remove member 2
        obj.save()
        mock_db_update.assert_called_once_with(self.context, _DB_UUID,
                                               {'name': 'new_name',
                                                'members': ['instance_id1'],
                                                'policies': ['policy1']})
        mock_notify.assert_called_once_with(self.context, "update",
                                               {'name': 'new_name',
                                                'members': ['instance_id1'],
                                                'policies': ['policy1'],
                                                'server_group_id': _DB_UUID})

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.db.instance_group_update')
    @mock.patch('nova.db.instance_group_get')
    def test_save_without_hosts_main(self, mock_db_get, mock_db_update,
                                     mock_notify):
        mock_db_get.side_effect = [_INST_GROUP_DB, _INST_GROUP_DB]
        obj = objects.InstanceGroup.get_by_uuid(self.context, _DB_UUID)
        obj.hosts = ['fake-host1']
        self.assertRaises(exception.InstanceGroupSaveException,
                          obj.save)
        # make sure that we can save by removing hosts from what is updated
        obj.obj_reset_changes(['hosts'])
        obj.save()
        # since hosts was the only update, there is no actual call
        self.assertFalse(mock_db_update.called)
        self.assertFalse(mock_notify.called)

    @mock.patch('nova.compute.utils.notify_about_server_group_action')
    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.objects.InstanceGroup._create_in_db',
                return_value=_INST_GROUP_DB)
    def test_create(self, mock_db_create, mock_notify, mock_notify_action):
        obj = objects.InstanceGroup(context=self.context)
        obj.uuid = _DB_UUID
        obj.name = _INST_GROUP_DB['name']
        obj.user_id = _INST_GROUP_DB['user_id']
        obj.project_id = _INST_GROUP_DB['project_id']
        obj.members = _INST_GROUP_DB['members']
        obj.policies = _INST_GROUP_DB['policies']
        obj.updated_at = _TS_NOW
        obj.created_at = _TS_NOW
        obj.deleted_at = None
        obj.deleted = False
        obj.create()
        mock_db_create.assert_called_once_with(
            self.context,
            {'uuid': _DB_UUID,
             'name': _INST_GROUP_DB['name'],
             'user_id': _INST_GROUP_DB['user_id'],
             'project_id': _INST_GROUP_DB['project_id'],
             'created_at': _TS_NOW,
             'updated_at': _TS_NOW,
             'deleted_at': None,
             'deleted': False,
             },
            members=_INST_GROUP_DB['members'],
            policies=_INST_GROUP_DB['policies'])
        mock_notify.assert_called_once_with(
            self.context, "create",
            {'uuid': _DB_UUID,
             'name': _INST_GROUP_DB['name'],
             'user_id': _INST_GROUP_DB['user_id'],
             'project_id': _INST_GROUP_DB['project_id'],
             'created_at': _TS_NOW,
             'updated_at': _TS_NOW,
             'deleted_at': None,
             'deleted': False,
             'members': _INST_GROUP_DB['members'],
             'policies': _INST_GROUP_DB['policies'],
             'server_group_id': _DB_UUID})

        def _group_matcher(group):
            """Custom mock call matcher method."""
            return (group.uuid == _DB_UUID and
                group.name == _INST_GROUP_DB['name'] and
                group.user_id == _INST_GROUP_DB['user_id'] and
                group.project_id == _INST_GROUP_DB['project_id'] and
                group.created_at == _TS_NOW and
                group.updated_at == _TS_NOW and
                group.deleted_at is None and
                group.deleted is False and
                group.members == _INST_GROUP_DB['members'] and
                group.policies == _INST_GROUP_DB['policies'] and
                group.id == 1)

        group_matcher = test_utils.CustomMockCallMatcher(_group_matcher)

        self.assertRaises(exception.ObjectActionError, obj.create)
        mock_notify_action.assert_called_once_with(context=self.context,
                                                   group=group_matcher,
                                                   action='create')

    @mock.patch('nova.compute.utils.notify_about_server_group_action')
    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.objects.InstanceGroup._destroy_in_db')
    def test_destroy(self, mock_db_delete, mock_notify, mock_notify_action):
        obj = objects.InstanceGroup(context=self.context)
        obj.uuid = _DB_UUID
        obj.destroy()

        group_matcher = test_utils.CustomMockCallMatcher(
            lambda group: group.uuid == _DB_UUID)

        mock_notify_action.assert_called_once_with(context=obj._context,
                                                   group=group_matcher,
                                                   action='delete')
        mock_db_delete.assert_called_once_with(self.context, _DB_UUID)
        mock_notify.assert_called_once_with(self.context, "delete",
                                            {'server_group_id': _DB_UUID})

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.objects.InstanceGroup._add_members_in_db')
    def test_add_members(self, mock_members_add_db, mock_notify):
        fake_member_models = [{'instance_uuid': mock.sentinel.uuid}]
        fake_member_uuids = [mock.sentinel.uuid]
        mock_members_add_db.return_value = fake_member_models
        members = objects.InstanceGroup.add_members(self.context,
                                                    _DB_UUID,
                                                    fake_member_uuids)
        self.assertEqual(fake_member_uuids, members)
        mock_members_add_db.assert_called_once_with(
                self.context,
                _DB_UUID,
                fake_member_uuids)
        mock_notify.assert_called_once_with(
                self.context, "addmember",
                {'instance_uuids': fake_member_uuids,
                 'server_group_id': _DB_UUID})

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid',
                return_value=_INST_GROUP_DB)
    def test_count_members_by_user(self, mock_get_db, mock_il_get):
        mock_il_get.return_value = [mock.ANY]
        obj = objects.InstanceGroup.get_by_uuid(self.context, _DB_UUID)
        expected_filters = {
            'uuid': ['instance_id1', 'instance_id2'],
            'user_id': 'fake_user',
            'deleted': False
        }
        self.assertEqual(1, obj.count_members_by_user('fake_user'))
        mock_il_get.assert_called_once_with(self.context,
                                            filters=expected_filters)

    @mock.patch('nova.objects.InstanceList.get_by_filters')
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid',
                return_value=_INST_GROUP_DB)
    def test_get_hosts(self, mock_get_db, mock_il_get):
        mock_il_get.return_value = [objects.Instance(host='host1'),
                                    objects.Instance(host='host2'),
                                    objects.Instance(host=None)]
        obj = objects.InstanceGroup.get_by_uuid(self.context, _DB_UUID)
        hosts = obj.get_hosts()
        self.assertEqual(['instance_id1', 'instance_id2'], obj.members)
        expected_filters = {
            'uuid': ['instance_id1', 'instance_id2'],
            'deleted': False
        }
        mock_il_get.assert_called_once_with(self.context,
                                            filters=expected_filters)
        self.assertEqual(2, len(hosts))
        self.assertIn('host1', hosts)
        self.assertIn('host2', hosts)

        # Test manual exclusion
        mock_il_get.reset_mock()
        hosts = obj.get_hosts(exclude=['instance_id1'])
        expected_filters = {
            'uuid': set(['instance_id2']),
            'deleted': False
        }
        mock_il_get.assert_called_once_with(self.context,
                                            filters=expected_filters)

    def test_obj_make_compatible(self):
        obj = objects.InstanceGroup(self.context, **_INST_GROUP_DB)
        obj_primitive = obj.obj_to_primitive()
        self.assertNotIn('metadetails', obj_primitive)
        obj.obj_make_compatible(obj_primitive, '1.6')
        self.assertEqual({}, obj_primitive['metadetails'])

    @mock.patch.object(objects.InstanceList, 'get_by_filters')
    def test_load_hosts(self, mock_get_by_filt):
        mock_get_by_filt.return_value = [objects.Instance(host='host1'),
                                         objects.Instance(host='host2')]

        obj = objects.InstanceGroup(self.context, members=['uuid1'],
                                    uuid=uuids.group)
        self.assertEqual(2, len(obj.hosts))
        self.assertIn('host1', obj.hosts)
        self.assertIn('host2', obj.hosts)
        self.assertNotIn('hosts', obj.obj_what_changed())

    def test_load_anything_else_but_hosts(self):
        obj = objects.InstanceGroup(self.context)
        self.assertRaises(exception.ObjectActionError, getattr, obj, 'members')


class TestInstanceGroupObject(test_objects._LocalTest,
                              _TestInstanceGroupObject):
    pass


class TestRemoteInstanceGroupObject(test_objects._RemoteTest,
                                    _TestInstanceGroupObject):
    pass


def _mock_db_list_get(*args):
    instances = [(uuids.f1, 'f1', 'p1'),
                 (uuids.f2, 'f2', 'p1'),
                 (uuids.f3, 'f3', 'p2'),
                 (uuids.f4, 'f4', 'p2')]
    result = []
    for instance in instances:
        values = copy.deepcopy(_INST_GROUP_DB)
        values['uuid'] = instance[0]
        values['name'] = instance[1]
        values['project_id'] = instance[2]
        result.append(values)
    return result


class _TestInstanceGroupListObject(object):

    @mock.patch('nova.db.instance_group_get_all')
    @mock.patch('nova.objects.InstanceGroupList._get_from_db')
    def test_list_all_main(self, mock_api_get, mock_db_get):
        mock_api_get.return_value = []
        mock_db_get.side_effect = _mock_db_list_get
        inst_list = objects.InstanceGroupList.get_all(self.context)
        self.assertEqual(4, len(inst_list.objects))
        mock_db_get.assert_called_once_with(self.context)

    @mock.patch('nova.db.instance_group_get_all_by_project_id')
    @mock.patch('nova.objects.InstanceGroupList._get_from_db')
    def test_list_by_project_id_main(self, mock_api_get, mock_db_get):
        mock_api_get.return_value = []
        mock_db_get.side_effect = _mock_db_list_get
        objects.InstanceGroupList.get_by_project_id(
                self.context, mock.sentinel.project_id)
        mock_db_get.assert_called_once_with(
                self.context, mock.sentinel.project_id)

    @mock.patch('nova.db.instance_group_get_all_by_project_id')
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_name')
    def test_get_by_name_main(self, mock_api_get, mock_db_get):
        error = exception.InstanceGroupNotFound(group_uuid='f1')
        mock_api_get.side_effect = error
        mock_db_get.side_effect = _mock_db_list_get
        # Need the project_id value set, otherwise we'd use mock.sentinel
        mock_ctx = mock.MagicMock()
        mock_ctx.project_id = 'fake_project'
        ig = objects.InstanceGroup.get_by_name(mock_ctx, 'f1')
        mock_db_get.assert_called_once_with(mock_ctx, 'fake_project')
        self.assertEqual('f1', ig.name)
        self.assertRaises(exception.InstanceGroupNotFound,
                          objects.InstanceGroup.get_by_name,
                          mock_ctx, 'unknown')

    @mock.patch('nova.objects.InstanceGroup.get_by_uuid')
    @mock.patch('nova.objects.InstanceGroup.get_by_name')
    def test_get_by_hint(self, mock_name, mock_uuid):
        objects.InstanceGroup.get_by_hint(self.context, _DB_UUID)
        mock_uuid.assert_called_once_with(self.context, _DB_UUID)
        objects.InstanceGroup.get_by_hint(self.context, 'name')
        mock_name.assert_called_once_with(self.context, 'name')


class TestInstanceGroupListObject(test_objects._LocalTest,
                                  _TestInstanceGroupListObject):
    pass


class TestRemoteInstanceGroupListObject(test_objects._RemoteTest,
                                        _TestInstanceGroupListObject):
    pass

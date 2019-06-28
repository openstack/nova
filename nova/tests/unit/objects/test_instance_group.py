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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import exception as ovo_exc

from nova import exception
from nova import objects
from nova.tests.unit.objects import test_objects
from nova.tests.unit import utils as test_utils


_TS_NOW = timeutils.utcnow(with_timezone=True)
# o.vo.fields.DateTimeField converts to tz-aware and
# in process we lose microsecond resolution.
_TS_NOW = _TS_NOW.replace(microsecond=0)
_DB_UUID = uuids.fake
_INST_GROUP_POLICY_DB = {
    'policy': 'policy1',
    'rules': jsonutils.dumps({'max_server_per_host': '2'}),
}
_INST_GROUP_DB = {
    'id': 1,
    'uuid': _DB_UUID,
    'user_id': 'fake_user',
    'project_id': 'fake_project',
    'name': 'fake_name',
    # a group can only have 1 policy associated with it
    'policy': _INST_GROUP_POLICY_DB,
    '_policies': [_INST_GROUP_POLICY_DB],
    'members': ['instance_id1', 'instance_id2'],
    'created_at': _TS_NOW,
    'updated_at': _TS_NOW,
}
_INST_GROUP_OBJ_VALS = dict(
    {k: v for k, v in
     _INST_GROUP_DB.items()
     if k not in ('policy', '_policies')},
    policy=_INST_GROUP_POLICY_DB['policy'],
    rules=jsonutils.loads(_INST_GROUP_POLICY_DB['rules']))


class _TestInstanceGroupObject(object):

    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid',
                return_value=_INST_GROUP_DB)
    def test_get_by_uuid(self, mock_api_get):
        obj = objects.InstanceGroup.get_by_uuid(self.context,
                                                       _DB_UUID)
        mock_api_get.assert_called_once_with(self.context, _DB_UUID)
        self.assertEqual(_INST_GROUP_DB['members'], obj.members)
        self.assertEqual([_INST_GROUP_POLICY_DB['policy']], obj.policies)
        self.assertEqual(_DB_UUID, obj.uuid)
        self.assertEqual(_INST_GROUP_DB['project_id'], obj.project_id)
        self.assertEqual(_INST_GROUP_DB['user_id'], obj.user_id)
        self.assertEqual(_INST_GROUP_DB['name'], obj.name)
        self.assertEqual(_INST_GROUP_POLICY_DB['policy'], obj.policy)
        self.assertEqual({'max_server_per_host': 2}, obj.rules)

    def test_rules_helper(self):
        obj = objects.InstanceGroup()
        self.assertEqual({}, obj.rules)
        self.assertNotIn('_rules', obj)
        obj._rules = {}
        self.assertEqual({}, obj.rules)
        self.assertIn('_rules', obj)

    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_instance',
                return_value=_INST_GROUP_DB)
    def test_get_by_instance_uuid(self, mock_api_get):
        objects.InstanceGroup.get_by_instance_uuid(
                self.context, mock.sentinel.instance_uuid)
        mock_api_get.assert_called_once_with(
                self.context, mock.sentinel.instance_uuid)

    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid')
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
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid')
    @mock.patch('nova.objects.instance_group._instance_group_members_add')
    def test_save(self, mock_members_add, mock_db_get, mock_notify):
        changed_group = copy.deepcopy(_INST_GROUP_DB)
        changed_group['name'] = 'new_name'
        db_group = copy.deepcopy(_INST_GROUP_DB)
        mock_db_get.return_value = db_group
        obj = objects.InstanceGroup(self.context, **_INST_GROUP_OBJ_VALS)
        self.assertEqual(obj.name, 'fake_name')
        obj.obj_reset_changes()
        self.assertEqual(set([]), obj.obj_what_changed())
        obj.name = 'new_name'
        obj.members = ['instance_id1']  # Remove member 2
        obj.save()
        self.assertEqual(set([]), obj.obj_what_changed())
        mock_members_add.assert_called_once_with(
            self.context, mock_db_get.return_value, ['instance_id1'])
        mock_notify.assert_called_once_with(self.context, "update",
                                               {'name': 'new_name',
                                                'members': ['instance_id1'],
                                                'server_group_id': _DB_UUID})

    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_uuid')
    def test_save_without_hosts(self, mock_db_get, mock_notify):
        mock_db_get.return_value = _INST_GROUP_DB
        obj = objects.InstanceGroup(self.context, **_INST_GROUP_OBJ_VALS)
        obj.obj_reset_changes()
        obj.hosts = ['fake-host1']
        self.assertRaises(exception.InstanceGroupSaveException,
                          obj.save)
        # make sure that we can save by removing hosts from what is updated
        obj.obj_reset_changes(['hosts'])
        obj.save()
        # since hosts was the only update, there is no actual call
        self.assertFalse(mock_notify.called)

    def test_set_policies_failure(self):
        group_obj = objects.InstanceGroup(context=self.context,
                                          policies=['affinity'])
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
                          group_obj, 'policies', ['anti-affinity'])

    def test_save_policies(self):
        group_obj = objects.InstanceGroup(context=self.context)
        group_obj.policies = ['fake-host1']
        self.assertRaises(exception.InstanceGroupSaveException,
                          group_obj.save)

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
        obj.policies = [_INST_GROUP_DB['policy']['policy']]
        obj.updated_at = _TS_NOW
        obj.created_at = _TS_NOW
        obj.create()
        mock_db_create.assert_called_once_with(
            self.context,
            {'uuid': _DB_UUID,
             'name': _INST_GROUP_DB['name'],
             'user_id': _INST_GROUP_DB['user_id'],
             'project_id': _INST_GROUP_DB['project_id'],
             'created_at': _TS_NOW,
             'updated_at': _TS_NOW,
             },
            members=_INST_GROUP_DB['members'],
            policies=[_INST_GROUP_DB['policy']['policy']],
            policy=None,
            rules=None)
        mock_notify.assert_called_once_with(
            self.context, "create",
            {'uuid': _DB_UUID,
             'name': _INST_GROUP_DB['name'],
             'user_id': _INST_GROUP_DB['user_id'],
             'project_id': _INST_GROUP_DB['project_id'],
             'created_at': _TS_NOW,
             'updated_at': _TS_NOW,
             'members': _INST_GROUP_DB['members'],
             'policies': [_INST_GROUP_DB['policy']['policy']],
             'server_group_id': _DB_UUID})

        def _group_matcher(group):
            """Custom mock call matcher method."""
            return (group.uuid == _DB_UUID and
                group.name == _INST_GROUP_DB['name'] and
                group.user_id == _INST_GROUP_DB['user_id'] and
                group.project_id == _INST_GROUP_DB['project_id'] and
                group.created_at == _TS_NOW and
                group.updated_at == _TS_NOW and
                group.members == _INST_GROUP_DB['members'] and
                group.policies == [_INST_GROUP_DB['policy']['policy']] and
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

    @mock.patch('nova.compute.utils.notify_about_server_group_add_member')
    @mock.patch('nova.compute.utils.notify_about_server_group_update')
    @mock.patch('nova.objects.InstanceGroup._add_members_in_db')
    def test_add_members(self, mock_members_add_db, mock_notify,
                         mock_notify_add_member):
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
        mock_notify_add_member.assert_called_once_with(self.context, _DB_UUID)

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
                                            filters=expected_filters,
                                            expected_attrs=[])
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
                                            filters=expected_filters,
                                            expected_attrs=[])

    def test_obj_make_compatible(self):
        obj = objects.InstanceGroup(self.context, **_INST_GROUP_OBJ_VALS)
        data = lambda x: x['nova_object.data']
        obj_primitive = data(obj.obj_to_primitive())
        self.assertNotIn('metadetails', obj_primitive)
        obj.obj_make_compatible(obj_primitive, '1.6')
        self.assertEqual({}, obj_primitive['metadetails'])

    def test_obj_make_compatible_pre_1_11(self):
        none_policy_group = copy.deepcopy(_INST_GROUP_DB)
        none_policy_group['policy'] = None
        dbs = [_INST_GROUP_DB, none_policy_group]
        data = lambda x: x['nova_object.data']
        for db in dbs:
            ig = objects.InstanceGroup()
            obj = ig._from_db_object(self.context, ig, db)
            # Latest version obj has policy and policies
            obj_primitive = obj.obj_to_primitive()
            self.assertIn('policy', data(obj_primitive))
            self.assertIn('policies', data(obj_primitive))
            # Before 1.10, only has polices which is the list of policy name
            obj_primitive = obj.obj_to_primitive('1.10')
            self.assertNotIn('policy', data(obj_primitive))
            self.assertIn('policies', data(obj_primitive))
            self.assertEqual([db['policy']['policy']] if db['policy'] else [],
                             data(obj_primitive)['policies'])

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

    @mock.patch('nova.objects.InstanceGroup._get_from_db_by_name')
    def test_get_by_name(self, mock_api_get):
        db_group = copy.deepcopy(_INST_GROUP_DB)
        mock_api_get.side_effect = [
            db_group, exception.InstanceGroupNotFound(group_uuid='unknown')]
        ig = objects.InstanceGroup.get_by_name(self.context, 'fake_name')
        mock_api_get.assert_called_once_with(self.context, 'fake_name')
        self.assertEqual('fake_name', ig.name)
        self.assertRaises(exception.InstanceGroupNotFound,
                          objects.InstanceGroup.get_by_name,
                          self.context, 'unknown')

    @mock.patch('nova.objects.InstanceGroup.get_by_uuid')
    @mock.patch('nova.objects.InstanceGroup.get_by_name')
    def test_get_by_hint(self, mock_name, mock_uuid):
        objects.InstanceGroup.get_by_hint(self.context, _DB_UUID)
        mock_uuid.assert_called_once_with(self.context, _DB_UUID)
        objects.InstanceGroup.get_by_hint(self.context, 'name')
        mock_name.assert_called_once_with(self.context, 'name')


class TestInstanceGroupObject(test_objects._LocalTest,
                              _TestInstanceGroupObject):
    pass


class TestRemoteInstanceGroupObject(test_objects._RemoteTest,
                                    _TestInstanceGroupObject):
    pass


def _mock_db_list_get(*args, **kwargs):
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

    @mock.patch('nova.objects.InstanceGroupList._get_from_db')
    def test_list_all(self, mock_api_get):
        mock_api_get.side_effect = _mock_db_list_get
        inst_list = objects.InstanceGroupList.get_all(self.context)
        self.assertEqual(4, len(inst_list.objects))
        mock_api_get.assert_called_once_with(self.context)

    @mock.patch('nova.objects.InstanceGroupList._get_from_db')
    def test_list_by_project_id(self, mock_api_get):
        mock_api_get.side_effect = _mock_db_list_get
        objects.InstanceGroupList.get_by_project_id(
                self.context, mock.sentinel.project_id)
        mock_api_get.assert_called_once_with(
                self.context, project_id=mock.sentinel.project_id)


class TestInstanceGroupListObject(test_objects._LocalTest,
                                  _TestInstanceGroupListObject):
    pass


class TestRemoteInstanceGroupListObject(test_objects._RemoteTest,
                                        _TestInstanceGroupListObject):
    pass

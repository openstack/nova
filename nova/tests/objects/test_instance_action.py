#    Copyright 2013 IBM Corp.
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

from nova.compute import utils as compute_utils
from nova import db
from nova.objects import instance_action
from nova.openstack.common import timeutils
from nova.tests.objects import test_objects


NOW = timeutils.utcnow().replace(microsecond=0)
fake_action = {
    'created_at': NOW,
    'deleted_at': None,
    'updated_at': None,
    'deleted': False,
    'id': 123,
    'action': 'fake-action',
    'instance_uuid': 'fake-uuid',
    'request_id': 'fake-request',
    'user_id': 'fake-user',
    'project_id': 'fake-project',
    'start_time': NOW,
    'finish_time': None,
    'message': 'foo',
}
fake_event = {
    'created_at': NOW,
    'deleted_at': None,
    'updated_at': None,
    'deleted': False,
    'id': 123,
    'event': 'fake-event',
    'action_id': 123,
    'start_time': NOW,
    'finish_time': None,
    'result': 'fake-result',
    'traceback': 'fake-tb',
}


class _TestInstanceActionObject(object):
    @mock.patch.object(db, 'action_get_by_request_id')
    def test_get_by_request_id(self, mock_get):
        context = self.context
        mock_get.return_value = fake_action
        action = instance_action.InstanceAction.get_by_request_id(
            context, 'fake-uuid', 'fake-request')
        self.compare_obj(action, fake_action)
        mock_get.assert_called_once_with(context,
            'fake-uuid', 'fake-request')

    @mock.patch.object(db, 'action_start')
    def test_action_start(self, mock_start):
        expected_packed_values = compute_utils.pack_action_start(
            self.context, 'fake-uuid', 'fake-action')
        mock_start.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action', want_result=True)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.compare_obj(action, fake_action)

    @mock.patch.object(db, 'action_start')
    def test_action_start_no_result(self, mock_start):
        expected_packed_values = compute_utils.pack_action_start(
            self.context, 'fake-uuid', 'fake-action')
        mock_start.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action', want_result=False)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.assertIsNone(action)

    @mock.patch.object(db, 'action_finish')
    def test_action_finish(self, mock_finish):
        timeutils.set_time_override(override_time=NOW)
        expected_packed_values = compute_utils.pack_action_finish(
            self.context, 'fake-uuid')
        mock_finish.return_value = fake_action
        action = instance_action.InstanceAction.action_finish(
            self.context, 'fake-uuid', want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(action, fake_action)

    @mock.patch.object(db, 'action_finish')
    def test_action_finish_no_result(self, mock_finish):
        timeutils.set_time_override(override_time=NOW)
        expected_packed_values = compute_utils.pack_action_finish(
            self.context, 'fake-uuid')
        mock_finish.return_value = fake_action
        action = instance_action.InstanceAction.action_finish(
            self.context, 'fake-uuid', want_result=False)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.assertIsNone(action)

    @mock.patch.object(db, 'action_finish')
    @mock.patch.object(db, 'action_start')
    def test_finish(self, mock_start, mock_finish):
        timeutils.set_time_override(override_time=NOW)
        expected_packed_action_start = {
            'request_id': self.context.request_id,
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            'instance_uuid': 'fake-uuid',
            'action': 'fake-action',
            'start_time': self.context.timestamp,
        }
        expected_packed_action_finish = {
            'request_id': self.context.request_id,
            'instance_uuid': 'fake-uuid',
            'finish_time': NOW,
        }
        mock_start.return_value = fake_action
        mock_finish.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action')
        action.finish(self.context)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_action_start)
        mock_finish.assert_called_once_with(self.context,
                                           expected_packed_action_finish)
        self.compare_obj(action, fake_action)

    @mock.patch.object(db, 'actions_get')
    def test_get_list(self, mock_get):
        fake_actions = [dict(fake_action, id=1234),
                        dict(fake_action, id=5678)]
        mock_get.return_value = fake_actions
        obj_list = instance_action.InstanceActionList.get_by_instance_uuid(
            self.context, 'fake-uuid')
        for index, action in enumerate(obj_list):
            self.compare_obj(action, fake_actions[index])
        mock_get.assert_called_once_with(self.context, 'fake-uuid')


class TestInstanceActionObject(test_objects._LocalTest,
                               _TestInstanceActionObject):
    pass


class TestRemoteInstanceActionObject(test_objects._RemoteTest,
                                     _TestInstanceActionObject):
    pass


class _TestInstanceActionEventObject(object):
    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'action_event_get_by_id')
        db.action_event_get_by_id(self.context, 'fake-id').AndReturn(
            fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.get_by_id(self.context,
                                                              'fake-id')
        self.assertEqual(fake_event['id'], event.id)

    def test_event_start(self):
        self.mox.StubOutWithMock(db, 'action_event_start')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_start(
                self.context, 'fake-uuid', 'fake-event')).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_start(self.context,
                                                                'fake-uuid',
                                                                'fake-event')
        self.assertEqual(fake_event['id'], event.id)

    def test_event_start_no_result(self):
        self.mox.StubOutWithMock(db, 'action_event_start')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_start(
                'fake-uuid', 'fake-event')).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_start(
            self.context, 'fake-uuid', 'fake-event', want_result=False)
        self.assertIsNone(event)

    def test_event_finish(self):
        self.mox.StubOutWithMock(db, 'action_event_finish')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_finish(
                self.context, 'fake-uuid', 'fake-event', exc_val=None,
                exc_tb=None)).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_finish(self.context,
                                                                 'fake-uuid',
                                                                 'fake-event')
        self.assertEqual(fake_event['id'], event.id)

    def test_event_finish_no_result(self):
        self.mox.StubOutWithMock(db, 'action_event_finish')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_finish(
                self.context, 'fake-uuid', 'fake-event', exc_val=None,
                exc_tb=None)).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_finish(
            self.context, 'fake-uuid', 'fake-event', want_result=False)
        self.assertIsNone(event)

    def test_event_finish_with_failure(self):
        self.mox.StubOutWithMock(db, 'action_event_finish')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_finish(
                self.context, 'fake-uuid', 'fake-event', exc_val='fake-exc',
                exc_tb='fake-tb')).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_finish_with_failure(
            self.context, 'fake-uuid', 'fake-event', 'fake-exc', 'fake-tb')
        self.assertEqual(fake_event['id'], event.id)

    def test_finish(self):
        self.mox.StubOutWithMock(db, 'action_event_finish')
        db.action_event_start(
            self.context,
            compute_utils.pack_action_event_start(
                self.context, 'fake-uuid', 'fake-event')).AndReturn(fake_event)
        db.action_event_finish(
            self.context,
            compute_utils.pack_action_event_finish(
                self.context, 'fake-uuid', 'fake-event', exc_val=None,
                exc_tb=None)).AndReturn(fake_event)
        self.mox.ReplayAll()
        event = instance_action.InstanceActionEvent.event_start(
            self.context, 'fake-uuid', 'fake-event')
        event.finish()

    def test_get_by_action(self):
        self.mox.StubOutWithMock(db, 'action_events_get')
        events = [dict(fake_event, id=1234),
                  dict(fake_event, id=5678)]
        db.action_events_get(self.context, 'fake-action').AndReturn(events)
        self.mox.ReplayAll()
        event_list = instance_action.InstanceActionEventList.get_by_action(
            self.context, 'fake-action')
        self.assertEqual(2, len(event_list))
        for index, event in enumerate(event_list):
            self.assertEqual(events[index]['id'], event.id)

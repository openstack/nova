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

import traceback

import mock
from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils
import six

from nova import db
from nova.objects import instance_action
from nova import test
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


NOW = timeutils.utcnow().replace(microsecond=0)
fake_action = {
    'created_at': NOW,
    'deleted_at': None,
    'updated_at': None,
    'deleted': False,
    'id': 123,
    'action': 'fake-action',
    'instance_uuid': uuids.instance,
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

    def test_pack_action_start(self):
        values = instance_action.InstanceAction.pack_action_start(
            self.context, 'fake-uuid', 'fake-action')
        self.assertEqual(values['request_id'], self.context.request_id)
        self.assertEqual(values['user_id'], self.context.user_id)
        self.assertEqual(values['project_id'], self.context.project_id)
        self.assertEqual(values['instance_uuid'], 'fake-uuid')
        self.assertEqual(values['action'], 'fake-action')
        self.assertEqual(values['start_time'].replace(tzinfo=None),
                         self.context.timestamp)

    def test_pack_action_finish(self):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        values = instance_action.InstanceAction.pack_action_finish(
            self.context, 'fake-uuid')
        self.assertEqual(values['request_id'], self.context.request_id)
        self.assertEqual(values['instance_uuid'], 'fake-uuid')
        self.assertEqual(values['finish_time'].replace(tzinfo=None), NOW)

    @mock.patch.object(db, 'action_start')
    def test_action_start(self, mock_start):
        test_class = instance_action.InstanceAction
        expected_packed_values = test_class.pack_action_start(
            self.context, 'fake-uuid', 'fake-action')
        mock_start.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action', want_result=True)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.compare_obj(action, fake_action)

    @mock.patch.object(db, 'action_start')
    def test_action_start_no_result(self, mock_start):
        test_class = instance_action.InstanceAction
        expected_packed_values = test_class.pack_action_start(
            self.context, 'fake-uuid', 'fake-action')
        mock_start.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action', want_result=False)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.assertIsNone(action)

    @mock.patch.object(db, 'action_finish')
    def test_action_finish(self, mock_finish):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceAction
        expected_packed_values = test_class.pack_action_finish(
            self.context, 'fake-uuid')
        mock_finish.return_value = fake_action
        action = instance_action.InstanceAction.action_finish(
            self.context, 'fake-uuid', want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(action, fake_action)

    @mock.patch.object(db, 'action_finish')
    def test_action_finish_no_result(self, mock_finish):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceAction
        expected_packed_values = test_class.pack_action_finish(
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
        self.useFixture(utils_fixture.TimeFixture(NOW))
        expected_packed_action_start = {
            'request_id': self.context.request_id,
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            'instance_uuid': uuids.instance,
            'action': 'fake-action',
            'start_time': self.context.timestamp,
        }
        expected_packed_action_finish = {
            'request_id': self.context.request_id,
            'instance_uuid': uuids.instance,
            'finish_time': NOW,
        }
        mock_start.return_value = fake_action
        mock_finish.return_value = fake_action
        action = instance_action.InstanceAction.action_start(
            self.context, uuids.instance, 'fake-action')
        action.finish()
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
    @mock.patch.object(db, 'action_event_get_by_id')
    def test_get_by_id(self, mock_get):
        mock_get.return_value = fake_event
        event = instance_action.InstanceActionEvent.get_by_id(
            self.context, 'fake-action-id', 'fake-event-id')
        self.compare_obj(event, fake_event)
        mock_get.assert_called_once_with(self.context,
            'fake-action-id', 'fake-event-id')

    @mock.patch.object(db, 'action_event_start')
    def test_event_start(self, mock_start):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_start(
            self.context, 'fake-uuid', 'fake-event')
        mock_start.return_value = fake_event
        event = instance_action.InstanceActionEvent.event_start(
            self.context, 'fake-uuid', 'fake-event', want_result=True)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.compare_obj(event, fake_event)

    @mock.patch.object(db, 'action_event_start')
    def test_event_start_no_result(self, mock_start):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_start(
            self.context, 'fake-uuid', 'fake-event')
        mock_start.return_value = fake_event
        event = instance_action.InstanceActionEvent.event_start(
            self.context, 'fake-uuid', 'fake-event', want_result=False)
        mock_start.assert_called_once_with(self.context,
                                           expected_packed_values)
        self.assertIsNone(event)

    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish(self, mock_finish):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event')
        expected_packed_values['finish_time'] = NOW
        mock_finish.return_value = fake_event
        event = instance_action.InstanceActionEvent.event_finish(
            self.context, 'fake-uuid', 'fake-event', want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(event, fake_event)

    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish_no_result(self, mock_finish):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event')
        expected_packed_values['finish_time'] = NOW
        mock_finish.return_value = fake_event
        event = instance_action.InstanceActionEvent.event_finish(
            self.context, 'fake-uuid', 'fake-event', want_result=False)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.assertIsNone(event)

    @mock.patch.object(traceback, 'format_tb')
    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish_with_failure(self, mock_finish, mock_tb):
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event', 'val', 'fake-tb')
        expected_packed_values['finish_time'] = NOW

        mock_finish.return_value = fake_event
        event = test_class.event_finish_with_failure(
            self.context, 'fake-uuid', 'fake-event', 'val', 'fake-tb',
            want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(event, fake_event)

    @mock.patch.object(traceback, 'format_tb')
    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish_with_failure_legacy(self, mock_finish, mock_tb):
        # Tests that exc_tb is serialized when it's not a string type.
        mock_tb.return_value = 'fake-tb'
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event', 'val', 'fake-tb')
        expected_packed_values['finish_time'] = NOW

        mock_finish.return_value = fake_event
        fake_tb = mock.sentinel.fake_tb
        event = test_class.event_finish_with_failure(
            self.context, 'fake-uuid', 'fake-event', exc_val='val',
            exc_tb=fake_tb, want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(event, fake_event)
        mock_tb.assert_called_once_with(fake_tb)

    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish_with_failure_legacy_unicode(self, mock_finish):
        # Tests that traceback.format_tb is not called when exc_tb is unicode.
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event', 'val',
            six.text_type('fake-tb'))
        expected_packed_values['finish_time'] = NOW

        mock_finish.return_value = fake_event
        event = test_class.event_finish_with_failure(
            self.context, 'fake-uuid', 'fake-event', exc_val='val',
            exc_tb=six.text_type('fake-tb'), want_result=True)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.compare_obj(event, fake_event)

    @mock.patch.object(traceback, 'format_tb')
    @mock.patch.object(db, 'action_event_finish')
    def test_event_finish_with_failure_no_result(self, mock_finish, mock_tb):
        # Tests that traceback.format_tb is not called when exc_tb is a str
        # and want_result is False, so no event should come back.
        mock_tb.return_value = 'fake-tb'
        self.useFixture(utils_fixture.TimeFixture(NOW))
        test_class = instance_action.InstanceActionEvent
        expected_packed_values = test_class.pack_action_event_finish(
            self.context, 'fake-uuid', 'fake-event', 'val', 'fake-tb')
        expected_packed_values['finish_time'] = NOW

        mock_finish.return_value = fake_event
        event = test_class.event_finish_with_failure(
            self.context, 'fake-uuid', 'fake-event', 'val', 'fake-tb',
            want_result=False)
        mock_finish.assert_called_once_with(self.context,
                                            expected_packed_values)
        self.assertIsNone(event)
        self.assertFalse(mock_tb.called)

    @mock.patch.object(db, 'action_events_get')
    def test_get_by_action(self, mock_get):
        fake_events = [dict(fake_event, id=1234),
                       dict(fake_event, id=5678)]
        mock_get.return_value = fake_events
        obj_list = instance_action.InstanceActionEventList.get_by_action(
            self.context, 'fake-action-id')
        for index, event in enumerate(obj_list):
            self.compare_obj(event, fake_events[index])
        mock_get.assert_called_once_with(self.context, 'fake-action-id')

    @mock.patch('nova.objects.instance_action.InstanceActionEvent.'
                'pack_action_event_finish')
    @mock.patch('traceback.format_tb')
    def test_event_finish_with_failure_serialized(self, mock_format,
                                                  mock_pack):
        mock_format.return_value = 'traceback'
        mock_pack.side_effect = test.TestingException
        self.assertRaises(
            test.TestingException,
            instance_action.InstanceActionEvent.event_finish_with_failure,
            self.context, 'fake-uuid', 'fake-event',
            exc_val=mock.sentinel.exc_val,
            exc_tb=mock.sentinel.exc_tb)
        mock_pack.assert_called_once_with(self.context, 'fake-uuid',
                                          'fake-event',
                                          exc_val=str(mock.sentinel.exc_val),
                                          exc_tb='traceback')
        mock_format.assert_called_once_with(mock.sentinel.exc_tb)


class TestInstanceActionEventObject(test_objects._LocalTest,
                                    _TestInstanceActionEventObject):
    pass


class TestRemoteInstanceActionEventObject(test_objects._RemoteTest,
                                          _TestInstanceActionEventObject):
    pass

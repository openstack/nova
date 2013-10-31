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

from nova.compute import utils as compute_utils
from nova import db
from nova.objects import instance_action
from nova.openstack.common import timeutils
from nova.tests.objects import test_objects


NOW = timeutils.utcnow()
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
    def test_get_by_request_id(self):
        self.mox.StubOutWithMock(db, 'action_get_by_request_id')
        db.action_get_by_request_id(self.context, 'fake-uuid', 'fake-request'
                                    ).AndReturn(fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.get_by_request_id(
            self.context, 'fake-uuid', 'fake-request')
        self.assertEqual(fake_action['id'], action.id)

    def test_action_start(self):
        self.mox.StubOutWithMock(db, 'action_start')
        db.action_start(self.context, compute_utils.pack_action_start(
                self.context, 'fake-uuid', 'fake-action')).AndReturn(
                    fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action')
        self.assertEqual(fake_action['id'], action.id)

    def test_action_start_no_result(self):
        self.mox.StubOutWithMock(db, 'action_start')
        db.action_start(self.context, compute_utils.pack_action_start(
                self.context, 'fake-uuid', 'fake-action')).AndReturn(
                    fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action', want_result=False)
        self.assertIsNone(action)

    def test_action_finish(self):
        timeutils.set_time_override()
        self.mox.StubOutWithMock(db, 'action_finish')
        db.action_finish(self.context, compute_utils.pack_action_finish(
                self.context, 'fake-uuid')).AndReturn(fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.action_finish(
            self.context, 'fake-uuid', want_result=True)
        self.assertEqual(fake_action['id'], action.id)

    def test_action_finish_no_result(self):
        timeutils.set_time_override()
        self.mox.StubOutWithMock(db, 'action_finish')
        db.action_finish(self.context, compute_utils.pack_action_finish(
                self.context, 'fake-uuid')).AndReturn(fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.action_finish(
            self.context, 'fake-uuid', want_result=False)
        self.assertIsNone(action)

    def test_finish(self):
        timeutils.set_time_override()
        self.mox.StubOutWithMock(db, 'action_start')
        self.mox.StubOutWithMock(db, 'action_finish')
        db.action_start(self.context, compute_utils.pack_action_start(
                self.context, 'fake-uuid', 'fake-action')).AndReturn(
                    fake_action)
        db.action_finish(self.context, compute_utils.pack_action_finish(
                self.context, 'fake-uuid')).AndReturn(fake_action)
        self.mox.ReplayAll()
        action = instance_action.InstanceAction.action_start(
            self.context, 'fake-uuid', 'fake-action')
        action.finish()

    def test_get_list(self):
        timeutils.set_time_override()
        self.mox.StubOutWithMock(db, 'actions_get')
        actions = [dict(fake_action, id=1234),
                   dict(fake_action, id=5678)]
        db.actions_get(self.context, 'fake-uuid').AndReturn(actions)
        self.mox.ReplayAll()
        action_list = instance_action.InstanceActionList.get_by_instance_uuid(
            self.context, 'fake-uuid')
        self.assertEqual(2, len(action_list))
        for index, action in enumerate(action_list):
            self.assertEqual(actions[index]['id'], action.id)


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

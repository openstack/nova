# Copyright 2013 Rackspace Hosting
# All Rights Reserved.
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
import uuid

from lxml import etree
from webob import exc

from nova.api.openstack.compute.plugins.v3 import instance_actions
from nova.compute import api as compute_api
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.openstack.common import policy
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests import fake_instance_actions

FAKE_UUID = fake_instance_actions.FAKE_UUID
FAKE_REQUEST_ID = fake_instance_actions.FAKE_REQUEST_ID1


def format_action(action):
    '''Remove keys that aren't serialized.'''
    to_delete = ('id', 'finish_time', 'created_at', 'updated_at', 'deleted_at',
                 'deleted')
    for key in to_delete:
        if key in action:
            del(action[key])
    if 'start_time' in action:
        # NOTE(danms): Without WSGI above us, these will be just stringified,
        # and objects will have added a timezone, so strip that for comparison
        action['start_time'] = str(action['start_time'].replace(tzinfo=None))
    for event in action.get('events', []):
        format_event(event)
    return action


def format_event(event):
    '''Remove keys that aren't serialized.'''
    to_delete = ('id', 'created_at', 'updated_at', 'deleted_at', 'deleted',
                 'action_id')
    for key in to_delete:
        if key in event:
            del(event[key])
    if 'start_time' in event:
        # NOTE(danms): Without WSGI above us, these will be just stringified,
        # and objects will have added a timezone, so strip that for comparison
        event['start_time'] = str(event['start_time'].replace(tzinfo=None))
    if 'finish_time' in event:
        # NOTE(danms): Without WSGI above us, these will be just stringified,
        # and objects will have added a timezone, so strip that for comparison
        event['finish_time'] = str(event['finish_time'].replace(tzinfo=None))
    return event


class InstanceActionsPolicyTest(test.NoDBTestCase):
    def setUp(self):
        super(InstanceActionsPolicyTest, self).setUp()
        self.controller = instance_actions.InstanceActionsController()

    def test_list_actions_restricted_by_project(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:v3:os-instance-actions':
                               policy.parse_rule('project_id:%(project_id)s')})
        policy.set_rules(rules)

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None, use_slave=False):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequestV3.blank('/servers/12/os-instance-actions')
        self.assertRaises(exception.NotAuthorized, self.controller.index, req,
                          str(uuid.uuid4()))

    def test_get_action_restricted_by_project(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:v3:os-instance-actions':
                               policy.parse_rule('project_id:%(project_id)s')})
        policy.set_rules(rules)

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None, use_slave=False):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequestV3.blank(
                                    '/servers/12/os-instance-actions/1')
        self.assertRaises(exception.NotAuthorized, self.controller.show, req,
                          str(uuid.uuid4()), '1')


class InstanceActionsTest(test.NoDBTestCase):
    def setUp(self):
        super(InstanceActionsTest, self).setUp()
        self.controller = instance_actions.InstanceActionsController()
        self.fake_actions = copy.deepcopy(fake_instance_actions.FAKE_ACTIONS)
        self.fake_events = copy.deepcopy(fake_instance_actions.FAKE_EVENTS)

        def fake_get(self, context, instance_uuid):
            return {'uuid': instance_uuid}

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None, use_slave=False):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(compute_api.API, 'get', fake_get)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)

    def test_list_actions(self):
        def fake_get_actions(context, uuid):
            actions = []
            for act in self.fake_actions[uuid].itervalues():
                action = models.InstanceAction()
                action.update(act)
                actions.append(action)
            return actions

        self.stubs.Set(db, 'actions_get', fake_get_actions)
        req = fakes.HTTPRequestV3.blank('/servers/12/os-instance-actions')
        res_dict = self.controller.index(req, FAKE_UUID)
        for res in res_dict['instance_actions']:
            fake_action = self.fake_actions[FAKE_UUID][res['request_id']]
            self.assertEqual(format_action(fake_action),
                             format_action(res))

    def test_get_action_with_events_allowed(self):
        def fake_get_action(context, uuid, request_id):
            action = models.InstanceAction()
            action.update(self.fake_actions[uuid][request_id])
            return action

        def fake_get_events(context, action_id):
            events = []
            for evt in self.fake_events[action_id]:
                event = models.InstanceActionEvent()
                event.update(evt)
                events.append(event)
            return events

        self.stubs.Set(db, 'action_get_by_request_id', fake_get_action)
        self.stubs.Set(db, 'action_events_get', fake_get_events)
        req = fakes.HTTPRequestV3.blank(
                                '/servers/12/os-instance-actions/1',
                                use_admin_context=True)
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        self.assertEqual(format_action(fake_action),
                         format_action(res_dict['instance_action']))

    def test_get_action_with_events_not_allowed(self):
        def fake_get_action(context, uuid, request_id):
            return self.fake_actions[uuid][request_id]

        def fake_get_events(context, action_id):
            return self.fake_events[action_id]

        self.stubs.Set(db, 'action_get_by_request_id', fake_get_action)
        self.stubs.Set(db, 'action_events_get', fake_get_events)
        rules = policy.Rules({
            'compute:get': policy.parse_rule(''),
            'compute_extension:v3:os-instance-actions':
            policy.parse_rule(''),
            'compute_extension:v3:os-instance-actions:events':
            policy.parse_rule('is_admin:True')})
        policy.set_rules(rules)
        req = fakes.HTTPRequestV3.blank(
                                '/servers/12/os-instance-actions/1')
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        self.assertEqual(format_action(fake_action),
                         format_action(res_dict['instance_action']))

    def test_action_not_found(self):
        def fake_no_action(context, uuid, action_id):
            return None

        self.stubs.Set(db, 'action_get_by_request_id', fake_no_action)
        req = fakes.HTTPRequestV3.blank(
                                '/servers/12/os-instance-actions/1')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, FAKE_REQUEST_ID)

    def test_instance_not_found(self):
        def fake_get(self, context, instance_uuid):
            raise exception.InstanceNotFound(instance_id=instance_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        req = fakes.HTTPRequestV3.blank('/servers/12/os-instance-actions')
        self.assertRaises(exc.HTTPNotFound, self.controller.index, req,
                          FAKE_UUID)

    def test_instance_not_found_in_show(self):
        def fake_get(self, context, instance_uuid):
            raise exception.InstanceNotFound(instance_id=instance_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        req = fakes.HTTPRequestV3.blank('/servers/12/os-instance-actions/1')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, FAKE_REQUEST_ID)


class InstanceActionsSerializerTest(test.NoDBTestCase):
    def setUp(self):
        super(InstanceActionsSerializerTest, self).setUp()
        self.fake_actions = copy.deepcopy(fake_instance_actions.FAKE_ACTIONS)
        self.fake_events = copy.deepcopy(fake_instance_actions.FAKE_EVENTS)

    def _verify_instance_action_attachment(self, attach, tree):
        for key in attach.keys():
            if key != 'events':
                self.assertEqual(attach[key], tree.get(key),
                                 '%s did not match' % key)

    def _verify_instance_action_event_attachment(self, attach, tree):
        for key in attach.keys():
            self.assertEqual(attach[key], tree.get(key),
                             '%s did not match' % key)

    def test_instance_action_serializer(self):
        serializer = instance_actions.InstanceActionTemplate()
        action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        text = serializer.serialize({'instance_action': action})
        tree = etree.fromstring(text)

        action = format_action(action)
        self.assertEqual('instance_action', tree.tag)
        self._verify_instance_action_attachment(action, tree)
        found_events = False
        for child in tree:
            if child.tag == 'events':
                found_events = True
        self.assertFalse(found_events)

    def test_instance_action_events_serializer(self):
        serializer = instance_actions.InstanceActionTemplate()
        action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        event = self.fake_events[action['id']][0]
        action['events'] = [dict(event), dict(event)]
        text = serializer.serialize({'instance_action': action})
        tree = etree.fromstring(text)

        action = format_action(action)
        self.assertEqual('instance_action', tree.tag)
        self._verify_instance_action_attachment(action, tree)

        event = format_event(event)
        found_events = False
        for child in tree:
            if child.tag == 'events':
                found_events = True
                for key in event:
                    self.assertEqual(event[key], child.get(key))
        self.assertTrue(found_events)

    def test_instance_actions_serializer(self):
        serializer = instance_actions.InstanceActionsTemplate()
        action_list = self.fake_actions[FAKE_UUID].values()
        text = serializer.serialize({'instance_actions': action_list})
        tree = etree.fromstring(text)

        action_list = [format_action(action) for action in action_list]
        self.assertEqual('instance_actions', tree.tag)
        self.assertEqual(len(action_list), len(tree))
        for idx, child in enumerate(tree):
            self.assertEqual('instance_action', child.tag)
            request_id = child.get('request_id')
            self._verify_instance_action_attachment(
                                    self.fake_actions[FAKE_UUID][request_id],
                                    child)

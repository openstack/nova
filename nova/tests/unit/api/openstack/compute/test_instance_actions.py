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

import mock
from oslo_policy import policy as oslo_policy
import six
from webob import exc

from nova.api.openstack.compute import instance_actions as instance_actions_v21
from nova.api.openstack import wsgi as os_wsgi
from nova.compute import api as compute_api
from nova.db.sqlalchemy import models
from nova import exception
from nova import objects
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_server_actions
from nova.tests import uuidsentinel as uuids

FAKE_UUID = fake_server_actions.FAKE_UUID
FAKE_REQUEST_ID = fake_server_actions.FAKE_REQUEST_ID1
FAKE_EVENT_ID = fake_server_actions.FAKE_ACTION_ID1
FAKE_REQUEST_NOTFOUND_ID = 'req-' + uuids.req_not_found


def format_action(action, expect_traceback=True):
    '''Remove keys that aren't serialized.'''
    to_delete = ('id', 'finish_time', 'created_at', 'updated_at', 'deleted_at',
                 'deleted')
    for key in to_delete:
        if key in action:
            del(action[key])
    if 'start_time' in action:
        # NOTE(danms): Without WSGI above us, these will be just stringified
        action['start_time'] = str(action['start_time'].replace(tzinfo=None))
    for event in action.get('events', []):
        format_event(event, expect_traceback)
    return action


def format_event(event, expect_traceback=True):
    '''Remove keys that aren't serialized.'''
    to_delete = ['id', 'created_at', 'updated_at', 'deleted_at', 'deleted',
                 'action_id']
    if not expect_traceback:
        to_delete.append('traceback')
    for key in to_delete:
        if key in event:
            del(event[key])
    if 'start_time' in event:
        # NOTE(danms): Without WSGI above us, these will be just stringified
        event['start_time'] = str(event['start_time'].replace(tzinfo=None))
    if 'finish_time' in event:
        # NOTE(danms): Without WSGI above us, these will be just stringified
        event['finish_time'] = str(event['finish_time'].replace(tzinfo=None))
    return event


class InstanceActionsPolicyTestV21(test.NoDBTestCase):
    instance_actions = instance_actions_v21

    def setUp(self):
        super(InstanceActionsPolicyTestV21, self).setUp()
        self.controller = self.instance_actions.InstanceActionsController()

    def _get_http_req(self, action):
        fake_url = '/123/servers/12/%s' % action
        return fakes.HTTPRequest.blank(fake_url)

    def _get_instance_other_project(self, req):
        context = req.environ['nova.context']
        project_id = '%s_unequal' % context.project_id
        return objects.Instance(project_id=project_id)

    def _set_policy_rules(self):
        rules = {'compute:get': '',
                 'os_compute_api:os-instance-actions':
                     'project_id:%(project_id)s'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_list_actions_restricted_by_project(self, mock_instance_get):
        self._set_policy_rules()
        req = self._get_http_req('os-instance-actions')
        mock_instance_get.return_value = self._get_instance_other_project(req)
        self.assertRaises(exception.Forbidden, self.controller.index, req,
                          uuids.fake)

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_get_action_restricted_by_project(self, mock_instance_get):
        self._set_policy_rules()
        req = self._get_http_req('os-instance-actions/1')
        mock_instance_get.return_value = self._get_instance_other_project(req)
        self.assertRaises(exception.Forbidden, self.controller.show, req,
                          uuids.fake, '1')


class InstanceActionsTestV21(test.NoDBTestCase):
    instance_actions = instance_actions_v21
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION
    expect_events_non_admin = False

    def fake_get(self, context, instance_uuid, expected_attrs=None):
        return objects.Instance(uuid=instance_uuid)

    def setUp(self):
        super(InstanceActionsTestV21, self).setUp()
        self.controller = self.instance_actions.InstanceActionsController()
        self.fake_actions = copy.deepcopy(fake_server_actions.FAKE_ACTIONS)
        self.fake_events = copy.deepcopy(fake_server_actions.FAKE_EVENTS)
        self.stubs.Set(compute_api.API, 'get', self.fake_get)

    def _get_http_req(self, action, use_admin_context=False):
        fake_url = '/123/servers/12/%s' % action
        return fakes.HTTPRequest.blank(fake_url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def _set_policy_rules(self):
        rules = {'compute:get': '',
                 'os_compute_api:os-instance-actions': '',
                 'os_compute_api:os-instance-actions:events': 'is_admin:True'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

    def test_list_actions(self):
        def fake_get_actions(context, uuid, limit=None, marker=None,
                             filters=None):
            actions = []
            for act in six.itervalues(self.fake_actions[uuid]):
                action = models.InstanceAction()
                action.update(act)
                actions.append(action)
            return actions

        self.stub_out('nova.db.actions_get', fake_get_actions)
        req = self._get_http_req('os-instance-actions')
        res_dict = self.controller.index(req, FAKE_UUID)
        for res in res_dict['instanceActions']:
            fake_action = self.fake_actions[FAKE_UUID][res['request_id']]
            self.assertEqual(format_action(fake_action), format_action(res))

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

        self.stub_out('nova.db.action_get_by_request_id', fake_get_action)
        self.stub_out('nova.db.action_events_get', fake_get_events)
        req = self._get_http_req('os-instance-actions/1',
                                use_admin_context=True)
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        self.assertEqual(format_action(fake_action),
                         format_action(res_dict['instanceAction']))

    def test_get_action_with_events_not_allowed(self):
        def fake_get_action(context, uuid, request_id):
            return self.fake_actions[uuid][request_id]

        def fake_get_events(context, action_id):
            return self.fake_events[action_id]

        self.stub_out('nova.db.action_get_by_request_id', fake_get_action)
        self.stub_out('nova.db.action_events_get', fake_get_events)

        self._set_policy_rules()
        req = self._get_http_req('os-instance-actions/1')
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        if self.expect_events_non_admin:
            fake_event = fake_server_actions.FAKE_EVENTS[FAKE_EVENT_ID]
            fake_action['events'] = copy.deepcopy(fake_event)
        # By default, non-admins are not allowed to see traceback details.
        self.assertEqual(format_action(fake_action, expect_traceback=False),
                         format_action(res_dict['instanceAction'],
                                       expect_traceback=False))

    def test_action_not_found(self):
        def fake_no_action(context, uuid, action_id):
            return None

        self.stub_out('nova.db.action_get_by_request_id', fake_no_action)
        req = self._get_http_req('os-instance-actions/1')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, FAKE_REQUEST_ID)

    def test_index_instance_not_found(self):
        def fake_get(self, context, instance_uuid, expected_attrs=None):
            raise exception.InstanceNotFound(instance_id=instance_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        req = self._get_http_req('os-instance-actions')
        self.assertRaises(exc.HTTPNotFound, self.controller.index, req,
                          FAKE_UUID)

    def test_show_instance_not_found(self):
        def fake_get(self, context, instance_uuid, expected_attrs=None):
            raise exception.InstanceNotFound(instance_id=instance_uuid)
        self.stubs.Set(compute_api.API, 'get', fake_get)
        req = self._get_http_req('os-instance-actions/fake')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, 'fake')


class InstanceActionsTestV221(InstanceActionsTestV21):
    wsgi_api_version = "2.21"

    def fake_get(self, context, instance_uuid, expected_attrs=None):
        self.assertEqual('yes', context.read_deleted)
        return objects.Instance(uuid=instance_uuid)


class InstanceActionsTestV251(InstanceActionsTestV221):
    wsgi_api_version = "2.51"
    expect_events_non_admin = True


class InstanceActionsTestV258(InstanceActionsTestV251):
    wsgi_api_version = "2.58"

    @mock.patch('nova.objects.InstanceActionList.get_by_instance_uuid')
    def test_get_action_with_invalid_marker(self, mock_actions_get):
        """Tests detail paging with an invalid marker (not found)."""
        mock_actions_get.side_effect = exception.MarkerNotFound(
            marker=FAKE_REQUEST_NOTFOUND_ID)
        req = self._get_http_req('os-instance-actions?'
                                 'marker=%s' % FAKE_REQUEST_NOTFOUND_ID)
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.index, req, FAKE_UUID)

    def test_get_action_with_invalid_limit(self):
        """Tests get paging with an invalid limit."""
        req = self._get_http_req('os-instance-actions?limit=x')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)
        req = self._get_http_req('os-instance-actions?limit=-1')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_action_with_invalid_change_since(self):
        """Tests get paging with a invalid change_since."""
        req = self._get_http_req('os-instance-actions?'
                                 'changes-since=wrong_time')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Invalid input for query parameters changes-since',
                      six.text_type(ex))

    def test_get_action_with_invalid_params(self):
        """Tests get paging with a invalid change_since."""
        req = self._get_http_req('os-instance-actions?'
                                 'wrong_params=xxx')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    def test_get_action_with_multi_params(self):
        """Tests get paging with multi markers."""
        req = self._get_http_req('os-instance-actions?marker=A&marker=B')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Invalid input for query parameters marker',
                      six.text_type(ex))

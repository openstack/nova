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
import datetime

import iso8601
import mock
from oslo_policy import policy as oslo_policy
from oslo_utils.fixture import uuidsentinel as uuids
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
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_server_actions
from nova import utils


FAKE_UUID = fake_server_actions.FAKE_UUID
FAKE_REQUEST_ID = fake_server_actions.FAKE_REQUEST_ID1
FAKE_EVENT_ID = fake_server_actions.FAKE_ACTION_ID1
FAKE_REQUEST_NOTFOUND_ID = 'req-' + uuids.req_not_found


def format_action(action, expect_traceback=True, expect_host=False,
                  expect_hostId=False):
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
        format_event(event, action.get('project_id'),
                     expect_traceback=expect_traceback,
                     expect_host=expect_host, expect_hostId=expect_hostId)
    return action


def format_event(event, project_id, expect_traceback=True, expect_host=False,
                 expect_hostId=False):
    '''Remove keys that aren't serialized.'''
    to_delete = ['id', 'created_at', 'updated_at', 'deleted_at', 'deleted',
                 'action_id']
    if not expect_traceback:
        to_delete.append('traceback')
    if not expect_host:
        to_delete.append('host')
    if not expect_hostId:
        to_delete.append('hostId')
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
    expect_event_hostId = False
    expect_event_host = False

    def fake_get(self, context, instance_uuid, expected_attrs=None,
                 cell_down_support=False):
        return objects.Instance(uuid=instance_uuid)

    def setUp(self):
        super(InstanceActionsTestV21, self).setUp()
        self.controller = self.instance_actions.InstanceActionsController()
        self.fake_actions = copy.deepcopy(fake_server_actions.FAKE_ACTIONS)
        self.fake_events = copy.deepcopy(fake_server_actions.FAKE_EVENTS)
        get_patcher = mock.patch.object(compute_api.API, 'get',
                                        side_effect=self.fake_get)
        self.addCleanup(get_patcher.stop)
        self.mock_get = get_patcher.start()

    def _get_http_req(self, action, use_admin_context=False):
        fake_url = '/123/servers/12/%s' % action
        return fakes.HTTPRequest.blank(fake_url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def _get_http_req_with_version(self, action, use_admin_context=False,
                                   version="2.21"):
        fake_url = '/123/servers/12/%s' % action
        return fakes.HTTPRequest.blank(fake_url,
                                       use_admin_context=use_admin_context,
                                       version=version)

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

        self.stub_out('nova.db.api.actions_get', fake_get_actions)
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

        self.stub_out('nova.db.api.action_get_by_request_id', fake_get_action)
        self.stub_out('nova.db.api.action_events_get', fake_get_events)
        req = self._get_http_req('os-instance-actions/1',
                                use_admin_context=True)
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        self.assertEqual(format_action(fake_action,
                                       expect_host=self.expect_event_host,
                                       expect_hostId=self.expect_event_hostId),
                         format_action(res_dict['instanceAction'],
                                       expect_host=self.expect_event_host,
                                       expect_hostId=self.expect_event_hostId))

    def test_get_action_with_events_not_allowed(self):
        def fake_get_action(context, uuid, request_id):
            return self.fake_actions[uuid][request_id]

        def fake_get_events(context, action_id):
            return self.fake_events[action_id]

        self.stub_out('nova.db.api.action_get_by_request_id', fake_get_action)
        self.stub_out('nova.db.api.action_events_get', fake_get_events)

        self._set_policy_rules()
        req = self._get_http_req('os-instance-actions/1')
        res_dict = self.controller.show(req, FAKE_UUID, FAKE_REQUEST_ID)
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        if self.expect_events_non_admin:
            fake_event = fake_server_actions.FAKE_EVENTS[FAKE_EVENT_ID]
            fake_action['events'] = copy.deepcopy(fake_event)
        # By default, non-admins are not allowed to see traceback details
        # and event host.
        self.assertEqual(format_action(fake_action,
                                       expect_traceback=False,
                                       expect_host=False,
                                       expect_hostId=self.expect_event_hostId),
                         format_action(res_dict['instanceAction'],
                                       expect_traceback=False,
                                       expect_host=False,
                                       expect_hostId=self.expect_event_hostId))

    def test_action_not_found(self):
        def fake_no_action(context, uuid, action_id):
            return None

        self.stub_out('nova.db.api.action_get_by_request_id', fake_no_action)
        req = self._get_http_req('os-instance-actions/1')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, FAKE_REQUEST_ID)

    def test_index_instance_not_found(self):
        self.mock_get.side_effect = exception.InstanceNotFound(
            instance_id=FAKE_UUID)
        req = self._get_http_req('os-instance-actions')
        self.assertRaises(exc.HTTPNotFound, self.controller.index, req,
                          FAKE_UUID)
        self.mock_get.assert_called_once_with(req.environ['nova.context'],
                                              FAKE_UUID, expected_attrs=None,
                                              cell_down_support=False)

    def test_show_instance_not_found(self):
        self.mock_get.side_effect = exception.InstanceNotFound(
            instance_id=FAKE_UUID)
        req = self._get_http_req('os-instance-actions/fake')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          FAKE_UUID, 'fake')
        self.mock_get.assert_called_once_with(req.environ['nova.context'],
                                              FAKE_UUID, expected_attrs=None,
                                              cell_down_support=False)


class InstanceActionsTestV221(InstanceActionsTestV21):
    wsgi_api_version = "2.21"

    def fake_get(self, context, instance_uuid, expected_attrs=None,
                 cell_down_support=False):
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


class InstanceActionsTestV262(InstanceActionsTestV258):
    wsgi_api_version = "2.62"
    expect_event_hostId = True
    expect_event_host = True
    instance_project_id = '26cde4489f6749a08834741678df3c4a'

    def fake_get(self, context, instance_uuid, expected_attrs=None,
                 cell_down_support=False):
        return objects.Instance(uuid=instance_uuid,
                                project_id=self.instance_project_id)

    @mock.patch.object(compute_api.InstanceActionAPI, 'action_events_get')
    @mock.patch.object(compute_api.InstanceActionAPI,
                       'action_get_by_request_id')
    def test_get_action_with_events_project_id_none(self, mock_action_get,
                                                    mock_action_events):
        fake_request_id = 'req-%s' % uuids.req1

        mock_action_get.return_value = objects.InstanceAction(
            id=789,
            action='stop',
            instance_uuid=uuids.instance,
            request_id=fake_request_id,
            user_id=None,
            project_id=None,
            start_time=datetime.datetime(2019, 2, 28, 14, 28, 0, 0),
            finish_time=None,
            message='',
            created_at=None,
            updated_at=None,
            deleted_at=None,
            deleted=False)

        mock_action_events.return_value = [
            objects.InstanceActionEvent(
                id=5,
                action_id=789,
                event='compute_stop_instance',
                start_time=datetime.datetime(2019, 2, 28, 14, 28, 0, 0),
                finish_time=datetime.datetime(2019, 2, 28, 14, 30, 0, 0),
                result='Success',
                traceback='',
                created_at=None,
                updated_at=None,
                deleted_at=None,
                deleted=False,
                host='host2')]

        req = self._get_http_req('os-instance-actions/1',
                                 use_admin_context=True)
        res_dict = self.controller.show(req, uuids.instance, fake_request_id)

        # Assert that 'project_id' is null (None) in the response
        self.assertIsNone(res_dict['instanceAction']['project_id'])
        self.assertEqual('host2',
                         res_dict['instanceAction']['events'][0]['host'])
        # Assert that the 'hostId' is based on 'host' and the project ID
        # of the server
        self.assertEqual(utils.generate_hostid(
            res_dict['instanceAction']['events'][0]['host'],
            self.instance_project_id),
            res_dict['instanceAction']['events'][0]['hostId'])


class InstanceActionsTestV266(InstanceActionsTestV258):
    wsgi_api_version = "2.66"

    def test_get_action_with_invalid_changes_before(self):
        """Tests get paging with a invalid changes-before."""
        req = self._get_http_req('os-instance-actions?'
                                 'changes-before=wrong_time')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        self.assertIn('Invalid input for query parameters changes-before',
                      six.text_type(ex))

    @mock.patch('nova.compute.api.InstanceActionAPI.actions_get')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_get_action_with_changes_since_and_changes_before(
            self, mock_get_instance, mock_action_get):
        param = 'changes-since=2012-12-05T00:00:00Z&' \
                'changes-before=2012-12-05T01:00:00Z'
        req = self._get_http_req_with_version('os-instance-actions?%s' %
                                              param, use_admin_context=True,
                                              version=self.wsgi_api_version)
        instance = fake_instance.fake_instance_obj(req.environ['nova.context'])
        mock_get_instance.return_value = instance

        self.controller.index(req, FAKE_UUID)
        filters = {'changes-since': datetime.datetime(
                       2012, 12, 5, 0, 0, tzinfo=iso8601.iso8601.UTC),
                   'changes-before': datetime.datetime(
                       2012, 12, 5, 1, 0, tzinfo=iso8601.iso8601.UTC)}
        mock_action_get.assert_called_once_with(req.environ['nova.context'],
                                                instance, limit=1000,
                                                marker=None,
                                                filters=filters)

    def test_instance_actions_filters_with_distinct_changes_time_bad_request(
            self):
        changes_since = '2018-09-04T05:45:27Z'
        changes_before = '2018-09-03T05:45:27Z'
        req = self._get_http_req('os-instance-actions?'
                                 'changes-since=%s&changes-before=%s' %
                                 (changes_since, changes_before))
        ex = self.assertRaises(exc.HTTPBadRequest, self.controller.index,
                               req, FAKE_UUID)
        self.assertIn('The value of changes-since must be less than '
                      'or equal to changes-before', six.text_type(ex))

    def test_get_action_with_changes_before_old_microversion(self):
        """Tests that the changes-before query parameter is an error before
        microversion 2.66.
        """
        param = 'changes-before=2018-09-13T15:13:03Z'
        req = self._get_http_req_with_version('os-instance-actions?%s' %
                                              param, use_admin_context=True,
                                              version="2.65")
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.index, req)
        detail = 'Additional properties are not allowed'
        self.assertIn(detail, six.text_type(ex))

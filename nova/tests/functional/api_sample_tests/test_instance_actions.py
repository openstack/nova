# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.functional import api_samples_test_base
from nova.tests.unit import policy_fixture


class ServerActionsSampleJsonTest(test_servers.ServersSampleBase):

    microversion = None
    ADMIN_API = True
    sample_dir = 'os-instance-actions'

    def setUp(self):
        super(ServerActionsSampleJsonTest, self).setUp()
        # Create and stop a server
        self.uuid = self._post_server()
        self._get_response('servers/%s/action' % self.uuid, 'POST',
                           '{"os-stop": null}')
        response = self._do_get('servers/%s/os-instance-actions' % self.uuid)
        response_data = api_samples_test_base.pretty_data(response.content)
        actions = api_samples_test_base.objectify(response_data)
        self.action_stop = actions['instanceActions'][0]
        self._wait_for_state_change({'id': self.uuid}, 'SHUTOFF')
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())

    def _get_subs(self):
        return {
            'uuid': self.uuid,
            'project_id': self.action_stop['project_id']
        }

    def test_instance_action_get(self):
        req_id = self.action_stop['request_id']
        response = self._do_get('servers/%s/os-instance-actions/%s' %
                                (self.uuid, req_id))
        # Non-admins can see event details except for the "traceback" field
        # starting in the 2.51 microversion.
        if self.ADMIN_API:
            name = 'instance-action-get-resp'
        else:
            name = 'instance-action-get-non-admin-resp'
        self._verify_response(name, self._get_subs(), response, 200)

    def test_instance_actions_list(self):
        response = self._do_get('servers/%s/os-instance-actions' % self.uuid)
        self._verify_response('instance-actions-list-resp', self._get_subs(),
                              response, 200)


class ServerActionsV221SampleJsonTest(ServerActionsSampleJsonTest):
    microversion = '2.21'
    scenarios = [('v2_21', {'api_major_version': 'v2.1'})]


class ServerActionsV251AdminSampleJsonTest(ServerActionsSampleJsonTest):
    """Tests the 2.51 microversion for the os-instance-actions API.

    The 2.51 microversion allows non-admins to see instance action event
    details *except* for the traceback field.

    The tests in this class are run as an admin user so all fields will be
    displayed.
    """
    microversion = '2.51'
    scenarios = [('v2_51', {'api_major_version': 'v2.1'})]


class ServerActionsV251NonAdminSampleJsonTest(ServerActionsSampleJsonTest):
    """Tests the 2.51 microversion for the os-instance-actions API.

    The 2.51 microversion allows non-admins to see instance action event
    details *except* for the traceback field.

    The tests in this class are run as a non-admin user so all fields except
    for the ``traceback`` field will be displayed.
    """
    ADMIN_API = False
    microversion = '2.51'
    scenarios = [('v2_51', {'api_major_version': 'v2.1'})]


class ServerActionsV258SampleJsonTest(ServerActionsV251AdminSampleJsonTest):
    microversion = '2.58'
    scenarios = [('v2_58', {'api_major_version': 'v2.1'})]

    def test_instance_actions_list_with_limit(self):
        response = self._do_get('servers/%s/os-instance-actions'
                                '?limit=1' % self.uuid)
        self._verify_response('instance-actions-list-with-limit-resp',
                              self._get_subs(), response, 200)

    def test_instance_actions_list_with_marker(self):

        marker = self.action_stop['request_id']
        response = self._do_get('servers/%s/os-instance-actions'
                                '?marker=%s' % (self.uuid, marker))
        self._verify_response('instance-actions-list-with-marker-resp',
                              self._get_subs(), response, 200)

    def test_instance_actions_with_changes_since(self):
        stop_action_time = self.action_stop['start_time']
        response = self._do_get(
            'servers/%s/os-instance-actions'
            '?changes-since=%s' % (self.uuid, stop_action_time))
        self._verify_response(
            'instance-actions-list-with-changes-since',
            self._get_subs(), response, 200)


class ServerActionsV258NonAdminSampleJsonTest(ServerActionsV258SampleJsonTest):
    ADMIN_API = False


class ServerActionsV262SampleJsonTest(ServerActionsV258SampleJsonTest):
    microversion = '2.62'
    scenarios = [('v2_62', {'api_major_version': 'v2.1'})]

    def _get_subs(self):
        return {
            'uuid': self.uuid,
            'project_id': self.action_stop['project_id'],
            'event_host': r'\w+',
            'event_hostId': '[a-f0-9]+'
        }


class ServerActionsV262NonAdminSampleJsonTest(ServerActionsV262SampleJsonTest):
    ADMIN_API = False


class ServerActionsV266SampleJsonTest(ServerActionsV262SampleJsonTest):
    microversion = '2.66'
    scenarios = [('v2_66', {'api_major_version': 'v2.1'})]

    def test_instance_actions_with_changes_before(self):
        stop_action_time = self.action_stop['updated_at']
        response = self._do_get(
            'servers/%s/os-instance-actions'
            '?changes-before=%s' % (self.uuid, stop_action_time))
        self._verify_response(
            'instance-actions-list-with-changes-before',
            self._get_subs(), response, 200)


class ServerActionsV284SampleJsonTest(ServerActionsV266SampleJsonTest):
    microversion = '2.84'
    scenarios = [('2.84', {'api_major_version': 'v2.1'})]


class ServerActionsV284NonAdminSampleJsonTest(ServerActionsV284SampleJsonTest):
    ADMIN_API = False

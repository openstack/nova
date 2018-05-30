# Copyright 2011 OpenStack Foundation
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

import mock

from nova.api.openstack.compute import pause_server as \
    pause_server_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class PauseServerTestsV21(admin_only_action_common.CommonTests):
    pause_server = pause_server_v21
    controller_name = 'PauseServerController'
    _api_version = '2.1'

    def setUp(self):
        super(PauseServerTestsV21, self).setUp()
        self.controller = getattr(self.pause_server, self.controller_name)()
        self.compute_api = self.controller.compute_api
        self.stub_out('nova.api.openstack.compute.pause_server.'
                      'PauseServerController',
                      lambda *a, **kw: self.controller)

    def test_pause_unpause(self):
        self._test_actions(['_pause', '_unpause'])

    def test_actions_raise_on_not_implemented(self):
        for action in ['_pause', '_unpause']:
            self._test_not_implemented_state(action)

    def test_pause_unpause_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['_pause', '_unpause'])

    def test_pause_unpause_with_non_existed_instance_in_compute_api(self):
        self._test_actions_instance_not_found_in_compute_api(['_pause',
                                                              '_unpause'])

    def test_pause_unpause_raise_conflict_on_invalid_state(self):
        self._test_actions_raise_conflict_on_invalid_state(['_pause',
                                                            '_unpause'])

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(['_pause', '_unpause'])


class PauseServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(PauseServerPolicyEnforcementV21, self).setUp()
        self.controller = pause_server_v21.PauseServerController()
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_pause_policy_failed_with_other_project(self, get_instance_mock):
        get_instance_mock.return_value = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            project_id=self.req.environ['nova.context'].project_id)
        rule_name = "os_compute_api:os-pause-server:pause"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        # Change the project_id in request context.
        self.req.environ['nova.context'].project_id = 'other-project'
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._pause, self.req, fakes.FAKE_UUID,
            body={'pause': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_pause_overridden_policy_failed_with_other_user_in_same_project(
        self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-pause-server:pause"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._pause, self.req,
                                fakes.FAKE_UUID, body={'pause': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.compute.api.API.pause')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_pause_overridden_policy_pass_with_same_user(self,
                                                        get_instance_mock,
                                                        pause_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            user_id=self.req.environ['nova.context'].user_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-pause-server:pause"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._pause(self.req, fakes.FAKE_UUID, body={'pause': {}})
        pause_mock.assert_called_once_with(self.req.environ['nova.context'],
                                          instance)

    def test_unpause_policy_failed(self):
        rule_name = "os_compute_api:os-pause-server:unpause"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._unpause, self.req, fakes.FAKE_UUID,
            body={'unpause': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

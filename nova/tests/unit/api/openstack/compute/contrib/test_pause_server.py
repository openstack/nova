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

from nova.api.openstack.compute.contrib import admin_actions as \
    pause_server_v2
from nova.api.openstack.compute.plugins.v3 import pause_server as \
    pause_server_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class PauseServerTestsV21(admin_only_action_common.CommonTests):
    pause_server = pause_server_v21
    controller_name = 'PauseServerController'
    _api_version = '2.1'

    def setUp(self):
        super(PauseServerTestsV21, self).setUp()
        self.controller = getattr(self.pause_server, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.pause_server, self.controller_name,
                       _fake_controller)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_pause_unpause(self):
        self._test_actions(['_pause', '_unpause'])

    def test_actions_raise_on_not_implemented(self):
        for action in ['_pause', '_unpause']:
            self.mox.StubOutWithMock(self.compute_api,
                                     action.replace('_', ''))
            self._test_not_implemented_state(action)
            # Re-mock this.
            self.mox.StubOutWithMock(self.compute_api, 'get')

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


class PauseServerTestsV2(PauseServerTestsV21):
    pause_server = pause_server_v2
    controller_name = 'AdminActionsController'
    _api_version = '2'

    def test_actions_raise_on_not_implemented(self):
        pass


class PauseServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(PauseServerPolicyEnforcementV21, self).setUp()
        self.controller = pause_server_v21.PauseServerController()

    def test_pause_policy_failed(self):
        rule_name = "os_compute_api:os-pause-server:pause"
        self.policy.set_rules({rule_name: "project:non_fake"})
        req = fakes.HTTPRequest.blank('')
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._pause, req, fakes.FAKE_UUID,
            body={'pause': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_unpause_policy_failed(self):
        rule_name = "os_compute_api:os-pause-server:unpause"
        self.policy.set_rules({rule_name: "project:non_fake"})
        req = fakes.HTTPRequest.blank('')
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._unpause, req, fakes.FAKE_UUID,
            body={'unpause': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

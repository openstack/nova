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

from nova.api.openstack.compute.legacy_v2.contrib import admin_actions as \
    suspend_server_v2
from nova.api.openstack.compute import suspend_server as \
    suspend_server_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes


class SuspendServerTestsV21(admin_only_action_common.CommonTests):
    suspend_server = suspend_server_v21
    controller_name = 'SuspendServerController'
    _api_version = '2.1'

    def setUp(self):
        super(SuspendServerTestsV21, self).setUp()
        self.controller = getattr(self.suspend_server, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.suspend_server, self.controller_name,
                       _fake_controller)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_suspend_resume(self):
        self._test_actions(['_suspend', '_resume'])

    def test_suspend_resume_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['_suspend', '_resume'])

    def test_suspend_resume_raise_conflict_on_invalid_state(self):
        self._test_actions_raise_conflict_on_invalid_state(['_suspend',
                                                            '_resume'])

    def test_actions_with_locked_instance(self):
        self._test_actions_with_locked_instance(['_suspend', '_resume'])


class SuspendServerTestsV2(SuspendServerTestsV21):
    suspend_server = suspend_server_v2
    controller_name = 'AdminActionsController'
    _api_version = '2'


class SuspendServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(SuspendServerPolicyEnforcementV21, self).setUp()
        self.controller = suspend_server_v21.SuspendServerController()
        self.req = fakes.HTTPRequest.blank('')

    def test_suspend_policy_failed(self):
        rule_name = "os_compute_api:os-suspend-server:suspend"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._suspend, self.req, fakes.FAKE_UUID,
            body={'suspend': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_resume_policy_failed(self):
        rule_name = "os_compute_api:os-suspend-server:resume"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._resume, self.req, fakes.FAKE_UUID,
            body={'resume': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

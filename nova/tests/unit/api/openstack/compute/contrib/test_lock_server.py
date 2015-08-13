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

import webob

import mock

from nova.api.openstack import common
from nova.api.openstack.compute.legacy_v2.contrib import admin_actions \
        as lock_server_v2
from nova.api.openstack.compute import lock_server as lock_server_v21
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.api.openstack.compute import admin_only_action_common
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class LockServerTestsV21(admin_only_action_common.CommonTests):
    lock_server = lock_server_v21
    controller_name = 'LockServerController'
    authorization_error = exception.PolicyNotAuthorized
    _api_version = '2.1'

    def setUp(self):
        super(LockServerTestsV21, self).setUp()
        self.controller = getattr(self.lock_server, self.controller_name)()
        self.compute_api = self.controller.compute_api

        def _fake_controller(*args, **kwargs):
            return self.controller

        self.stubs.Set(self.lock_server, self.controller_name,
                       _fake_controller)
        self.mox.StubOutWithMock(self.compute_api, 'get')

    def test_lock_unlock(self):
        self._test_actions(['_lock', '_unlock'])

    def test_lock_unlock_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['_lock', '_unlock'])

    def test_unlock_not_authorized(self):
        self.mox.StubOutWithMock(self.compute_api, 'unlock')

        instance = self._stub_instance_get()

        self.compute_api.unlock(self.context, instance).AndRaise(
                exception.PolicyNotAuthorized(action='unlock'))

        self.mox.ReplayAll()
        body = {}
        self.assertRaises(self.authorization_error,
                          self.controller._unlock,
                          self.req, instance.uuid, body)


class LockServerTestsV2(LockServerTestsV21):
    lock_server = lock_server_v2
    controller_name = 'AdminActionsController'
    authorization_error = webob.exc.HTTPForbidden
    _api_version = '2'


class LockServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(LockServerPolicyEnforcementV21, self).setUp()
        self.controller = lock_server_v21.LockServerController()
        self.req = fakes.HTTPRequest.blank('')

    def test_lock_policy_failed(self):
        rule_name = "os_compute_api:os-lock-server:lock"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._lock, self.req,
                                fakes.FAKE_UUID,
                                body={'lock': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    def test_unlock_policy_failed(self):
        rule_name = "os_compute_api:os-lock-server:unlock"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._unlock, self.req,
                                fakes.FAKE_UUID,
                                body={'unlock': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch.object(common, 'get_instance')
    def test_unlock_policy_failed_with_unlock_override(self,
                                                       get_instance_mock):
        ctxt = context.RequestContext('fake', 'fake')
        instance = fake_instance.fake_instance_obj(ctxt)
        instance.locked_by = "fake"
        get_instance_mock.return_value = instance
        rule_name = ("os_compute_api:os-lock-server:"
                     "unlock:unlock_override")
        rules = {"os_compute_api:os-lock-server:unlock": "@",
                 rule_name: "project:non_fake"}
        self.policy.set_rules(rules)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._unlock,
            self.req, fakes.FAKE_UUID, body={'unlock': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

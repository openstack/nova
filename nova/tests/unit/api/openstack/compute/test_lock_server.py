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

from nova.api.openstack import common
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
        self.stub_out('nova.api.openstack.compute.lock_server.'
                      'LockServerController',
                      lambda *a, **kw: self.controller)

    def test_lock_unlock(self):
        self._test_actions(['_lock', '_unlock'])

    def test_lock_unlock_with_non_existed_instance(self):
        self._test_actions_with_non_existed_instance(['_lock', '_unlock'])

    def test_unlock_not_authorized(self):
        instance = self._stub_instance_get()

        body = {}
        with mock.patch.object(
                self.compute_api, 'unlock',
                side_effect=exception.PolicyNotAuthorized(
                    action='unlock')) as mock_unlock:
            self.assertRaises(self.authorization_error,
                              self.controller._unlock,
                              self.req, instance.uuid, body)
            mock_unlock.assert_called_once_with(self.context, instance)
        self.mock_get.assert_called_once_with(self.context, instance.uuid,
                                              expected_attrs=None)

    @mock.patch.object(common, 'get_instance')
    def test_unlock_override_not_authorized_with_non_admin_user(
            self, mock_get_instance):
        instance = fake_instance.fake_instance_obj(self.context)
        instance.locked_by = "owner"
        mock_get_instance.return_value = instance
        self.assertRaises(self.authorization_error,
                          self.controller._unlock, self.req,
                          instance.uuid,
                          {'unlock': None})

    @mock.patch.object(common, 'get_instance')
    def test_unlock_override_with_admin_user(self, mock_get_instance):
        admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        admin_ctxt = admin_req.environ['nova.context']
        instance = fake_instance.fake_instance_obj(admin_ctxt)
        instance.locked_by = "owner"
        mock_get_instance.return_value = instance
        with mock.patch.object(self.compute_api, 'unlock') as mock_unlock:
            self.controller._unlock(admin_req, instance.uuid, {'unlock': None})
            mock_unlock.assert_called_once_with(admin_ctxt, instance)


class LockServerPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(LockServerPolicyEnforcementV21, self).setUp()
        self.controller = lock_server_v21.LockServerController()
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_lock_policy_failed_with_other_project(self, get_instance_mock):
        get_instance_mock.return_value = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            project_id=self.req.environ['nova.context'].project_id)
        rule_name = "os_compute_api:os-lock-server:lock"
        self.policy.set_rules({rule_name: "project_id:%(project_id)s"})
        # Change the project_id in request context.
        self.req.environ['nova.context'].project_id = 'other-project'
        exc = self.assertRaises(
                                exception.PolicyNotAuthorized,
                                self.controller._lock, self.req,
                                fakes.FAKE_UUID,
                                body={'lock': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_lock_overridden_policy_failed_with_other_user_in_same_project(
        self, get_instance_mock):
        get_instance_mock.return_value = (
            fake_instance.fake_instance_obj(self.req.environ['nova.context']))
        rule_name = "os_compute_api:os-lock-server:lock"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        # Change the user_id in request context.
        self.req.environ['nova.context'].user_id = 'other-user'
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._lock, self.req,
                                fakes.FAKE_UUID, body={'lock': {}})
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.compute.api.API.lock')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_lock_overridden_policy_pass_with_same_user(self,
                                                        get_instance_mock,
                                                        lock_mock):
        instance = fake_instance.fake_instance_obj(
            self.req.environ['nova.context'],
            user_id=self.req.environ['nova.context'].user_id)
        get_instance_mock.return_value = instance
        rule_name = "os_compute_api:os-lock-server:lock"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._lock(self.req, fakes.FAKE_UUID, body={'lock': {}})
        lock_mock.assert_called_once_with(self.req.environ['nova.context'],
                                          instance)

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

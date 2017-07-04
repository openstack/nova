# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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
import mock
import webob

from nova.api.openstack.compute import admin_password as admin_password_v21
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


def fake_get(self, context, id, expected_attrs=None):
    return fake_instance.fake_instance_obj(
        context,
        uuid=id,
        project_id=context.project_id,
        user_id=context.user_id,
        expected_attrs=expected_attrs)


def fake_set_admin_password(self, context, instance, password=None):
    pass


class AdminPasswordTestV21(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(AdminPasswordTestV21, self).setUp()
        self.stub_out('nova.compute.api.API.set_admin_password',
                      fake_set_admin_password)
        self.stub_out('nova.compute.api.API.get', fake_get)
        self.fake_req = fakes.HTTPRequest.blank('')

    def _get_action(self):
        return admin_password_v21.AdminPasswordController().change_password

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def test_change_password(self):
        body = {'changePassword': {'adminPass': 'test'}}
        res = self._get_action()(self.fake_req, fakes.FAKE_UUID, body=body)
        self._check_status(202, res, self._get_action())

    def test_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        res = self._get_action()(self.fake_req, fakes.FAKE_UUID, body=body)
        self._check_status(202, res, self._get_action())

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=NotImplementedError())
    def test_change_password_with_non_implement(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(
                    instance_id=fakes.FAKE_UUID))
    def test_change_password_with_non_existed_instance(self, mock_get):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPNotFound,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_change_password_with_non_string_password(self):
        body = {'changePassword': {'adminPass': 1234}}
        self.assertRaises(self.validation_error,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstancePasswordSetFailed(instance="1",
                                                                reason=''))
    def test_change_password_failed(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.SetAdminPasswdNotSupported(instance="1",
                                                                 reason=''))
    def test_change_password_not_supported(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstanceAgentNotEnabled(instance="1",
                                                              reason=''))
    def test_change_password_guest_agent_disabled(self,
                                                  mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_change_password_without_admin_password(self):
        body = {'changPassword': {}}
        self.assertRaises(self.validation_error,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        self.assertRaises(self.validation_error,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_change_password_adminpass_none(self):
        body = {'changePassword': None}
        self.assertRaises(self.validation_error,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        self.assertRaises(self.validation_error,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)

    def test_server_change_password_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False, group='api')
        body = {'changePassword': {'adminPass': '1234pass'}}
        res = self._get_action()(self.fake_req, fakes.FAKE_UUID, body=body)
        self._check_status(202, res, self._get_action())

    @mock.patch('nova.compute.api.API.set_admin_password',
                side_effect=exception.InstanceInvalidState(
                    instance_uuid='fake', attr='vm_state', state='stopped',
                    method='set_admin_password'))
    def test_change_password_invalid_state(self, mock_set_admin_password):
        body = {'changePassword': {'adminPass': 'test'}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._get_action(),
                          self.fake_req, fakes.FAKE_UUID, body=body)


class AdminPasswordPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(AdminPasswordPolicyEnforcementV21, self).setUp()
        self.controller = admin_password_v21.AdminPasswordController()
        self.req = fakes.HTTPRequest.blank('')
        req_context = self.req.environ['nova.context']

        def fake_get_instance(self, context, id):
            return fake_instance.fake_instance_obj(
                req_context,
                uuid=id,
                project_id=req_context.project_id,
                user_id=req_context.user_id)

        self.stub_out(
            'nova.api.openstack.common.get_instance', fake_get_instance)

    def _common_policy_check(self, rules, rule_name, func, *arg, **kwarg):
        self.policy.set_rules(rules)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_change_password_policy_failed_with_other_project(self):
        rule_name = "os_compute_api:os-admin-password"
        rule = {rule_name: "project_id:%(project_id)s"}
        body = {'changePassword': {'adminPass': '1234pass'}}
        # Change the project_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].project_id = 'other-project'
        self._common_policy_check(
            rule, rule_name, self.controller.change_password,
            req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.set_admin_password')
    def test_change_password_overridden_policy_pass_with_same_project(
        self, password_mock):
        rule_name = "os_compute_api:os-admin-password"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'changePassword': {'adminPass': '1234pass'}}
        self.controller.change_password(self.req, fakes.FAKE_UUID, body=body)
        password_mock.assert_called_once_with(self.req.environ['nova.context'],
                                              mock.ANY, '1234pass')

    def test_change_password_overridden_policy_failed_with_other_user(self):
        rule_name = "os_compute_api:os-admin-password"
        rule = {rule_name: "user_id:%(user_id)s"}
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        body = {'changePassword': {'adminPass': '1234pass'}}
        self._common_policy_check(
            rule, rule_name, self.controller.change_password,
            req, fakes.FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.set_admin_password')
    def test_change_password_overridden_policy_pass_with_same_user(
        self, password_mock):
        rule_name = "os_compute_api:os-admin-password"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'changePassword': {'adminPass': '1234pass'}}
        self.controller.change_password(self.req, fakes.FAKE_UUID, body=body)
        password_mock.assert_called_once_with(self.req.environ['nova.context'],
                                              mock.ANY, '1234pass')

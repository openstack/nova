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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import admin_password
from nova.compute import vm_states
from nova import exception
from nova.policies import admin_password as ap_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class AdminPasswordPolicyTest(base.BasePolicyTest):
    """Test Admin Password APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AdminPasswordPolicyTest, self).setUp()
        self.controller = admin_password.AdminPasswordController()
        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id
        self.rule_name = ap_policies.BASE_POLICY_NAME
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuid, project_id=self.project_id,
                user_id=user_id, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that admin or and server owner is able to change the password
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin is not able to change the password
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

    @mock.patch('nova.compute.api.API.set_admin_password')
    def test_change_paassword_policy(self, mock_password):
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 self.rule_name,
                                 self.controller.change_password,
                                 self.req, self.instance.uuid,
                                 body={'changePassword': {
                                       'adminPass': '1234pass'}})

    def test_change_password_overridden_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        body = {'changePassword': {'adminPass': '1234pass'}}
        self.policy.set_rules({self.rule_name: "user_id:%(user_id)s"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller.change_password,
            req, fakes.FAKE_UUID, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % self.rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.set_admin_password')
    def test_change_password_overridden_policy_pass_with_same_user(
        self, password_mock):
        self.policy.set_rules({self.rule_name: "user_id:%(user_id)s"})
        body = {'changePassword': {'adminPass': '1234pass'}}
        self.controller.change_password(self.req, fakes.FAKE_UUID, body=body)
        password_mock.assert_called_once_with(self.req.environ['nova.context'],
                                              mock.ANY, '1234pass')


class AdminPasswordScopeTypePolicyTest(AdminPasswordPolicyTest):
    """Test Admin Password APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AdminPasswordScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class AdminPasswordNoLegacyPolicyTest(AdminPasswordPolicyTest):
    """Test Admin Password APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(AdminPasswordNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system or projct admin or owner is able to change
        # the password.
        self.admin_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system and non-admin/owner is not able to change the
        # password.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_reader_context,
            self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]

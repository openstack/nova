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

from nova.api.openstack.compute import suspend_server
from nova.compute import vm_states
from nova import exception
from nova.policies import suspend_server as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class SuspendServerPolicyTest(base.BasePolicyTest):
    """Test Suspend Server APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SuspendServerPolicyTest, self).setUp()
        self.controller = suspend_server.SuspendServerController()
        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                user_id=user_id, vm_state=vm_states.ACTIVE)
        self.mock_get.return_value = self.instance

        # Check that admin or and server owner is able to suspend/resume
        # the server
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to suspend/resume
        # the server
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

    @mock.patch('nova.compute.api.API.suspend')
    def test_suspend_server_policy(self, mock_suspend):
        rule_name = policies.POLICY_ROOT % 'suspend'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._suspend,
                                 self.req, self.instance.uuid,
                                 body={'suspend': {}})

    @mock.patch('nova.compute.api.API.resume')
    def test_resume_server_policy(self, mock_resume):
        rule_name = policies.POLICY_ROOT % 'resume'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._resume,
                                 self.req, self.instance.uuid,
                                 body={'resume': {}})

    def test_suspend_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.POLICY_ROOT % 'suspend'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._suspend,
            req, self.instance.uuid, body={'suspend': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.suspend')
    def test_suspend_server_overridden_policy_pass_with_same_user(
        self, mock_suspend):
        rule_name = policies.POLICY_ROOT % 'suspend'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._suspend(self.req,
                                 self.instance.uuid,
                                 body={'suspend': {}})


class SuspendServerScopeTypePolicyTest(SuspendServerPolicyTest):
    """Test Suspend Server APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SuspendServerScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class SuspendServerNoLegacyPolicyTest(SuspendServerScopeTypePolicyTest):
    """Test Suspend Server APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(SuspendServerNoLegacyPolicyTest, self).setUp()
        # Check that system admin or and server owner is able to
        # suspend/resume the server.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system/admin/owner is not able to suspend/resume
        # the server.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.other_project_member_context, self.project_reader_context,
            self.project_foo_context
        ]

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

import functools

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import lock_server
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova.policies import base as base_policy
from nova.policies import lock_server as ls_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base

CONF = nova.conf.CONF


class LockServerPolicyTest(base.BasePolicyTest):
    """Test Lock server APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(LockServerPolicyTest, self).setUp()
        self.controller = lock_server.LockServerController()
        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuid, project_id=self.project_id,
                user_id=user_id, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance

        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to lock,
        # unlock the server.
        self.project_action_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]

        # By default, legacy rule are enable and scope check is disabled.
        # system admin, legacy admin, and project admin is able to override
        # unlock, regardless who locked the server.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.API.lock')
    def test_lock_server_policy(self, mock_lock):
        rule_name = ls_policies.POLICY_ROOT % 'lock'
        self.common_policy_auth(self.project_action_authorized_contexts,
                                rule_name,
                                self.controller._lock,
                                self.req, self.instance.uuid,
                                body={'lock': {}})

    @mock.patch('nova.compute.api.API.unlock')
    def test_unlock_server_policy(self, mock_unlock):
        rule_name = ls_policies.POLICY_ROOT % 'unlock'
        self.common_policy_auth(self.project_action_authorized_contexts,
                                rule_name,
                                self.controller._unlock,
                                self.req, self.instance.uuid,
                                body={'unlock': {}})

    @mock.patch('nova.compute.api.API.unlock')
    @mock.patch('nova.compute.api.API.is_expected_locked_by')
    def test_unlock_override_server_policy(self, mock_expected, mock_unlock):
        mock_expected.return_value = False
        rule = ls_policies.POLICY_ROOT % 'unlock'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = ls_policies.POLICY_ROOT % 'unlock:unlock_override'
        if not CONF.oslo_policy.enforce_scope:
            check_rule = rule_name
        else:
            check_rule = functools.partial(base.rule_if_system,
                rule, rule_name)
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                check_rule,
                                self.controller._unlock,
                                self.req, self.instance.uuid,
                                body={'unlock': {}})

    def test_lock_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = ls_policies.POLICY_ROOT % 'lock'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._lock,
            req, fakes.FAKE_UUID, body={'lock': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.lock')
    def test_lock_sevrer_overridden_policy_pass_with_same_user(
        self, mock_lock):
        rule_name = ls_policies.POLICY_ROOT % 'lock'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._lock(self.req,
                              fakes.FAKE_UUID,
                              body={'lock': {}})


class LockServerNoLegacyNoScopePolicyTest(LockServerPolicyTest):
    """Test lock/unlock server APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only.

    """

    without_deprecated_rules = True

    def setUp(self):
        super(LockServerNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, only project admin or member will be
        # able to lock/unlock the server and only project admin can
        # override the unlock.
        self.project_action_authorized_contexts = [
            self.project_admin_context, self.project_member_context]
        self.project_admin_authorized_contexts = [self.project_admin_context]


class LockServerScopeTypePolicyTest(LockServerPolicyTest):
    """Test Lock Server APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(LockServerScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # Scope enable will not allow system admin to lock/unlock the server.
        self.project_action_authorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]


class LockServerScopeTypeNoLegacyPolicyTest(LockServerScopeTypePolicyTest):
    """Test Lock Server APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(LockServerScopeTypeNoLegacyPolicyTest, self).setUp()
        # With scope enable and no legacy rule, only project admin/member
        # will be able to lock/unlock the server.
        self.project_action_authorized_contexts = [
            self.project_admin_context, self.project_member_context]
        self.project_admin_authorized_contexts = [self.project_admin_context]


class LockServerOverridePolicyTest(LockServerScopeTypeNoLegacyPolicyTest):
    """Test Lock Server APIs policies with system and project scoped
    but default to system roles only are allowed for project roles
    if override by operators. This test is with system scope enable
    and no more deprecated rules.
    """

    def setUp(self):
        super(LockServerOverridePolicyTest, self).setUp()
        # We are overriding the 'unlock:unlock_override' policy
        # to PROJECT_MEMBER so testing it with both admin as well
        # as project member as allowed context.
        self.project_admin_authorized_contexts = [
            self.project_admin_context, self.project_member_context]

    def test_unlock_override_server_policy(self):
        rule = ls_policies.POLICY_ROOT % 'unlock:unlock_override'
        self.policy.set_rules({
        # make unlock allowed for everyone so that we can check unlock
        # override policy.
        ls_policies.POLICY_ROOT % 'unlock': "@",
        rule: base_policy.PROJECT_MEMBER}, overwrite=False)
        super(LockServerOverridePolicyTest,
              self).test_unlock_override_server_policy()

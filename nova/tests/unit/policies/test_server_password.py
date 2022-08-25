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

from unittest import mock

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import server_password
from nova.policies import base as base_policy
from nova.policies import server_password as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerPasswordPolicyTest(base.BasePolicyTest):
    """Test Server Password APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerPasswordPolicyTest, self).setUp()
        self.controller = server_password.ServerPasswordController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                system_metadata={}, expected_attrs=['system_metadata'])
        self.mock_get.return_value = self.instance
        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to delete,
        # the server Password.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # and they can get their own server password.
        self.project_reader_authorized_contexts = (
            self.project_member_authorized_contexts)

    @mock.patch('nova.api.metadata.password.extract_password')
    def test_index_server_password_policy(self, mock_pass):
        rule_name = policies.BASE_POLICY_NAME % 'show'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req, self.instance.uuid)

    @mock.patch('nova.api.metadata.password.convert_password')
    def test_clear_server_password_policy(self, mock_pass):
        rule_name = policies.BASE_POLICY_NAME % 'clear'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.clear,
                                self.req, self.instance.uuid)


class ServerPasswordNoLegacyNoScopePolicyTest(ServerPasswordPolicyTest):
    """Test Server Password APIs policies with no legacy deprecated rules
    and no scope checks.

    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.BASE_POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.BASE_POLICY_NAME % 'clear':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(ServerPasswordNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, legacy admin loose power.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_no_scope_no_legacy)


class ServerPasswordScopeTypePolicyTest(ServerPasswordPolicyTest):
    """Test Server Password APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerPasswordScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With Scope enable, system users no longer allowed.
        self.project_member_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)
        self.project_reader_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)


class ServerPasswordScopeTypeNoLegacyPolicyTest(
        ServerPasswordScopeTypePolicyTest):
    """Test Server Password APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.BASE_POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.BASE_POLICY_NAME % 'clear':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(ServerPasswordScopeTypeNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enable, only project admin, member,
        # and reader will be able to allowed operation on server password.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_scope_no_legacy)

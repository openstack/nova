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

        # Check that admin or and server owner is able to
        # delete the server password.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to delete
        # the server password.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that admin or and server owner is able to get
        # the server password.
        self.reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to get
        # the server password.
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

    @mock.patch('nova.api.metadata.password.extract_password')
    def test_index_server_password_policy(self, mock_pass):
        rule_name = policies.BASE_POLICY_NAME % 'show'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req, self.instance.uuid)

    @mock.patch('nova.api.metadata.password.convert_password')
    def test_clear_server_password_policy(self, mock_pass):
        rule_name = policies.BASE_POLICY_NAME % 'clear'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.clear,
                                 self.req, self.instance.uuid)


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


class ServerPasswordNoLegacyPolicyTest(ServerPasswordScopeTypePolicyTest):
    """Test Server Password APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.BASE_POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        policies.BASE_POLICY_NAME % 'clear':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN}

    def setUp(self):
        super(ServerPasswordNoLegacyPolicyTest, self).setUp()

        # Check that system or projct admin or owner is able to clear
        # server password.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system and non-admin/owner is not able to clear
        # server password.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.project_reader_context,
            self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context]

        # Check that system reader or projct owner is able to get
        # server password.
        self.reader_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context,
        ]

        # Check that non-system reader nd non-admin/owner is not able to get
        # server password.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

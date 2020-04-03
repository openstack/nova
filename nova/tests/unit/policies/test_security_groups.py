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

from nova.api.openstack.compute import security_groups
from nova.compute import vm_states
from nova.policies import base as base_policy
from nova.policies import security_groups as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class SecurityGroupsPolicyTest(base.BasePolicyTest):
    """Test Security Groups APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SecurityGroupsPolicyTest, self).setUp()
        self.controller = security_groups.ServerSecurityGroupController()
        self.action_ctr = security_groups.SecurityGroupActionController()
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

        # Check that admin or and server owner is able to operate
        # server security groups.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to operate
        # server security groups.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

        self.reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context, self.project_foo_context
        ]

        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

    @mock.patch('nova.network.security_group_api.get_instance_security_groups')
    def test_get_security_groups_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'list'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req, self.instance.uuid)

    @mock.patch('nova.network.security_group_api.add_to_instance')
    def test_add_security_groups_policy(self, mock_add):
        rule_name = policies.POLICY_NAME % 'add'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.action_ctr._addSecurityGroup,
                                 self.req, self.instance.uuid,
                                 body={'addSecurityGroup':
                                       {'name': 'fake'}})

    @mock.patch('nova.network.security_group_api.remove_from_instance')
    def test_remove_security_groups_policy(self, mock_remove):
        rule_name = policies.POLICY_NAME % 'remove'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.action_ctr._removeSecurityGroup,
                                 self.req, self.instance.uuid,
                                 body={'removeSecurityGroup':
                                       {'name': 'fake'}})


class SecurityGroupsScopeTypePolicyTest(SecurityGroupsPolicyTest):
    """Test Security Groups APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SecurityGroupsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class SecurityGroupsNoLegacyPolicyTest(SecurityGroupsScopeTypePolicyTest):
    """Test Security Groups APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        policies.POLICY_NAME % 'add':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        policies.POLICY_NAME % 'remove':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN}

    def setUp(self):
        super(SecurityGroupsNoLegacyPolicyTest, self).setUp()

        # Check that system or projct admin or owner is able to operate
        # server security groups.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system and non-admin/owner is not able to operate
        # server security groups.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.project_reader_context,
            self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context]

        # Check that system reader or projct is able to get
        # server security groups.
        self.reader_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context,
        ]

        # Check that non-system reader nd non-admin/owner is not able to get
        # server security groups.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

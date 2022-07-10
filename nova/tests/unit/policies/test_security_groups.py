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
from oslo_utils import timeutils

from nova.api.openstack.compute import security_groups
from nova.compute import vm_states
from nova.policies import base as base_policy
from nova.policies import security_groups as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerSecurityGroupsPolicyTest(base.BasePolicyTest):
    """Test Server Security Groups APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerSecurityGroupsPolicyTest, self).setUp()
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

        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to operate
        # server security groups.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # With legacy rule, any admin or project role is able to get their
        # server SG.
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
        ]

    @mock.patch('nova.network.security_group_api.get_instance_security_groups')
    def test_get_security_groups_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'list'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req, self.instance.uuid)

    @mock.patch('nova.network.security_group_api.add_to_instance')
    def test_add_security_groups_policy(self, mock_add):
        rule_name = policies.POLICY_NAME % 'add'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.action_ctr._addSecurityGroup,
                                self.req, self.instance.uuid,
                                body={'addSecurityGroup':
                                      {'name': 'fake'}})

    @mock.patch('nova.network.security_group_api.remove_from_instance')
    def test_remove_security_groups_policy(self, mock_remove):
        rule_name = policies.POLICY_NAME % 'remove'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.action_ctr._removeSecurityGroup,
                                self.req, self.instance.uuid,
                                body={'removeSecurityGroup':
                                      {'name': 'fake'}})


class ServerSecurityGroupsNoLegacyNoScopePolicyTest(
        ServerSecurityGroupsPolicyTest):
    """Test Server Security Groups server APIs policies with no legacy
    deprecated rules and no scope checks.

    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'add':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'remove':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(ServerSecurityGroupsNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, only project admin or member will be
        # able to add/remove SG to server and reader to get SG.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_no_scope_no_legacy)


class SecurityGroupsPolicyTest(base.BasePolicyTest):
    """Test Security Groups APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SecurityGroupsPolicyTest, self).setUp()
        self.controller = security_groups.SecurityGroupController()
        self.rule_ctr = security_groups.SecurityGroupRulesController()
        self.req = fakes.HTTPRequest.blank('')

        # With legacy and scope disabled, everyone is able to perform crud
        # operation on security groups.
        # NOTE(gmann): Nova cannot verify the security groups owner during
        # nova policy enforcement so will be passing context's project_id
        # as target to policy and always pass. If requester is not admin
        # or owner of security groups then neutron will be returning the
        # appropriate error.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

    @mock.patch('nova.network.security_group_api.list')
    def test_list_security_groups_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'get'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req)

    @mock.patch('nova.network.security_group_api.get')
    def test_show_security_groups_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'show'
        self.common_policy_auth(self.project_reader_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, uuids.fake_id)

    @mock.patch('nova.network.security_group_api.get')
    @mock.patch('nova.network.security_group_api.update_security_group')
    def test_update_security_groups_policy(self, mock_update, mock_get):
        rule_name = policies.POLICY_NAME % 'update'
        body = {'security_group': {
            'name': 'test',
            'description': 'test-desc'}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.update,
                                self.req, uuids.fake_id, body=body)

    @mock.patch('nova.network.security_group_api.create_security_group')
    def test_create_security_groups_policy(self, mock_create):
        rule_name = policies.POLICY_NAME % 'create'
        body = {'security_group': {
            'name': 'test',
            'description': 'test-desc'}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.network.security_group_api.get')
    @mock.patch('nova.network.security_group_api.destroy')
    def test_delete_security_groups_policy(self, mock_destroy, mock_get):
        rule_name = policies.POLICY_NAME % 'delete'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                self.req, uuids.fake_id)

    @mock.patch('nova.network.security_group_api.get')
    @mock.patch('nova.network.security_group_api.create_security_group_rule')
    def test_create_security_group_rules_policy(self, mock_create, mock_get):
        rule_name = policies.POLICY_NAME % 'rule:create'
        body = {'security_group_rule': {
            'ip_protocol': 'test', 'group_id': uuids.fake_id,
            'parent_group_id': uuids.fake_id,
            'from_port': 22}}
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.rule_ctr.create,
                                self.req, body=body)

    @mock.patch('nova.network.security_group_api.get_rule')
    @mock.patch('nova.network.security_group_api.get')
    @mock.patch('nova.network.security_group_api.remove_rules')
    def test_delete_security_group_rules_policy(self, mock_remove, mock_get,
            mock_rules):
        rule_name = policies.POLICY_NAME % 'rule:delete'
        self.common_policy_auth(self.project_member_authorized_contexts,
                                rule_name,
                                self.rule_ctr.delete,
                                self.req, uuids.fake_id)


class SecurityGroupsNoLegacyNoScopePolicyTest(
        SecurityGroupsPolicyTest):
    """Test Security Groups APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'get':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'update':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
            policies.POLICY_NAME % 'rule:create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
            policies.POLICY_NAME % 'rule:delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(SecurityGroupsNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy, project other roles like foo will not be able
        # to operate on SG.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context
        ]


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
        # With scope enabled, system users will not be able to
        # operate on SG.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
            self.other_project_member_context
        ]


class ServerSecurityGroupsScopeTypePolicyTest(ServerSecurityGroupsPolicyTest):
    """Test Server Security Groups APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerSecurityGroupsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # Scope enable will not allow system users.
        self.project_member_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)
        self.project_reader_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)


class ServerSecurityGroupsScopeTypeNoLegacyPolicyTest(
    ServerSecurityGroupsScopeTypePolicyTest):
    """Test Security Groups APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'add':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'remove':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(ServerSecurityGroupsScopeTypeNoLegacyPolicyTest, self).setUp()
        # With scope enable and no legacy rule, only project admin/member
        # will be able to add/remove the SG to their server and reader
        # will get SG of server.
        self.project_member_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)
        self.project_reader_authorized_contexts = (
            self.project_reader_or_admin_with_scope_no_legacy)


class SecurityGroupsNoLegacyPolicyTest(SecurityGroupsScopeTypePolicyTest):
    """Test Security Groups APIs policies with system scope enabled,
    and no more deprecated.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'get':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_ADMIN,
        policies.POLICY_NAME % 'create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'update':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
        policies.POLICY_NAME % 'delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
            policies.POLICY_NAME % 'rule:create':
            base_policy.PROJECT_MEMBER_OR_ADMIN,
            policies.POLICY_NAME % 'rule:delete':
            base_policy.PROJECT_MEMBER_OR_ADMIN}

    def setUp(self):
        super(SecurityGroupsNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enabled, system users and project
        # other roles like foo will not be able to operate SG.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context,
            self.other_project_member_context
        ]
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_reader_context,
            self.other_project_member_context
        ]

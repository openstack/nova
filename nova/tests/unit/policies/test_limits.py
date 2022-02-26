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

import mock

from nova.api.openstack.compute import limits
import nova.conf
from nova.policies import base as base_policy
from nova.policies import limits as limits_policies
from nova import quota
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base

CONF = nova.conf.CONF


class LimitsPolicyTest(base.BasePolicyTest):
    """Test Limits APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(LimitsPolicyTest, self).setUp()
        self.controller = limits.LimitsController()
        self.req = fakes.HTTPRequest.blank('')

        self.absolute_limits = {
            'ram': 512,
            'instances': 5,
            'cores': 21,
            'key_pairs': 10,
            'floating_ips': 10,
            'security_groups': 10,
            'security_group_rules': 20,
        }

        def stub_get_project_quotas(context, project_id, usages=True):
            return {k: dict(limit=v, in_use=v // 2)
                    for k, v in self.absolute_limits.items()}

        mock_get_project_quotas = mock.patch.object(
            quota.QUOTAS,
            "get_project_quotas",
            side_effect = stub_get_project_quotas)
        mock_get_project_quotas.start()

        # Check that everyone is able to get their limits
        self.everyone_authorized_contexts = self.all_contexts

        # With legacy rule, any admin is able to get other projects limit.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    def test_get_limits_policy(self):
        rule_name = limits_policies.BASE_POLICY_NAME
        self.common_policy_auth(self.everyone_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    def test_get_other_limits_policy(self):
        rule = limits_policies.BASE_POLICY_NAME
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('/?tenant_id=faketenant')
        rule_name = limits_policies.OTHER_PROJECT_LIMIT_POLICY_NAME
        if not CONF.oslo_policy.enforce_scope:
            check_rule = rule_name
        else:
            check_rule = functools.partial(base.rule_if_system,
                rule, rule_name)
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                check_rule, self.controller.index,
                                req)


class LimitsNoLegacyNoScopeTest(LimitsPolicyTest):
    """Test Flavor Access API policies with deprecated rules
    disabled, but scope checking still disabled.
    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        limits_policies.OTHER_PROJECT_LIMIT_POLICY_NAME:
            base_policy.PROJECT_ADMIN}

    def setUp(self):
        super(LimitsNoLegacyNoScopeTest, self).setUp()

        # Even with no legacy rule, any admin can get other project
        # limits.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]


class LimitsScopeTypePolicyTest(LimitsPolicyTest):
    """Test Limits APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(LimitsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With Scope enable, system users no longer allowed.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_member_context,
            self.project_foo_context, self.other_project_reader_context
        ]


class LimitsScopeTypeNoLegacyPolicyTest(LimitsScopeTypePolicyTest):
    """Test Limits APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        limits_policies.OTHER_PROJECT_LIMIT_POLICY_NAME:
            base_policy.PROJECT_ADMIN}

    def setUp(self):
        super(LimitsScopeTypeNoLegacyPolicyTest, self).setUp()
        # With no legacy and scope enable, only project level admin
        # will get other projects limit.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_member_context,
            self.project_foo_context, self.other_project_reader_context
        ]

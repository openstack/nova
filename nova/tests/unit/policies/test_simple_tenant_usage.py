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

from nova.api.openstack.compute import simple_tenant_usage
from nova.policies import simple_tenant_usage as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class SimpleTenantUsagePolicyTest(base.BasePolicyTest):
    """Test Simple Tenant Usage APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SimpleTenantUsagePolicyTest, self).setUp()
        self.controller = simple_tenant_usage.SimpleTenantUsageController()
        self.req = fakes.HTTPRequest.blank('')
        self.controller._get_instances_all_cells = mock.MagicMock()

        # Check that reader(legacy admin) or and owner is able to get
        # the tenant usage statistics for a specific tenant.
        self.reader_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context]
        # Check that non-reader(legacy non-admin) or owner is not able to get
        # the tenant usage statistics for a specific tenant.
        self.reader_or_owner_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that reader is able to get the tenant usage statistics.
        self.reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-reader is not able to get the tenant usage statistics.
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context,
            self.other_project_reader_context
        ]

    def test_index_simple_tenant_usage_policy(self):
        rule_name = policies.POLICY_ROOT % 'list'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req)

    def test_show_simple_tenant_usage_policy(self):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_check(self.reader_or_owner_authorized_contexts,
                                 self.reader_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.show,
                                 self.req, self.project_id)


class SimpleTenantUsageScopeTypePolicyTest(SimpleTenantUsagePolicyTest):
    """Test Simple Tenant Usage APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(SimpleTenantUsageScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system reader is able to get the tenant usage statistics.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system/reader is not able to get the tenant usage
        # statistics.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context,
            self.other_project_reader_context
        ]


class SimpleTenantUsageNoLegacyPolicyTest(
        SimpleTenantUsageScopeTypePolicyTest):
    """Test Simple Tenant Usage APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(SimpleTenantUsageNoLegacyPolicyTest, self).setUp()
        # Check that system reader or owner is able to get
        # the tenant usage statistics for a specific tenant.
        self.reader_or_owner_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context]
        # Check that non-system reader/owner is not able to get
        # the tenant usage statistics for a specific tenant.
        self.reader_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.other_project_member_context,
            self.project_foo_context, self.other_project_reader_context
        ]

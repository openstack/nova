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

from nova.api.openstack.compute import flavor_access
from nova.policies import base as base_policy
from nova.policies import flavor_access as fa_policy
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
from nova.tests.unit.policies import base


class FlavorAccessPolicyTest(base.BasePolicyTest):
    """Test Flavor Access APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorAccessPolicyTest, self).setUp()
        self.controller = flavor_access.FlavorActionController()
        self.controller_index = flavor_access.FlavorAccessController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_flavor')).mock
        uuid = uuids.fake_id
        self.flavor = fake_flavor.fake_flavor_obj(
                self.project_member_context,
                id=1, uuid=uuid, project_id=self.project_id,
                is_public=False)
        self.mock_get.return_value = self.flavor
        self.stub_out('nova.api.openstack.identity.verify_project_id',
                      lambda ctx, project_id: True)
        self.stub_out('nova.objects.flavor._get_projects_from_db',
                lambda context, flavorid: [])

        # With legacy rule and no scope checks, all admin is able to
        # add/remove flavor access to a tenant.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

        # With legacy rule, anyone can access flavor access info.
        self.admin_index_authorized_contexts = self.all_contexts

    def test_list_flavor_access_policy(self):
        rule_name = fa_policy.BASE_POLICY_NAME
        self.common_policy_auth(self.admin_index_authorized_contexts,
                                rule_name, self.controller_index.index,
                                self.req, '1')

    @mock.patch('nova.objects.Flavor.add_access')
    def test_add_tenant_access_policy(self, mock_add):
        rule_name = fa_policy.POLICY_ROOT % "add_tenant_access"
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name,
                                self.controller._add_tenant_access,
                                self.req, '1',
                                body={'addTenantAccess': {'tenant': 't1'}})

    @mock.patch('nova.objects.Flavor.remove_access')
    def test_remove_tenant_access_policy(self, mock_remove):
        rule_name = fa_policy.POLICY_ROOT % "remove_tenant_access"
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name,
                                self.controller._remove_tenant_access,
                                self.req, '1',
                                body={'removeTenantAccess': {'tenant': 't1'}})


class FlavorAccessNoLegacyNoScopeTest(FlavorAccessPolicyTest):
    """Test Flavor Access API policies with deprecated rules
    disabled, but scope checking still disabled.
    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        fa_policy.POLICY_ROOT % "add_tenant_access":
            base_policy.ADMIN,
        fa_policy.POLICY_ROOT % "remove_tenant_access":
            base_policy.ADMIN,
        fa_policy.BASE_POLICY_NAME:
            base_policy.ADMIN}

    def setUp(self):
        super(FlavorAccessNoLegacyNoScopeTest, self).setUp()

        # with no legacy rule means all admin is able to list access info.
        self.admin_index_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]


class FlavorAccessScopeTypePolicyTest(FlavorAccessPolicyTest):
    """Test Flavor Access APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorAccessScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Scope checks remove project users power.
        self.admin_authorized_contexts = [
            self.system_admin_context]
        self.admin_index_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context]


class FlavorAccessScopeTypeNoLegacyPolicyTest(FlavorAccessScopeTypePolicyTest):
    """Test FlavorAccess APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        fa_policy.POLICY_ROOT % "add_tenant_access":
            base_policy.ADMIN,
        fa_policy.POLICY_ROOT % "remove_tenant_access":
            base_policy.ADMIN,
        fa_policy.BASE_POLICY_NAME:
            base_policy.ADMIN}

    def setUp(self):
        super(FlavorAccessScopeTypeNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        self.admin_index_authorized_contexts = [
            self.system_admin_context]

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

from nova.api.openstack.compute import hypervisors
from nova.policies import base as base_policy
from nova.policies import hypervisors as hv_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class HypervisorsPolicyTest(base.BasePolicyTest):
    """Test os-hypervisors APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(HypervisorsPolicyTest, self).setUp()
        self.controller = hypervisors.HypervisorsController()
        self.req = fakes.HTTPRequest.blank('')
        self.controller._get_compute_nodes_by_name_pattern = mock.MagicMock()
        self.controller.host_api.compute_node_get_all = mock.MagicMock()
        self.controller.host_api.service_get_by_compute_host = mock.MagicMock()
        self.controller.host_api.compute_node_get = mock.MagicMock()

        # With legacy rule and scope check disabled by default, system admin,
        # legacy admin, and project admin will be able to perform hypervisors
        # Operations.
        self.system_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    def test_list_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'list'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    def test_list_details_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'list-detail'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.detail,
                                self.req)

    def test_show_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'show'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.get_host_uptime')
    def test_uptime_hypervisors_policy(self, mock_uptime):
        rule_name = hv_policies.BASE_POLICY_NAME % 'uptime'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.uptime,
                                self.req, 11111)

    def test_search_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'search'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.search,
                                self.req, 11111)

    def test_servers_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'servers'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.servers,
                                self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.compute_node_statistics')
    def test_statistics_hypervisors_policy(self, mock_statistics):
        rule_name = hv_policies.BASE_POLICY_NAME % 'statistics'
        self.common_policy_auth(self.system_admin_authorized_contexts,
                                rule_name, self.controller.statistics,
                                self.req)


class HypervisorsNoLegacyNoScopePolicyTest(HypervisorsPolicyTest):
    """Test Hypervisors APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only. In this case
    system admin, legacy admin, and project admin will be able to perform
    Hypervisors Operations. Legacy admin will be allowed as policy is just
    admin if no scope checks.
    """

    without_deprecated_rules = True


class HypervisorsScopeTypePolicyTest(HypervisorsPolicyTest):
    """Test os-hypervisors APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(HypervisorsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope checks enable, only system admin is able to perform
        # hypervisors Operations.
        self.system_admin_authorized_contexts = [self.system_admin_context]


class HypervisorsScopeTypeNoLegacyPolicyTest(HypervisorsScopeTypePolicyTest):
    """Test Hypervisors APIs policies with no legacy deprecated rules
    and scope checks enabled which means scope + new defaults so
    only system admin is able to perform hypervisors Operations.
    """

    without_deprecated_rules = True

    rules_without_deprecation = {
        hv_policies.BASE_POLICY_NAME % 'list':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'list-detail':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'show':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'statistics':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'uptime':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'search':
            base_policy.ADMIN,
        hv_policies.BASE_POLICY_NAME % 'servers':
            base_policy.ADMIN,
    }

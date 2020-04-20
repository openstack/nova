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

        # Check that system scoped admin, member and reader are able to
        # perform operations on hypervisors.
        # NOTE(gmann): Until old default rule which is admin_api is
        # deprecated and not removed, project admin and legacy admin
        # will be able to get hypervisors. This make sure that existing
        # tokens will keep working even we have changed this policy defaults
        # to reader role.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-system-reader are not able to perform operations
        # on hypervisors
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context]

    def test_list_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'list'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req)

    def test_list_details_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'list-detail'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.detail,
                                 self.req)

    def test_show_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'show'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.get_host_uptime')
    def test_uptime_hypervisors_policy(self, mock_uptime):
        rule_name = hv_policies.BASE_POLICY_NAME % 'uptime'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.uptime,
                                 self.req, 11111)

    def test_search_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'search'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.search,
                                 self.req, 11111)

    def test_servers_hypervisors_policy(self):
        rule_name = hv_policies.BASE_POLICY_NAME % 'servers'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.servers,
                                 self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.compute_node_statistics')
    def test_statistics_hypervisors_policy(self, mock_statistics):
        rule_name = hv_policies.BASE_POLICY_NAME % 'statistics'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.statistics,
                                 self.req)


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

        # Check that system reader is able to perform operations
        # on hypervisors.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system-reader is not able to perform operations
        # on hypervisors.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]


class HypervisorsNoLegacyPolicyTest(HypervisorsScopeTypePolicyTest):
    """Test Hypervisors APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        hv_policies.BASE_POLICY_NAME % 'list':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'list-detail':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'show':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'statistics':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'uptime':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'search':
            base_policy.SYSTEM_READER,
        hv_policies.BASE_POLICY_NAME % 'servers':
            base_policy.SYSTEM_READER,
    }

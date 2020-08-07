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

from nova.api.openstack.compute import hosts
from nova.policies import base as base_policy
from nova.policies import hosts as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class HostsPolicyTest(base.BasePolicyTest):
    """Test os-hosts APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(HostsPolicyTest, self).setUp()
        self.controller = hosts.HostController()
        self.req = fakes.HTTPRequest.blank('')

        # Check that admin is able to perform operations on hosts.
        self.system_admin_authorized_contexts = [
            self.system_admin_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to perform operations
        # on hosts.
        self.system_admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context, self.other_project_reader_context
        ]
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context
        ]
        self.system_reader_unauthorized_contexts = [
            self.project_foo_context, self.system_foo_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

    @mock.patch('nova.compute.api.HostAPI.service_get_all')
    def test_list_hosts_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'list'
        self.common_policy_check(self.system_reader_authorized_contexts,
                                 self.system_reader_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req)

    @mock.patch('nova.context.set_target_cell')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.'
        'get_first_node_by_host_for_old_compat')
    @mock.patch('nova.compute.api.HostAPI.instance_get_all_by_host')
    def test_show_host_policy(self, mock_get, mock_node, mock_map, mock_set):
        rule_name = policies.POLICY_NAME % 'show'
        self.common_policy_check(self.system_reader_authorized_contexts,
                                 self.system_reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, 11111)

    def test_update_host_policy(self):
        rule_name = policies.POLICY_NAME % 'update'
        self.common_policy_check(self.system_admin_authorized_contexts,
                                 self.system_admin_unauthorized_contexts,
                                 rule_name, self.controller.update,
                                 self.req, 11111, body={})

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_reboot_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'reboot'
        self.common_policy_check(self.system_admin_authorized_contexts,
                                 self.system_admin_unauthorized_contexts,
                                 rule_name, self.controller.reboot,
                                 self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_shutdown_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'shutdown'
        self.common_policy_check(self.system_admin_authorized_contexts,
                                 self.system_admin_unauthorized_contexts,
                                 rule_name, self.controller.shutdown,
                                 self.req, 11111)

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_startup_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'start'
        self.common_policy_check(self.system_admin_authorized_contexts,
                                 self.system_admin_unauthorized_contexts,
                                 rule_name, self.controller.startup,
                                 self.req, 11111)


class HostsScopeTypePolicyTest(HostsPolicyTest):
    """Test os-hosts APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(HostsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system admin is able to perform operations on hosts.
        self.system_admin_authorized_contexts = [
            self.system_admin_context]
        # Check that system non-admin is not able to perform operations
        # on hosts.
        self.system_admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context, self.other_project_reader_context
        ]
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context
        ]
        self.system_reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]


class HostsNoLegacyPolicyTest(HostsScopeTypePolicyTest):
    """Test Hosts APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_NAME % 'list':
            base_policy.SYSTEM_READER,
        policies.POLICY_NAME % 'show':
            base_policy.SYSTEM_READER,
        policies.POLICY_NAME % 'update':
            base_policy.SYSTEM_ADMIN,
        policies.POLICY_NAME % 'reboot':
            base_policy.SYSTEM_ADMIN,
        policies.POLICY_NAME % 'shutdown':
            base_policy.SYSTEM_ADMIN,
        policies.POLICY_NAME % 'startup':
            base_policy.SYSTEM_ADMIN}

    def setUp(self):
        super(HostsNoLegacyPolicyTest, self).setUp()

        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context
        ]
        self.system_reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        self.system_admin_authorized_contexts = [
            self.system_admin_context
        ]
        self.system_admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.project_admin_context, self.project_member_context,
            self.legacy_admin_context, self.other_project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_foo_context, self.other_project_reader_context
        ]

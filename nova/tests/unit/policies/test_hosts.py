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

from nova.api.openstack.compute import hosts
from nova import objects
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

        # With legacy rule and scope check disabled by default,
        # legacy admin and project admin will be able to perform hosts
        # Operations.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.HostAPI.service_get_all')
    def test_list_hosts_policy(self, mock_get):
        rule_name = policies.POLICY_NAME % 'list'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    @mock.patch('nova.context.set_target_cell')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNode.get_first_node_by_host_for_old_compat')  # noqa: E501
    @mock.patch('nova.compute.api.HostAPI.instance_get_all_by_host')
    def test_show_host_policy(self, mock_get, mock_node, mock_map, mock_set):
        mock_get.return_value = []
        mock_node.return_value = objects.ComputeNode(
            vcpus=16, memory_mb=8192, local_gb=1000,
            vcpus_used=4, memory_mb_used=1024, local_gb_used=10,
        )
        rule_name = policies.POLICY_NAME % 'show'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.show,
                                self.req, 'hostname')

    @mock.patch('nova.compute.api.HostAPI.set_host_enabled')
    def test_update_host_policy(self, mock_set_host_enabled):
        mock_set_host_enabled.return_value = 'enabled'
        rule_name = policies.POLICY_NAME % 'update'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.update,
                                self.req, 'hostname',
                                body={'status': 'enable'})

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_reboot_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'reboot'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.reboot,
                                self.req, 'hostname')

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_shutdown_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'shutdown'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.shutdown,
                                self.req, 'hostname')

    @mock.patch('nova.compute.api.HostAPI.host_power_action')
    def test_startup_host_policy(self, mock_action):
        rule_name = policies.POLICY_NAME % 'start'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.startup,
                                self.req, 'hostname')


class HostsNoLegacyPolicyTest(HostsPolicyTest):
    """Test Hosts APIs policies with no legacy deprecated rules
    which means new defaults only. In this case, legacy admin and
    project admin will be able to perform hosts Operations.

    """

    without_deprecated_rules = True

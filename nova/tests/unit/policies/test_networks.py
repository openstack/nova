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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import networks
from nova.policies import base as base_policy
from nova.policies import networks as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class NetworksPolicyTest(base.BasePolicyTest):
    """Test Networks APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(NetworksPolicyTest, self).setUp()
        self.controller = networks.NetworkController()
        self.req = fakes.HTTPRequest.blank('')
        # Check that everyone is able to get networks.
        # NOTE: Nova cannot verify the networks owner during nova policy
        # enforcement so will be passing context's project_id as target to
        # policy and always pass. If requester is not admin or owner
        # of networks then neutron will be returning the appropriate error.
        self.reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]
        self.reader_unauthorized_contexts = []

    @mock.patch('nova.network.neutron.API.get_all')
    def test_list_networks_policy(self, mock_get):
        rule_name = "os_compute_api:os-networks:list"
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req)

    @mock.patch('nova.network.neutron.API.get')
    def test_show_network_policy(self, mock_get):
        rule_name = "os_compute_api:os-networks:show"
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, uuids.fake_id)


class NetworksScopeTypePolicyTest(NetworksPolicyTest):
    """Test Networks APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(NetworksScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class NetworksNoLegacyPolicyTest(NetworksScopeTypePolicyTest):
    """Test Networks APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.POLICY_ROOT % 'list':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        policies.POLICY_ROOT % 'show':
            base_policy.PROJECT_READER_OR_SYSTEM_READER}

    def setUp(self):
        super(NetworksNoLegacyPolicyTest, self).setUp()
        self.reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]
        self.reader_unauthorized_contexts = [
            self.project_foo_context,
            self.system_foo_context
        ]

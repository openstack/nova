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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import baremetal_nodes
from nova.policies import baremetal_nodes as policies
from nova.policies import base as base_policy
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base
from nova.tests.unit.virt.ironic import utils as ironic_utils


FAKE_IRONIC_CLIENT = ironic_utils.FakeClient()


class BaremetalNodesPolicyTest(base.BasePolicyTest):
    """Test Baremetal Nodes APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(BaremetalNodesPolicyTest, self).setUp()
        self.controller = baremetal_nodes.BareMetalNodeController()
        self.req = fakes.HTTPRequest.blank('')
        self.stub_out('nova.api.openstack.compute.'
                      'baremetal_nodes._get_ironic_client',
                      lambda *_: FAKE_IRONIC_CLIENT)
        # With legacy rule and scope check disabled by default, system admin,
        # legacy admin, and project admin will be able to get baremetal nodes.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    def test_index_nodes_policy(self):
        rule_name = "os_compute_api:os-baremetal-nodes:list"
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'get')
    def test_show_node_policy(self, mock_get, mock_port):
        rule_name = "os_compute_api:os-baremetal-nodes:show"
        properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
        node = ironic_utils.get_test_node(properties=properties)
        mock_get.return_value = node
        mock_port.return_value = []

        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, uuids.fake_id)


class BaremetalNodesNoLegacyNoScopePolicyTest(BaremetalNodesPolicyTest):
    """Test Baremetal Nodes APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only. In that case
    system admin, legacy admin, and project admin will be able to get
    Baremetal nodes Legacy admin will be allowed as policy is just admin if
    no scope checks.

    """

    without_deprecated_rules = True


class BaremetalNodesScopeTypePolicyTest(BaremetalNodesPolicyTest):
    """Test Baremetal Nodes APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scopped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(BaremetalNodesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope checks enable, only project-scoped admins are
        # able to get baremetal nodes.
        self.project_admin_authorized_contexts = [self.legacy_admin_context,
                                                 self.project_admin_context]


class BNScopeTypeNoLegacyPolicyTest(BaremetalNodesScopeTypePolicyTest):
    """Test Baremetal Nodes APIs policies with no legacy deprecated rules
    and scope checks enabled which means scope + new defaults so
    only system admin is able to get baremetal nodes.
    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.BASE_POLICY_NAME % 'list':
            base_policy.ADMIN,
        policies.BASE_POLICY_NAME % 'show':
            base_policy.ADMIN}

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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import server_topology
from nova.compute import vm_states
from nova import objects
from nova.policies import server_topology as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerTopologyPolicyTest(base.BasePolicyTest):
    """Test Server Topology APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerTopologyPolicyTest, self).setUp()
        self.controller = server_topology.ServerTopologyController()
        self.req = fakes.HTTPRequest.blank('', version='2.78')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                vm_state=vm_states.ACTIVE)
        self.mock_get.return_value = self.instance
        self.instance.numa_topology = objects.InstanceNUMATopology(
                instance_uuid = self.instance.uuid,
                cells=[objects.InstanceNUMACell(
                    node=0, memory=1024, pagesize=4, id=123,
                    cpu_topology=None,
                    cpu_pinning={},
                    cpuset=set([0, 1]))])

        # Check that system reader or and server owner is able to get
        # the server topology.
        self.system_reader_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context]
        # Check that non-stem reader/owner is not able to get
        # the server topology.
        self.system_reader_or_owner_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context,
        ]
        # Check that system reader is able to get the server topology
        # host information.
        self.system_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system reader is not able to get the server topology
        # host information.
        self.system_reader_unauthorized_contexts = [
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context,
            self.other_project_reader_context
        ]

    def test_index_server_topology_policy(self):
        rule_name = policies.BASE_POLICY_NAME % 'index'
        self.common_policy_check(
            self.system_reader_or_owner_authorized_contexts,
            self.system_reader_or_owner_unauthorized_contexts,
            rule_name,
            self.controller.index,
            self.req, self.instance.uuid)

    def test_index_host_server_topology_policy(self):
        rule_name = policies.BASE_POLICY_NAME % 'host:index'
        # 'index' policy is checked before 'host:index' so
        # we have to allow it for everyone otherwise it will
        # fail first for unauthorized contexts.
        rule = policies.BASE_POLICY_NAME % 'index'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        authorize_res, unauthorize_res = self.common_policy_check(
            self.system_reader_authorized_contexts,
            self.system_reader_unauthorized_contexts,
            rule_name, self.controller.index, self.req, self.instance.uuid,
            fatal=False)
        for resp in authorize_res:
            self.assertEqual(123, resp['nodes'][0]['host_node'])
            self.assertEqual({}, resp['nodes'][0]['cpu_pinning'])
        for resp in unauthorize_res:
            self.assertNotIn('host_node', resp['nodes'][0])
            self.assertNotIn('cpu_pinning', resp['nodes'][0])


class ServerTopologyScopeTypePolicyTest(ServerTopologyPolicyTest):
    """Test Server Topology APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerTopologyScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system reader is able to get the server topology
        # host information.
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system/reader is not able to get the server topology
        # host information.
        self.system_reader_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context,
            self.other_project_reader_context,
        ]


class ServerTopologyNoLegacyPolicyTest(ServerTopologyScopeTypePolicyTest):
    """Test Server Topology APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerTopologyNoLegacyPolicyTest, self).setUp()
        # Check that system reader/owner is able to get
        # the server topology.
        self.system_reader_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context, self.system_reader_context,
            self.project_reader_context]
        # Check that non-system/reader/owner is not able to get
        # the server topology.
        self.system_reader_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.other_project_member_context, self.project_foo_context,
            self.other_project_reader_context,
        ]

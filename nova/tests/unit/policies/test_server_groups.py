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

from nova.api.openstack.compute import server_groups
from nova.policies import server_groups as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class ServerGroupPolicyTest(base.BasePolicyTest):
    """Test Server Groups APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerGroupPolicyTest, self).setUp()
        self.controller = server_groups.ServerGroupController()
        self.req = fakes.HTTPRequest.blank('')

        # Policy is admin_or_owner but we do not pass the project id
        # in policy enforcement to check the ownership. project id
        # is nothing but of server group for which request is made. So
        # let's keep it as it is and with new defaults and sceop enbled,
        # these can be authorized to meanigful roles.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]
        self.admin_or_owner_unauthorized_contexts = [
        ]

    @mock.patch('nova.objects.InstanceGroupList.get_all')
    def test_index_server_groups_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req)

    @mock.patch('nova.objects.InstanceGroup.get_by_uuid')
    def test_show_server_groups_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.show,
                                 self.req, uuids.fake_id)

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_server_groups_policy(self, mock_quota):
        rule_name = policies.POLICY_ROOT % 'create'
        body = {'server_group': {'name': 'fake',
                                 'policies': ['affinity']}}
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.create,
                                 self.req, body=body)

    @mock.patch('nova.objects.InstanceGroup.get_by_uuid')
    def test_delete_server_groups_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.delete,
                                 self.req, uuids.fake_id)


class ServerGroupScopeTypePolicyTest(ServerGroupPolicyTest):
    """Test Server Groups APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerGroupScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

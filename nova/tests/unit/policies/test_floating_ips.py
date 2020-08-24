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
from oslo_utils import timeutils

from nova.api.openstack.compute import floating_ips
from nova.compute import vm_states
from nova.network import model as network_model
from nova.policies import base as base_policy
from nova.policies import floating_ips as fip_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network_cache_model
from nova.tests.unit.policies import base


class FloatingIPPolicyTest(base.BasePolicyTest):
    """Test Floating IP APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FloatingIPPolicyTest, self).setUp()
        self.controller = floating_ips.FloatingIPController()
        self.action_controller = floating_ips.FloatingIPActionController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context, project_id=self.project_id,
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that everyone is able to perform crud operation on FIP.
        # NOTE: Nova cannot verify the FIP owner during nova policy
        # enforcement so will be passing context's project_id as target to
        # policy and always pass. If requester is not admin or owner
        # of FIP then neutron will be returning the appropriate error.
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
        self.cd_authorized_contexts = self.reader_authorized_contexts
        self.cd_unauthorized_contexts = self.reader_unauthorized_contexts
        # Check that admin or owner is able to add/delete FIP to server.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context
        ]
        # Check that non-admin and non-owner is not able to add/delete
        # FIP to server.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

    @mock.patch('nova.network.neutron.API.get_floating_ip')
    def test_show_floating_ip_policy(self, mock_get):
        rule_name = "os_compute_api:os-floating-ips:show"
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, uuids.fake_id)

    @mock.patch('nova.network.neutron.API.get_floating_ips_by_project')
    def test_index_floating_ip_policy(self, mock_get):
        rule_name = "os_compute_api:os-floating-ips:list"
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req)

    @mock.patch('nova.network.neutron.API.get_floating_ip_by_address')
    @mock.patch('nova.network.neutron.API.allocate_floating_ip')
    def test_create_floating_ip_policy(self, mock_create, mock_get):
        rule_name = "os_compute_api:os-floating-ips:create"
        self.common_policy_check(self.cd_authorized_contexts,
                                 self.cd_unauthorized_contexts,
                                 rule_name, self.controller.create,
                                 self.req, uuids.fake_id)

    @mock.patch('nova.network.neutron.API.get_instance_id_by_floating_address')
    @mock.patch('nova.network.neutron.API.get_floating_ip')
    @mock.patch('nova.network.neutron.API.'
        'disassociate_and_release_floating_ip')
    def test_delete_floating_ip_policy(self, mock_delete, mock_get,
            mock_instance):
        rule_name = "os_compute_api:os-floating-ips:delete"
        self.common_policy_check(self.cd_authorized_contexts,
                                 self.cd_unauthorized_contexts,
                                 rule_name, self.controller.delete,
                                 self.req, uuids.fake_id)

    @mock.patch('nova.objects.Instance.get_network_info')
    @mock.patch('nova.network.neutron.API.associate_floating_ip')
    def test_add_floating_ip_policy(self, mock_add, mock_net):
        rule_name = "os_compute_api:os-floating-ips:add"
        ninfo = network_model.NetworkInfo([fake_network_cache_model.new_vif(),
                fake_network_cache_model.new_vif(
                        {'address': 'bb:bb:bb:bb:bb:bb'})])
        mock_net.return_value = network_model.NetworkInfo.hydrate(ninfo)
        body = {'addFloatingIp': {
                    'address': '1.2.3.4'}}
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.action_controller._add_floating_ip,
                                 self.req, self.instance.uuid, body=body)

    @mock.patch('nova.network.neutron.API.get_instance_id_by_floating_address')
    @mock.patch('nova.network.neutron.API.get_floating_ip_by_address')
    @mock.patch('nova.network.neutron.API.disassociate_floating_ip')
    def test_remove_floating_ip_policy(self, mock_remove, mock_get,
            mock_instance):
        rule_name = "os_compute_api:os-floating-ips:remove"
        mock_instance.return_value = self.instance.uuid
        body = {'removeFloatingIp': {
                    'address': '1.2.3.4'}}
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.action_controller._remove_floating_ip,
                                 self.req, self.instance.uuid, body=body)


class FloatingIPScopeTypePolicyTest(FloatingIPPolicyTest):
    """Test Floating IP APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FloatingIPScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class FloatingIPNoLegacyPolicyTest(FloatingIPScopeTypePolicyTest):
    """Test Floating IP APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        fip_policies.BASE_POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        fip_policies.BASE_POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        fip_policies.BASE_POLICY_NAME % 'create':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        fip_policies.BASE_POLICY_NAME % 'delete':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        fip_policies.BASE_POLICY_NAME % 'add':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        fip_policies.BASE_POLICY_NAME % 'remove':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN}

    def setUp(self):
        super(FloatingIPNoLegacyPolicyTest, self).setUp()
        # Check that system admin or owner is able to
        # add/delete FIP to server.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
        ]
        # Check that non-system and non-admin/owner is not able
        # to add/delete FIP to server.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]
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
        self.cd_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.project_admin_context, self.project_member_context,
            self.legacy_admin_context, self.other_project_member_context
        ]
        self.cd_unauthorized_contexts = [
            self.system_reader_context,
            self.project_reader_context, self.project_foo_context,
            self.system_foo_context, self.other_project_reader_context
        ]

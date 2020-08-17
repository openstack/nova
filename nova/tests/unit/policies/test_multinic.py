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

from nova.api.openstack.compute import multinic
from nova.compute import vm_states
from nova.policies import base as base_policy
from nova.policies import multinic as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class MultinicPolicyTest(base.BasePolicyTest):
    """Test Multinic APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MultinicPolicyTest, self).setUp()
        self.controller = multinic.MultinicController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context, project_id=self.project_id,
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that admin or owner is able to add/remove fixed ip.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context
        ]
        # Check that non-admin and non-owner is not able to add/remove
        # fixed ip.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]

    @mock.patch('nova.compute.api.API.add_fixed_ip')
    def test_add_fixed_ip_policy(self, mock_add):
        rule_name = "os_compute_api:os-multinic:add"
        body = dict(addFixedIp=dict(networkId='test_net'))
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name, self.controller._add_fixed_ip,
                                 self.req, self.instance.uuid,
                                 body=body)

    @mock.patch('nova.compute.api.API.remove_fixed_ip')
    def test_remove_fixed_ip_policy(self, mock_remove):
        rule_name = "os_compute_api:os-multinic:remove"
        body = dict(removeFixedIp=dict(address='1.2.3.4'))
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name, self.controller._remove_fixed_ip,
                                 self.req, self.instance.uuid,
                                 body=body)


class MultinicScopeTypePolicyTest(MultinicPolicyTest):
    """Test Multinic APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MultinicScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class MultinicNoLegacyPolicyTest(MultinicScopeTypePolicyTest):
    """Test Multinic APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        policies.BASE_POLICY_NAME % 'add':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        policies.BASE_POLICY_NAME % 'remove':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN}

    def setUp(self):
        super(MultinicNoLegacyPolicyTest, self).setUp()
        # Check that system admin or owner is able to
        # add/delete Fixed IP to server.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
        ]
        # Check that non-system and non-admin/owner is not able
        # to add/delete Fixed IP to server.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]

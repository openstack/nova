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

from nova.api.openstack.compute import admin_actions
from nova.compute import vm_states
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class AdminActionsPolicyTest(base.BasePolicyTest):
    """Test Admin Actions APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AdminActionsPolicyTest, self).setUp()
        self.controller = admin_actions.AdminActionsController()
        self.req = fakes.HTTPRequest.blank('')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.compute.api.API.get')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuid, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that admin is able to change the service
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to change the service
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]

    @mock.patch('nova.objects.Instance.save')
    def test_reset_state_policy(self, mock_save):
        rule_name = "os_compute_api:os-admin-actions:reset_state"
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._reset_state,
                                 self.req, self.instance.uuid,
                                 body={'os-resetState': {'state': 'active'}})

    def test_inject_network_info_policy(self):
        rule_name = "os_compute_api:os-admin-actions:inject_network_info"
        with mock.patch.object(self.controller.compute_api,
                               "inject_network_info"):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name,
                                     self.controller._inject_network_info,
                                     self.req, self.instance.uuid, body={})

    def test_reset_network_policy(self):
        rule_name = "os_compute_api:os-admin-actions:reset_network"
        with mock.patch.object(self.controller.compute_api, "reset_network"):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller._reset_network,
                                     self.req, self.instance.uuid, body={})


class AdminActionsScopeTypePolicyTest(AdminActionsPolicyTest):
    """Test Admin Actions APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scopped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(AdminActionsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class AdminActionsNoLegacyPolicyTest(AdminActionsScopeTypePolicyTest):
    """Test Admin Actions APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(AdminActionsScopeTypePolicyTest, self).setUp()
        # Check that system admin is able to perform the system level actions
        # on server.
        self.admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system or non-admin is not able to perform the system
        # level actions on server.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]

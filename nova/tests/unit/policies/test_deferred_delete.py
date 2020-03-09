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

from nova.api.openstack.compute import deferred_delete
from nova.compute import vm_states
from nova import exception
from nova.policies import base as base_policy
from nova.policies import deferred_delete as dd_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class DeferredDeletePolicyTest(base.BasePolicyTest):
    """Test Deferred Delete APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(DeferredDeletePolicyTest, self).setUp()
        self.controller = deferred_delete.DeferredDeleteController()
        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context, project_id=self.project_id,
                id=1, uuid=uuid, user_id=user_id, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that admin or owner is able to force delete or restore server.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context
        ]
        # Check that non-admin and non-owner is not able to force delete or
        # restore server.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

    @mock.patch('nova.compute.api.API.restore')
    def test_restore_server_policy(self, mock_restore):
        rule_name = dd_policies.BASE_POLICY_NAME % 'restore'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._restore,
                                 self.req, self.instance.uuid,
                                 body={'restore': {}})

    def test_force_delete_server_policy(self):
        rule_name = dd_policies.BASE_POLICY_NAME % 'force'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._force_delete,
                                 self.req, self.instance.uuid,
                                 body={'forceDelete': {}})

    def test_force_delete_server_policy_failed_with_other_user(self):
        rule_name = dd_policies.BASE_POLICY_NAME % 'force'
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._force_delete,
            req, self.instance.uuid, body={'forceDelete': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.force_delete')
    def test_force_delete_server_policy_pass_with_same_user(
        self, force_delete_mock):
        rule_name = dd_policies.BASE_POLICY_NAME % 'force'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._force_delete(self.req, self.instance.uuid,
                                      body={'forceDelete': {}})
        force_delete_mock.assert_called_once_with(
            self.req.environ['nova.context'], self.instance)


class DeferredDeleteScopeTypePolicyTest(DeferredDeletePolicyTest):
    """Test Deferred Delete APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(DeferredDeleteScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class DeferredDeleteNoLegacyPolicyTest(DeferredDeletePolicyTest):
    """Test Deferred Delete APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        dd_policies.BASE_POLICY_NAME % 'restore':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
        dd_policies.BASE_POLICY_NAME % 'force':
            base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN}

    def setUp(self):
        super(DeferredDeleteNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system or projct admin or owner is able to
        # force delete or restore server.
        self.admin_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system and non-admin/owner is not able to
        # force delete or restore server.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_reader_context,
            self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]

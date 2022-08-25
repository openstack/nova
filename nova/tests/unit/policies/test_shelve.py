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

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import shelve
from nova.compute import vm_states
from nova import exception
from nova.policies import shelve as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ShelveServerPolicyTest(base.BasePolicyTest):
    """Test Shelve server APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ShelveServerPolicyTest, self).setUp()
        self.controller = shelve.ShelveController()
        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
            self.project_member_context,
            id=1, uuid=uuids.fake_id, project_id=self.project_id,
            user_id=user_id, vm_state=vm_states.ACTIVE)
        self.mock_get.return_value = self.instance
        # With legacy rule and no scope checks, all admin, project members
        # project reader or other project role(because legacy rule allow server
        # owner- having same project id and no role check) is able to shelve,
        # unshelve the server.
        self.project_action_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]

        # By default, legacy rule are enable and scope check is disabled.
        # system admin, legacy admin, and project admin is able to shelve
        # offload the server.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.API.shelve')
    def test_shelve_server_policy(self, mock_shelve):
        rule_name = policies.POLICY_ROOT % 'shelve'
        self.common_policy_auth(self.project_action_authorized_contexts,
                                rule_name,
                                self.controller._shelve,
                                self.req, self.instance.uuid,
                                body={'shelve': {}})

    @mock.patch('nova.compute.api.API.unshelve')
    def test_unshelve_server_policy(self, mock_unshelve):
        rule_name = policies.POLICY_ROOT % 'unshelve'
        self.common_policy_auth(self.project_action_authorized_contexts,
                                rule_name,
                                self.controller._unshelve,
                                self.req, self.instance.uuid,
                                body={'unshelve': {}})

    @mock.patch('nova.compute.api.API.shelve_offload')
    def test_shelve_offload_server_policy(self, mock_offload):
        rule_name = policies.POLICY_ROOT % 'shelve_offload'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller._shelve_offload,
                                self.req, self.instance.uuid,
                                body={'shelveOffload': {}})

    def test_shelve_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.POLICY_ROOT % 'shelve'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._shelve,
            req, fakes.FAKE_UUID, body={'shelve': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.shelve')
    def test_shelve_server_overridden_policy_pass_with_same_user(
        self, mock_shelve):
        rule_name = policies.POLICY_ROOT % 'shelve'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        self.controller._shelve(self.req,
                                fakes.FAKE_UUID,
                                body={'shelve': {}})


class ShelveServerNoLegacyNoScopePolicyTest(ShelveServerPolicyTest):
    """Test shelve/unshelve server APIs policies with no legacy deprecated
    rules and no scope checks which means new defaults only.

    """
    without_deprecated_rules = True

    def setUp(self):
        super(ShelveServerNoLegacyNoScopePolicyTest, self).setUp()
        # With no legacy rule, only project admin or member will be
        # able to shelve/unshelve the server and only project admin can
        # shelve offload the server.
        self.project_action_authorized_contexts = (
            self.project_member_or_admin_with_no_scope_no_legacy)


class ShelveServerScopeTypePolicyTest(ShelveServerPolicyTest):
    """Test Shelve Server APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ShelveServerScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # Scope enable will not allow system admin to shelve/unshelve the
        # server.
        self.project_action_authorized_contexts = (
            self.project_m_r_or_admin_with_scope_and_legacy)
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]


class ShelveServerScopeTypeNoLegacyPolicyTest(ShelveServerScopeTypePolicyTest):
    """Test Shelve Server APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ShelveServerScopeTypeNoLegacyPolicyTest, self).setUp()
        # With scope enable and no legacy rule, only project admin/member
        # will be able to shelve/unshelve the server.
        self.project_action_authorized_contexts = (
            self.project_member_or_admin_with_scope_no_legacy)

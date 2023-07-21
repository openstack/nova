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
from oslo_utils import timeutils

from nova.api.openstack.compute import migrate_server
from nova.compute import vm_states
from nova.policies import base as base_policy
from nova.policies import migrate_server as ms_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class MigrateServerPolicyTest(base.BasePolicyTest):
    """Test Migrate Server APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MigrateServerPolicyTest, self).setUp()
        self.controller = migrate_server.MigrateServerController()
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

        # With legacy rule, any admin is able to migrate
        # the server.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.compute.api.API.resize')
    def test_migrate_server_policy(self, mock_resize):
        rule_name = ms_policies.POLICY_ROOT % 'migrate'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller._migrate,
                                self.req, self.instance.uuid,
                                body={'migrate': None})

    @mock.patch('nova.compute.api.API.resize')
    def test_migrate_server_host_policy(self, mock_resize):
        rule_name = ms_policies.POLICY_ROOT % 'migrate:host'
        # the host parameter was added by the 2.56 microversion.
        req = fakes.HTTPRequest.blank('', version='2.56')
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller._migrate,
                                req, self.instance.uuid,
                                body={'migrate': {"host": "hostname"}})

    @mock.patch('nova.compute.api.API.live_migrate')
    def test_migrate_live_server_policy(self, mock_live_migrate):
        rule_name = ms_policies.POLICY_ROOT % 'migrate_live'
        body = {'os-migrateLive': {
                 'host': 'hostname',
                 'block_migration': "False",
                 'disk_over_commit': "False"}
               }
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name, self.controller._migrate_live,
                                self.req, self.instance.uuid,
                                body=body)


class MigrateServerNoLegacyNoScopeTest(MigrateServerPolicyTest):
    """Test Server Migrations API policies with deprecated rules
    disabled, but scope checking still disabled.
    """

    without_deprecated_rules = True


class MigrateServerScopeTypePolicyTest(MigrateServerPolicyTest):
    """Test Migrate Server APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MigrateServerScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")
        # With scope enabled, system admin is not allowed.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]


class MigrateServerScopeTypeNoLegacyPolicyTest(
        MigrateServerScopeTypePolicyTest):
    """Test Migrate Server APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True


class MigrateServerOverridePolicyTest(
        MigrateServerScopeTypeNoLegacyPolicyTest):
    """Test Migrate Server APIs policies with system and project scoped
    but default to system roles only are allowed for project roles
    if override by operators. This test is with system scope enable
    and no more deprecated rules.
    """

    def setUp(self):
        super(MigrateServerOverridePolicyTest, self).setUp()
        rule_migrate = ms_policies.POLICY_ROOT % 'migrate'
        rule_migrate_host = ms_policies.POLICY_ROOT % 'migrate:host'
        rule_live_migrate = ms_policies.POLICY_ROOT % 'migrate_live'
        # NOTE(gmann): override the rule to project member and verify it
        # work as policy is system and project scoped.
        self.policy.set_rules({
            rule_migrate: base_policy.PROJECT_MEMBER,
            rule_migrate_host: base_policy.PROJECT_MEMBER,
            rule_live_migrate: base_policy.PROJECT_MEMBER},
            overwrite=False)

        # Check that project member role as override above
        # is able to migrate the server
        self.project_admin_authorized_contexts = [
            self.project_admin_context, self.project_member_context]

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

        # Check that admin is able to migrate the server.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context
        ]
        # Check that non-admin is not able to migrate the server
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]

    @mock.patch('nova.compute.api.API.resize')
    @mock.patch('nova.api.openstack.common.'
                'instance_has_port_with_resource_request', return_value=False)
    def test_migrate_server_policy(self, mock_port, mock_resize):
        rule_name = ms_policies.POLICY_ROOT % 'migrate'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._migrate,
                                 self.req, self.instance.uuid,
                                 body={'migrate': None})

    @mock.patch('nova.compute.api.API.live_migrate')
    @mock.patch('nova.api.openstack.common.'
                'instance_has_port_with_resource_request', return_value=False)
    def test_migrate_live_server_policy(self, mock_port, mock_live_migrate):
        rule_name = ms_policies.POLICY_ROOT % 'migrate_live'
        body = {'os-migrateLive': {
                 'host': 'hostname',
                 'block_migration': "False",
                 'disk_over_commit': "False"}
               }
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._migrate_live,
                                 self.req, self.instance.uuid,
                                 body=body)


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


class MigrateServerNoLegacyPolicyTest(MigrateServerScopeTypePolicyTest):
    """Test Migrate Server APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(MigrateServerNoLegacyPolicyTest, self).setUp()
        # Check that system admin is able to migrate the server.
        self.admin_authorized_contexts = [
            self.system_admin_context
        ]
        # Check that non system admin is not able to migrate the server
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]


class MigrateServerOverridePolicyTest(MigrateServerNoLegacyPolicyTest):
    """Test Migrate Server APIs policies with system and project scoped
    but default to system roles only are allowed for project roles
    if override by operators. This test is with system scope enable
    and no more deprecated rules.
    """

    def setUp(self):
        super(MigrateServerOverridePolicyTest, self).setUp()
        rule_migrate = ms_policies.POLICY_ROOT % 'migrate'
        rule_live_migrate = ms_policies.POLICY_ROOT % 'migrate_live'
        # NOTE(gmann): override the rule to project member and verify it
        # work as policy is system and projct scoped.
        self.policy.set_rules({
            rule_migrate: base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
            rule_live_migrate: base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN},
            overwrite=False)

        # Check that system admin or project scoped role as override above
        # is able to migrate the server
        self.admin_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context]
        # Check that non-system admin or project role is not able to
        # migrate the server
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]

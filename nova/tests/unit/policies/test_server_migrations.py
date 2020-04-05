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

from nova.api.openstack.compute import server_migrations
from nova.compute import vm_states
from nova.policies import base as base_policy
from nova.policies import servers_migrations as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServerMigrationsPolicyTest(base.BasePolicyTest):
    """Test Server Migrations APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerMigrationsPolicyTest, self).setUp()
        self.controller = server_migrations.ServerMigrationsController()
        self.req = fakes.HTTPRequest.blank('', version='2.24')
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                vm_state=vm_states.ACTIVE)
        self.mock_get.return_value = self.instance

        # Check that admin is able to perform operations
        # for server migrations.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to perform operations
        # for server migrations.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]
        # Check that system-reader are able to perform operations
        # for server migrations.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-system-reader are not able to perform operations
        # for server migrations.
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context]

    @mock.patch('nova.compute.api.API.get_migrations_in_progress_by_instance')
    def test_list_server_migrations_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req, self.instance.uuid)

    @mock.patch('nova.api.openstack.compute.server_migrations.output')
    @mock.patch('nova.compute.api.API.get_migration_by_id_and_instance')
    def test_show_server_migrations_policy(self, mock_show, mock_output):
        rule_name = policies.POLICY_ROOT % 'show'
        mock_show.return_value = {"migration_type": "live-migration",
                                  "status": "running"}
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, self.instance.uuid, 11111)

    @mock.patch('nova.compute.api.API.live_migrate_abort')
    def test_delete_server_migrations_policy(self, mock_delete):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller.delete,
                                 self.req, self.instance.uuid, 11111)

    @mock.patch('nova.compute.api.API.live_migrate_force_complete')
    def test_force_delete_server_migrations_policy(self, mock_force):
        rule_name = policies.POLICY_ROOT % 'force_complete'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._force_complete,
                                 self.req, self.instance.uuid, 11111,
                                 body={"force_complete": None})


class ServerMigrationsScopeTypePolicyTest(ServerMigrationsPolicyTest):
    """Test Server Migrations APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerMigrationsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class ServerMigrationsNoLegacyPolicyTest(ServerMigrationsScopeTypePolicyTest):
    """Test Server Migrations APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServerMigrationsNoLegacyPolicyTest, self).setUp()
        # Check that admin is able to perform operations
        # for server migrations.
        self.admin_authorized_contexts = [
            self.system_admin_context
        ]
        # Check that non-admin is not able to perform operations
        # for server migrations.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context
        ]
        # Check that system reader is able to perform operations
        # for server migrations.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system-reader is not able to perform operations
        # for server migrations.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]


class ServerMigrationsOverridePolicyTest(ServerMigrationsNoLegacyPolicyTest):
    """Test Server Migrations APIs policies with system and project scoped
    but default to system roles only are allowed for project roles
    if override by operators. This test is with system scope enable
    and no more deprecated rules.
    """

    def setUp(self):
        super(ServerMigrationsOverridePolicyTest, self).setUp()
        rule_show = policies.POLICY_ROOT % 'show'
        rule_list = policies.POLICY_ROOT % 'index'
        rule_force = policies.POLICY_ROOT % 'force_complete'
        rule_delete = policies.POLICY_ROOT % 'delete'
        # NOTE(gmann): override the rule to project member and verify it
        # work as policy is system and projct scoped.
        self.policy.set_rules({
            rule_show: base_policy.PROJECT_READER_OR_SYSTEM_READER,
            rule_list: base_policy.PROJECT_READER_OR_SYSTEM_READER,
            rule_force: base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN,
            rule_delete: base_policy.PROJECT_MEMBER_OR_SYSTEM_ADMIN},
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
            self.project_foo_context, self.project_reader_context
        ]
        # Check that system reader is able to perform operations
        # for server migrations.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context]
        # Check that non-system-reader is not able to perform operations
        # for server migrations.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.other_project_member_context, self.project_foo_context
        ]

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

import datetime
import functools
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import migrations
import nova.conf
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.policies import base as base_policy
from nova.policies import migrations as migrations_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base

CONF = nova.conf.CONF


class MigrationsPolicyTest(base.BasePolicyTest):
    """Test Migrations APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MigrationsPolicyTest, self).setUp()
        self.controller = migrations.MigrationsController()
        self.req = fakes.HTTPRequest.blank('')

        # With legacy rule, any admin is able to list migrations.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

        self.project_manager_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.other_project_manager_context]

    def fake_migrations(self, project_id=None, same_project=None):
        migration = [
            {
                'id': 1234,
                'source_node': 'node1',
                'dest_node': 'node2',
                'dest_compute_id': 123,
                'source_compute': 'compute1',
                'dest_compute': 'compute2',
                'dest_host': '1.2.3.4',
                'status': 'running',
                'instance_uuid': uuids.instance,
                'old_instance_type_id': 1,
                'new_instance_type_id': 2,
                'migration_type': 'migration',
                'hidden': False,
                'memory_total': 123456,
                'memory_processed': 12345,
                'memory_remaining': 111111,
                'disk_total': 234567,
                'disk_processed': 23456,
                'disk_remaining': 211111,
                'created_at': datetime.datetime(2025, 1, 1),
                'updated_at': datetime.datetime(2025, 1, 1),
                'deleted_at': None,
                'deleted': False,
                'uuid': uuids.migration1,
                'cross_cell_move': False,
                'user_id': uuids.user_id,
                'project_id': uuids.other_project_id,
            }
        ]
        if project_id is None:
            return [migration[0], migration[0]]
        if same_project:
            migration[0]['project_id'] = project_id
        return migration

    @mock.patch('nova.compute.api.API.get_migrations')
    def test_list_migrations_policy(self, mock_migration):
        rule = migrations_policies.POLICY_ROOT % 'index:all_projects'
        # Migration 'index:all_projects' policy is checked after 'index'
        # policy so we have to allow it to everyone so that we can test
        # 'index' policy properly.
        self.policy.set_rules({rule: "@"}, overwrite=False)

        rule_name = migrations_policies.POLICY_ROOT % 'index'
        self.common_policy_auth(self.project_manager_authorized_contexts,
                                rule_name, self.controller.index,
                                self.req)

    @mock.patch('nova.compute.api.API.get_migrations')
    def test_list_migrations_host_policy(self, mock_get):
        fake_migration = self.fake_migrations()
        mock_get.return_value = obj_base.obj_make_list(
            'fake-context',
            objects.MigrationList(),
            objects.Migration,
            fake_migration)

        rule_1 = migrations_policies.POLICY_ROOT % 'index'
        rule_2 = migrations_policies.POLICY_ROOT % 'index:all_projects'
        # Migration 'index' and 'index:all_projects' policy are checked
        # before 'index:host' policy so we have to allow those to everyone
        # otherwise it will fail first for unauthorized contexts.
        self.policy.set_rules({rule_1: "@", rule_2: "@"}, overwrite=False)
        rule_name = migrations_policies.POLICY_ROOT % 'index:host'
        authorize_res, unauthorize_res = self.common_policy_auth(
            self.project_admin_authorized_contexts,
            rule_name, self.controller.index, self.req,
            fatal=False)
        self.assertNotEqual(0, len(authorize_res))
        self.assertNotEqual(0, len(unauthorize_res))
        # NOTE(gmaan): Check host info is returned only in authorized
        # context response.
        for resp in authorize_res:
            self.assertIn('compute2', resp['migrations'][0]['dest_compute'])
            self.assertIn('1.2.3.4', resp['migrations'][0]['dest_host'])
            self.assertIn('node2', resp['migrations'][0]['dest_node'])
            self.assertIn('compute1', resp['migrations'][0]['source_compute'])
            self.assertIn('node1', resp['migrations'][0]['source_node'])
            self.assertIn('compute2', resp['migrations'][1]['dest_compute'])
            self.assertIn('1.2.3.4', resp['migrations'][1]['dest_host'])
            self.assertIn('node2', resp['migrations'][1]['dest_node'])
            self.assertIn('compute1', resp['migrations'][1]['source_compute'])
            self.assertIn('node1', resp['migrations'][1]['source_node'])
        for resp in unauthorize_res:
            self.assertIsNone(resp['migrations'][0]['dest_compute'])
            self.assertIsNone(resp['migrations'][0]['dest_host'])
            self.assertIsNone(resp['migrations'][0]['dest_node'])
            self.assertIsNone(resp['migrations'][0]['source_compute'])
            self.assertIsNone(resp['migrations'][0]['source_node'])
            self.assertIsNone(resp['migrations'][1]['dest_compute'])
            self.assertIsNone(resp['migrations'][1]['dest_host'])
            self.assertIsNone(resp['migrations'][1]['dest_node'])
            self.assertIsNone(resp['migrations'][1]['source_compute'])
            self.assertIsNone(resp['migrations'][1]['source_node'])

    def test_list_migrations_check_primary_policy(self):
        rule = migrations_policies.POLICY_ROOT % 'index'
        # Migration 'index' policy is the primary policy and checked before
        # 'index:host' and 'host:all_projects' policies so if 'index' policy
        # is not allowed and even other policies are allowed then server
        # migration list will be denied.
        self.policy.set_rules({rule: "!"}, overwrite=False)
        self.common_policy_auth(
            set([]),
            rule, self.controller.index, self.req)

    @mock.patch('nova.compute.api.API.get_migrations_sorted')
    def test_list_all_projects_migrations_policy(self, mock_get):
        fake_migration = self.fake_migrations()
        mock_get.return_value = obj_base.obj_make_list(
            'fake-context',
            objects.MigrationList(),
            objects.Migration,
            fake_migration)

        rule = migrations_policies.POLICY_ROOT % 'index'
        # Migration 'index' policy is checked before 'index:all_projects'
        # policy so we have to allow it for everyone otherwise it
        # will fail first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = migrations_policies.POLICY_ROOT % 'index:all_projects'
        if not CONF.oslo_policy.enforce_scope:
            check_rule = rule_name
        else:
            check_rule = functools.partial(
                base.rule_if_system, rule, rule_name)
        req = fakes.HTTPRequest.blank('/os-migrations', version='2.80')
        authorize_res, _ = self.common_policy_auth(
                self.project_admin_authorized_contexts,
                check_rule, self.controller.index, req,
                fatal_auth=False)
        # NOTE(gmaan): Make sure there are authorize context with response.
        self.assertNotEqual(0, len(authorize_res))
        # NOTE(gmaan): Check all project migrations are returned
        for resp in authorize_res:
            self.assertEqual(2, len(resp['migrations']))

    def prepare_microversion_request(self, cxtx, mock_get, project_id=None):
        if not cxtx.project_id:
            cxtx.project_id = 'fake'
        project_id = project_id or cxtx.project_id
        req = fakes.HTTPRequest.blank(
            '/os-migrations?project_id=%s' % project_id,
            version='2.80')
        req.environ['nova.context'] = cxtx
        fake_migration = self.fake_migrations(
            project_id, same_project=(cxtx.project_id == project_id))
        mock_get.return_value = obj_base.obj_make_list(
            'fake-context',
            objects.MigrationList(),
            objects.Migration,
            fake_migration)
        return req, project_id

    @mock.patch('nova.compute.api.API.get_migrations_sorted')
    def test_list_same_project_migrations_policy(self, mock_get):
        rule_name = migrations_policies.POLICY_ROOT % 'index'
        # NOTE(gmaan): Project manager should be able to get their
        # own project migrations.
        for auth_cxtx in self.project_manager_authorized_contexts:
            req, project_id = self.prepare_microversion_request(
                auth_cxtx, mock_get)
            resp = self.controller.index(req)
            # NOTE(gmaan): Check their own project migrations are returned
            self.assertEqual(1, len(resp['migrations']))
            self.assertEqual(project_id,
                             resp['migrations'][0]['project_id'])
        for unauth_cxtx in (self.all_contexts -
                set(self.project_manager_authorized_contexts)):
            req, project_id = self.prepare_microversion_request(
                unauth_cxtx, mock_get)
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, self.controller.index, req)
            self.assertEqual(
                "Policy doesn't allow %s to be performed." % rule_name,
                exc.format_message())

    @mock.patch('nova.compute.api.API.get_migrations_sorted')
    def test_list_other_project_migrations_policy(self, mock_get):
        rule_name = migrations_policies.POLICY_ROOT % 'index'
        # NOTE(gmaan): Only Admin (not Project manager) can list the
        # other project migrations.
        for auth_cxtx in self.project_admin_authorized_contexts:
            project_id = uuids.other_project_id
            req, _ = self.prepare_microversion_request(
                auth_cxtx, mock_get, project_id=project_id)
            resp = self.controller.index(req)
            # NOTE(gmaan): Check their own project migrations are returned
            self.assertEqual(1, len(resp['migrations']))
            self.assertEqual(project_id,
                             resp['migrations'][0]['project_id'])

        for unauth_cxtx in (self.all_contexts -
                set(self.project_admin_authorized_contexts)):
            project_id = uuids.other_project_id
            req, _ = self.prepare_microversion_request(
                unauth_cxtx, mock_get, project_id=project_id)
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, self.controller.index, req)
            rule_name = migrations_policies.POLICY_ROOT % 'index'
            # NOTE(gmaan): Except system user, 'index' policy will allow
            # 'manager' to access list migration. 'index:all_projects' policy
            # will control if they can get their own or other project
            # migrations.
            if ('manager' in unauth_cxtx.roles and
                unauth_cxtx.system_scope != 'all'):
                rule_name = (migrations_policies.POLICY_ROOT
                             % 'index:all_projects')
            self.assertEqual(
                "Policy doesn't allow %s to be performed." % rule_name,
                exc.format_message())


class MigrationsNoLegacyNoScopeTest(MigrationsPolicyTest):
    """Test Migrations API policies with deprecated rules
    disabled, but scope checking still disabled.
    """

    without_deprecated_rules = True
    rules_without_deprecation = {
        migrations_policies.POLICY_ROOT % 'index':
            base_policy.PROJECT_MANAGER_OR_ADMIN,
    }

    def setUp(self):
        super(MigrationsNoLegacyNoScopeTest, self).setUp()

        # NOTE(gmaan): self.other_project_manager_context is in authorized
        # context to list their own project migration only. They will not
        # be able to get other project migration or host info in migrations.
        self.project_manager_authorized_contexts = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_manager_context,
            self.other_project_manager_context
        ])


class MigrationsScopeTypePolicyTest(MigrationsPolicyTest):
    """Test Migrations APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(MigrationsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope enabled, system admin is not allowed.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]
        self.project_manager_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.other_project_manager_context]


class MigrationsScopeTypeNoLegacyPolicyTest(
        MigrationsScopeTypePolicyTest):
    """Test Migrations APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        migrations_policies.POLICY_ROOT % 'index':
            base_policy.PROJECT_MANAGER_OR_ADMIN,
    }

    def setUp(self):
        super(MigrationsScopeTypeNoLegacyPolicyTest, self).setUp()
        # NOTE(gmaan): This is end goal of new defaults. Only admin can get
        # all project migrations with host info and manager role can only get
        # their own project migrations but without host info.
        self.project_manager_authorized_contexts = set([
            self.legacy_admin_context, self.project_admin_context,
            self.project_manager_context,
            self.other_project_manager_context
        ])

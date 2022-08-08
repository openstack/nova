# Copyright 2011 Piston Cloud Computing, Inc.
# All Rights Reserved.

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

"""Test of Policy Engine For Nova."""

import os.path

import mock
from oslo_policy import policy as oslo_policy
from oslo_serialization import jsonutils
import requests_mock

from nova import context
from nova import exception
from nova.policies import servers as servers_policy
from nova import policy
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_policy
from nova import utils


class PolicyFileTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PolicyFileTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.target = {}

    def test_modified_policy_reloads(self):
        with utils.tempdir() as tmpdir:
            tmpfilename = os.path.join(tmpdir, 'policy')

            self.flags(policy_file=tmpfilename, group='oslo_policy')

            # NOTE(uni): context construction invokes policy check to determine
            # is_admin or not. As a side-effect, policy reset is needed here
            # to flush existing policy cache.
            policy.reset()
            # NOTE(gmann): We do not need to log policy warnings for unit
            # tests.
            policy.init(suppress_deprecation_warnings=True)
            rule = oslo_policy.RuleDefault('example:test', "")
            policy._ENFORCER.register_defaults([rule])

            action = "example:test"
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": ""}')
            policy.authorize(self.context, action, self.target)
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": "!"}')
            policy._ENFORCER.load_rules(True)
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                              self.context, action, self.target)


class PolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PolicyTestCase, self).setUp()
        rules = [
            oslo_policy.RuleDefault("true", '@'),
            oslo_policy.RuleDefault("example:allowed", '@'),
            oslo_policy.RuleDefault("example:denied", "!"),
            oslo_policy.RuleDefault("old_action_not_default", "@"),
            oslo_policy.RuleDefault("new_action", "@"),
            oslo_policy.RuleDefault("old_action_default", "rule:admin_api"),
            oslo_policy.RuleDefault("example:get_http",
                                    "http://www.example.com"),
            oslo_policy.RuleDefault("example:my_file",
                                    "role:compute_admin or "
                                    "project_id:%(project_id)s"),
            oslo_policy.RuleDefault("example:early_and_fail", "! and @"),
            oslo_policy.RuleDefault("example:early_or_success", "@ or !"),
            oslo_policy.RuleDefault("example:lowercase_admin",
                                    "role:admin or role:sysadmin"),
            oslo_policy.RuleDefault("example:uppercase_admin",
                                    "role:ADMIN or role:sysadmin"),
        ]
        policy.reset()
        # NOTE(gmann): We do not need to log policy warnings for unit
        # tests.
        policy.init(suppress_deprecation_warnings=True)
        # before a policy rule can be used, its default has to be registered.
        policy._ENFORCER.register_defaults(rules)
        self.context = context.RequestContext('fake', 'fake', roles=['member'])
        self.target = {}

    def test_authorize_nonexistent_action_throws(self):
        action = "example:noexist"
        self.assertRaises(oslo_policy.PolicyNotRegistered, policy.authorize,
                          self.context, action, self.target)

    def test_authorize_bad_action_throws(self):
        action = "example:denied"
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, self.target)

    def test_authorize_bad_action_noraise(self):
        action = "example:denied"
        result = policy.authorize(self.context, action, self.target, False)
        self.assertFalse(result)

    def test_authorize_good_action(self):
        action = "example:allowed"
        result = policy.authorize(self.context, action, self.target)
        self.assertTrue(result)

    @requests_mock.mock()
    def test_authorize_http_true(self, req_mock):
        req_mock.post('http://www.example.com/',
                      text='True')
        action = "example:get_http"
        target = {}
        result = policy.authorize(self.context, action, target)
        self.assertTrue(result)

    @requests_mock.mock()
    def test_authorize_http_false(self, req_mock):
        req_mock.post('http://www.example.com/',
                      text='False')
        action = "example:get_http"
        target = {}
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, target)

    def test_templatized_authorization(self):
        target_mine = {'project_id': 'fake'}
        target_not_mine = {'project_id': 'another'}
        action = "example:my_file"
        policy.authorize(self.context, action, target_mine)
        # check we fallback to context.project_id
        # TODO(johngarbutt): longer term we need to remove this and make
        #  the target a required param.
        policy.authorize(self.context, action)
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, target_not_mine)

    def test_early_AND_authorization(self):
        action = "example:early_and_fail"
        self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, self.target)

    def test_early_OR_authorization(self):
        action = "example:early_or_success"
        policy.authorize(self.context, action, self.target)

    def test_ignore_case_role_check(self):
        lowercase_action = "example:lowercase_admin"
        uppercase_action = "example:uppercase_admin"
        # NOTE(dprince) we mix case in the Admin role here to ensure
        # case is ignored
        admin_context = context.RequestContext('admin',
                                               'fake',
                                               roles=['AdMiN'])
        policy.authorize(admin_context, lowercase_action, self.target)
        policy.authorize(admin_context, uppercase_action, self.target)

    @mock.patch.object(policy.LOG, 'warning')
    def test_warning_when_deprecated_user_based_rule_used(self, mock_warning):
        policy._warning_for_deprecated_user_based_rules(
            [("os_compute_api:servers:index",
                "project_id:%(project_id)s or user_id:%(user_id)s")])
        mock_warning.assert_called_once_with(
            u"The user_id attribute isn't supported in the rule "
             "'%s'. All the user_id based policy enforcement will be removed "
             "in the future.", "os_compute_api:servers:index")

    @mock.patch.object(policy.LOG, 'warning')
    def test_no_warning_for_user_based_resource(self, mock_warning):
        policy._warning_for_deprecated_user_based_rules(
            [("os_compute_api:os-keypairs:index",
                "user_id:%(user_id)s")])
        mock_warning.assert_not_called()

    @mock.patch.object(policy.LOG, 'warning')
    def test_no_warning_for_no_user_based_rule(self, mock_warning):
        policy._warning_for_deprecated_user_based_rules(
            [("os_compute_api:servers:index",
                "project_id:%(project_id)s")])
        mock_warning.assert_not_called()

    @requests_mock.mock()
    def test_authorize_raise_invalid_scope(self, req_mock):
        req_mock.post('http://www.example.com/',
                      text='False')
        action = "example:get_http"
        target = {}
        with mock.patch('oslo_policy.policy.Enforcer.authorize') as auth_mock:
            auth_mock.side_effect = oslo_policy.InvalidScope(
                action, self.context.system_scope, 'invalid_scope')
            exc = self.assertRaises(exception.PolicyNotAuthorized,
                                    policy.authorize, self.context,
                                    action, target)
            self.assertEqual(
                "Policy doesn't allow %s to be performed." % action,
                exc.format_message())

    @mock.patch.object(policy.LOG, 'warning')
    def test_verify_deprecated_policy_using_old_action(self, mock_warning):

        old_policy = "old_action_not_default"
        new_policy = "new_action"
        default_rule = "rule:admin_api"

        using_old_action = policy.verify_deprecated_policy(
            old_policy, new_policy, default_rule, self.context)

        mock_warning.assert_called_once_with("Start using the new "
            "action '%(new_policy)s'. The existing action '%(old_policy)s' "
            "is being deprecated and will be removed in future release.",
            {'new_policy': new_policy, 'old_policy': old_policy})
        self.assertTrue(using_old_action)

    def test_verify_deprecated_policy_using_new_action(self):
        old_policy = "old_action_default"
        new_policy = "new_action"
        default_rule = "rule:admin_api"

        using_old_action = policy.verify_deprecated_policy(
            old_policy, new_policy, default_rule, self.context)

        self.assertFalse(using_old_action)


class IsAdminCheckTestCase(test.NoDBTestCase):
    def setUp(self):
        super(IsAdminCheckTestCase, self).setUp()
        # NOTE(gmann): We do not need to log policy warnings for unit
        # tests.
        policy.init(suppress_deprecation_warnings=True)

    def test_init_true(self):
        check = policy.IsAdminCheck('is_admin', 'True')

        self.assertEqual(check.kind, 'is_admin')
        self.assertEqual(check.match, 'True')
        self.assertTrue(check.expected)

    def test_init_false(self):
        check = policy.IsAdminCheck('is_admin', 'nottrue')

        self.assertEqual(check.kind, 'is_admin')
        self.assertEqual(check.match, 'False')
        self.assertFalse(check.expected)

    def test_call_true(self):
        check = policy.IsAdminCheck('is_admin', 'True')

        self.assertTrue(check('target', dict(is_admin=True),
                              policy._ENFORCER))
        self.assertFalse(check('target', dict(is_admin=False),
                               policy._ENFORCER))

    def test_call_false(self):
        check = policy.IsAdminCheck('is_admin', 'False')

        self.assertFalse(check('target', dict(is_admin=True),
                               policy._ENFORCER))
        self.assertTrue(check('target', dict(is_admin=False),
                              policy._ENFORCER))

    def test_check_is_admin(self):
        ctxt = context.RequestContext(
            user_id='fake-user', project_id='fake-project')
        with mock.patch('oslo_policy.policy.Enforcer.authorize') as mock_auth:
            result = policy.check_is_admin(ctxt)
        self.assertEqual(mock_auth.return_value, result)
        mock_auth.assert_called_once_with(
            'context_is_admin',
            {'user_id': 'fake-user', 'project_id': 'fake-project'},
            ctxt)


class AdminRolePolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(AdminRolePolicyTestCase, self).setUp()
        self.policy = self.useFixture(nova_fixtures.RoleBasedPolicyFixture())
        self.context = context.RequestContext('fake', 'fake', roles=['member'])
        self.actions = policy.get_rules().keys()
        self.target = {}

    def test_authorize_admin_actions_with_nonadmin_context_throws(self):
        """Check if non-admin context passed to admin actions throws
           Policy not authorized exception
        """
        for action in self.actions:
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                          self.context, action, self.target)


class RealRolePolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(RealRolePolicyTestCase, self).setUp()
        self.policy = self.useFixture(nova_fixtures.RealPolicyFixture())
        self.non_admin_context = context.RequestContext('fake', 'fake',
                                                        roles=['member'])
        self.admin_context = context.RequestContext('fake', 'fake', True,
                                                     roles=['member'])
        self.target = {}
        self.fake_policy = jsonutils.loads(fake_policy.policy_data)

        self.admin_only_rules = (
"compute:aggregates:images",
"compute:server:topology:host:index",
"network:attach_external_network",
"os_compute_api:servers:create:forced_host",
"compute:servers:create:requested_destination",
"os_compute_api:servers:detail:get_all_tenants",
"os_compute_api:servers:index:get_all_tenants",
"os_compute_api:servers:allow_all_filters",
"os_compute_api:servers:show:host_status",
"os_compute_api:servers:show:host_status:unknown-only",
"os_compute_api:servers:migrations:force_complete",
"os_compute_api:servers:migrations:delete",
"os_compute_api:os-admin-actions:inject_network_info",
"os_compute_api:os-admin-actions:reset_state",
"os_compute_api:os-aggregates:index",
"os_compute_api:os-aggregates:create",
"os_compute_api:os-aggregates:show",
"os_compute_api:os-aggregates:update",
"os_compute_api:os-aggregates:delete",
"os_compute_api:os-aggregates:add_host",
"os_compute_api:os-aggregates:remove_host",
"os_compute_api:os-aggregates:set_metadata",
"os_compute_api:os-evacuate",
"os_compute_api:os-extended-server-attributes",
"os_compute_api:os-flavor-access:remove_tenant_access",
"os_compute_api:os-flavor-access:add_tenant_access",
"os_compute_api:os-flavor-extra-specs:create",
"os_compute_api:os-flavor-extra-specs:update",
"os_compute_api:os-flavor-extra-specs:delete",
"os_compute_api:os-flavor-manage:create",
"os_compute_api:os-flavor-manage:update",
"os_compute_api:os-flavor-manage:delete",
"os_compute_api:os-hosts:update",
"os_compute_api:os-hosts:reboot",
"os_compute_api:os-hosts:shutdown",
"os_compute_api:os-hosts:start",
"os_compute_api:os-instance-actions:events",
"os_compute_api:os-lock-server:unlock:unlock_override",
"os_compute_api:os-migrate-server:migrate",
"os_compute_api:os-migrate-server:migrate_live",
"os_compute_api:os-quota-sets:update",
"os_compute_api:os-quota-sets:delete",
"os_compute_api:os-server-diagnostics",
"os_compute_api:os-server-groups:index:all_projects",
"os_compute_api:os-services:update",
"os_compute_api:os-services:delete",
"os_compute_api:os-shelve:shelve_offload",
"os_compute_api:os-availability-zone:detail",
"os_compute_api:os-assisted-volume-snapshots:create",
"os_compute_api:os-assisted-volume-snapshots:delete",
"os_compute_api:os-console-auth-tokens",
"os_compute_api:os-quota-class-sets:update",
"os_compute_api:os-server-external-events:create",
"os_compute_api:os-volumes-attachments:swap",
"os_compute_api:servers:create:zero_disk_flavor",
)

        self.admin_or_owner_rules = (
"compute:server:topology:index",
"os_compute_api:servers:start",
"os_compute_api:servers:stop",
"os_compute_api:servers:trigger_crash_dump",
"os_compute_api:os-create-backup",
"os_compute_api:ips:index",
"os_compute_api:ips:show",
"os_compute_api:os-keypairs:create",
"os_compute_api:os-keypairs:delete",
"os_compute_api:os-keypairs:index",
"os_compute_api:os-keypairs:show",
"os_compute_api:os-lock-server:lock",
"os_compute_api:os-lock-server:unlock",
"os_compute_api:os-pause-server:pause",
"os_compute_api:os-pause-server:unpause",
"os_compute_api:os-quota-sets:show",
"os_compute_api:os-quota-sets:detail",
"os_compute_api:server-metadata:index",
"os_compute_api:server-metadata:show",
"os_compute_api:server-metadata:delete",
"os_compute_api:server-metadata:create",
"os_compute_api:server-metadata:update",
"os_compute_api:server-metadata:update_all",
"os_compute_api:os-suspend-server:suspend",
"os_compute_api:os-suspend-server:resume",
"os_compute_api:servers:confirm_resize",
"os_compute_api:servers:create",
"os_compute_api:servers:create:attach_network",
"os_compute_api:servers:create:attach_volume",
"os_compute_api:servers:create:trusted_certs",
"os_compute_api:servers:create_image",
"os_compute_api:servers:delete",
"os_compute_api:servers:detail",
"os_compute_api:servers:index",
"os_compute_api:servers:reboot",
"os_compute_api:servers:rebuild",
"os_compute_api:servers:rebuild:trusted_certs",
"os_compute_api:servers:resize",
"os_compute_api:servers:revert_resize",
"os_compute_api:servers:show",
"os_compute_api:servers:update",
"os_compute_api:servers:create_image:allow_volume_backed",
"os_compute_api:os-admin-password",
"os_compute_api:os-attach-interfaces:create",
"os_compute_api:os-attach-interfaces:delete",
"os_compute_api:os-console-output",
"os_compute_api:os-remote-consoles",
"os_compute_api:os-deferred-delete:restore",
"os_compute_api:os-deferred-delete:force",
"os_compute_api:os-flavor-access",
"os_compute_api:os-flavor-extra-specs:index",
"os_compute_api:os-flavor-extra-specs:show",
"os_compute_api:os-floating-ips:add",
"os_compute_api:os-floating-ips:remove",
"os_compute_api:os-floating-ips:create",
"os_compute_api:os-floating-ips:delete",
"os_compute_api:os-multinic:add",
"os_compute_api:os-multinic:remove",
"os_compute_api:os-rescue",
"os_compute_api:os-unrescue",
"os_compute_api:os-security-groups:create",
"os_compute_api:os-security-groups:update",
"os_compute_api:os-security-groups:delete",
"os_compute_api:os-security-groups:rule:create",
"os_compute_api:os-security-groups:rule:delete",
"os_compute_api:os-security-groups:add",
"os_compute_api:os-security-groups:remove",
"os_compute_api:os-server-password:clear",
"os_compute_api:os-server-tags:delete",
"os_compute_api:os-server-tags:delete_all",
"os_compute_api:os-server-tags:update",
"os_compute_api:os-server-tags:update_all",
"os_compute_api:os-server-groups:index",
"os_compute_api:os-server-groups:show",
"os_compute_api:os-server-groups:create",
"os_compute_api:os-server-groups:delete",
"os_compute_api:os-server-groups:update",
"os_compute_api:os-shelve:shelve",
"os_compute_api:os-shelve:unshelve",
"os_compute_api:os-volumes:create",
"os_compute_api:os-volumes:delete",
"os_compute_api:os-volumes:snapshots:create",
"os_compute_api:os-volumes:snapshots:delete",
"os_compute_api:os-volumes-attachments:create",
"os_compute_api:os-volumes-attachments:delete",
"os_compute_api:os-volumes-attachments:update",
)

        self.allow_all_rules = (
"os_compute_api:os-quota-sets:defaults",
"os_compute_api:os-availability-zone:list",
"os_compute_api:limits",
"os_compute_api:extensions",
"os_compute_api:os-floating-ip-pools",
)

        self.system_reader_rules = (
"os_compute_api:os-tenant-networks:list",
"os_compute_api:os-tenant-networks:show",
"os_compute_api:os-baremetal-nodes:list",
"os_compute_api:os-baremetal-nodes:show",
"os_compute_api:servers:migrations:index",
"os_compute_api:servers:migrations:show",
"os_compute_api:os-simple-tenant-usage:list",
"os_compute_api:os-migrations:index",
"os_compute_api:os-services:list",
"os_compute_api:os-instance-actions:events:details",
"os_compute_api:os-instance-usage-audit-log:list",
"os_compute_api:os-instance-usage-audit-log:show",
"os_compute_api:os-hosts:list",
"os_compute_api:os-hosts:show",
"os_compute_api:os-hypervisors:list",
"os_compute_api:os-hypervisors:list-detail",
"os_compute_api:os-hypervisors:show",
"os_compute_api:os-hypervisors:statistics",
"os_compute_api:os-hypervisors:uptime",
"os_compute_api:os-hypervisors:search",
"os_compute_api:os-hypervisors:servers",
"os_compute_api:limits:other_project",
"os_compute_api:os-networks:list",
"os_compute_api:os-networks:show",
)

        self.system_reader_or_owner_rules = (
"os_compute_api:os-simple-tenant-usage:show",
"os_compute_api:os-security-groups:get",
"os_compute_api:os-security-groups:show",
"os_compute_api:os-security-groups:list",
"os_compute_api:os-volumes-attachments:index",
"os_compute_api:os-volumes-attachments:show",
"os_compute_api:os-attach-interfaces:list",
"os_compute_api:os-attach-interfaces:show",
"os_compute_api:os-instance-actions:list",
"os_compute_api:os-instance-actions:show",
"os_compute_api:os-server-password:show",
"os_compute_api:os-server-tags:index",
"os_compute_api:os-server-tags:show",
"os_compute_api:os-floating-ips:list",
"os_compute_api:os-floating-ips:show",
"os_compute_api:os-volumes:list",
"os_compute_api:os-volumes:detail",
"os_compute_api:os-volumes:show",
"os_compute_api:os-volumes:snapshots:show",
"os_compute_api:os-volumes:snapshots:list",
"os_compute_api:os-volumes:snapshots:detail",
)

        self.allow_nobody_rules = (
            servers_policy.CROSS_CELL_RESIZE,
        )

    def test_all_rules_in_sample_file(self):
        special_rules = ["context_is_admin", "admin_or_owner", "default"]
        for (name, rule) in self.fake_policy.items():
            if name in special_rules:
                continue
            self.assertIn(name, policy.get_rules())

    def test_admin_only_rules(self):
        for rule in self.admin_only_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                              self.non_admin_context, rule,
                              {'project_id': 'fake', 'user_id': 'fake'})
            policy.authorize(self.admin_context, rule, self.target)

    def test_admin_or_owner_rules(self):
        for rule in self.admin_or_owner_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                              self.non_admin_context, rule, self.target)
            policy.authorize(self.non_admin_context, rule,
                           {'project_id': 'fake', 'user_id': 'fake'})

    def test_allow_all_rules(self):
        for rule in self.allow_all_rules:
            policy.authorize(self.non_admin_context, rule, self.target)

    def test_allow_nobody_rules(self):
        """No one can perform these operations, not even admin."""
        for rule in self.allow_nobody_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                              self.admin_context, rule, self.target)

    def test_rule_missing(self):
        rules = policy.get_rules()
        # eliqiao os_compute_api:os-quota-class-sets:show requires
        # admin=True or quota_class match, this rule won't belong to
        # admin_only, non_admin, admin_or_user, empty_rule
        special_rules = ('admin_api', 'admin_or_owner', 'context_is_admin',
                         'os_compute_api:os-quota-class-sets:show',
                         'system_admin_api', 'system_reader_api',
                         'project_admin_api', 'project_member_api',
                         'project_reader_api', 'system_admin_or_owner',
                         'system_or_project_reader')
        result = set(rules.keys()) - set(self.admin_only_rules +
            self.admin_or_owner_rules +
            self.allow_all_rules + self.system_reader_rules +
            self.system_reader_or_owner_rules +
            self.allow_nobody_rules + special_rules)
        self.assertEqual(set([]), result)

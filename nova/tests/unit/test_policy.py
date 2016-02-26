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

from oslo_policy import policy as oslo_policy
from oslo_serialization import jsonutils
import requests_mock

from nova import context
from nova import exception
from nova import policy
from nova import test
from nova.tests.unit import fake_policy
from nova.tests.unit import policy_fixture
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

            # NOTE(uni): context construction invokes policy check to determin
            # is_admin or not. As a side-effect, policy reset is needed here
            # to flush existing policy cache.
            policy.reset()

            action = "example:test"
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": ""}')
            policy.enforce(self.context, action, self.target)
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('{"example:test": "!"}')
            policy._ENFORCER.load_rules(True)
            self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                              self.context, action, self.target)


class PolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(PolicyTestCase, self).setUp()
        rules = {
            "true": '@',
            "example:allowed": '@',
            "example:denied": "!",
            "example:get_http": "http://www.example.com",
            "example:my_file": "role:compute_admin or "
                               "project_id:%(project_id)s",
            "example:early_and_fail": "! and @",
            "example:early_or_success": "@ or !",
            "example:lowercase_admin": "role:admin or role:sysadmin",
            "example:uppercase_admin": "role:ADMIN or role:sysadmin",
        }
        policy.reset()
        policy.init()
        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.context = context.RequestContext('fake', 'fake', roles=['member'])
        self.target = {}

    def test_enforce_nonexistent_action_throws(self):
        action = "example:noexist"
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, self.target)

    def test_enforce_bad_action_throws(self):
        action = "example:denied"
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, self.target)

    def test_enforce_bad_action_noraise(self):
        action = "example:denied"
        result = policy.enforce(self.context, action, self.target, False)
        self.assertFalse(result)

    def test_enforce_good_action(self):
        action = "example:allowed"
        result = policy.enforce(self.context, action, self.target)
        self.assertTrue(result)

    @requests_mock.mock()
    def test_enforce_http_true(self, req_mock):
        req_mock.post('http://www.example.com/',
                      text='True')
        action = "example:get_http"
        target = {}
        result = policy.enforce(self.context, action, target)
        self.assertTrue(result)

    @requests_mock.mock()
    def test_enforce_http_false(self, req_mock):
        req_mock.post('http://www.example.com/',
                      text='False')
        action = "example:get_http"
        target = {}
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, target)

    def test_templatized_enforcement(self):
        target_mine = {'project_id': 'fake'}
        target_not_mine = {'project_id': 'another'}
        action = "example:my_file"
        policy.enforce(self.context, action, target_mine)
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, target_not_mine)

    def test_early_AND_enforcement(self):
        action = "example:early_and_fail"
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, self.target)

    def test_early_OR_enforcement(self):
        action = "example:early_or_success"
        policy.enforce(self.context, action, self.target)

    def test_ignore_case_role_check(self):
        lowercase_action = "example:lowercase_admin"
        uppercase_action = "example:uppercase_admin"
        # NOTE(dprince) we mix case in the Admin role here to ensure
        # case is ignored
        admin_context = context.RequestContext('admin',
                                               'fake',
                                               roles=['AdMiN'])
        policy.enforce(admin_context, lowercase_action, self.target)
        policy.enforce(admin_context, uppercase_action, self.target)


class DefaultPolicyTestCase(test.NoDBTestCase):

    def setUp(self):
        super(DefaultPolicyTestCase, self).setUp()

        self.rules = {
            "default": '',
            "example:exist": "!",
        }

        self._set_rules('default')

        self.context = context.RequestContext('fake', 'fake')

    def _set_rules(self, default_rule):
        policy.reset()
        rules = oslo_policy.Rules.from_dict(self.rules)
        policy.init(rules=rules, default_rule=default_rule, use_conf=False)

    def test_policy_called(self):
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                self.context, "example:exist", {})

    def test_not_found_policy_calls_default(self):
        policy.enforce(self.context, "example:noexist", {})

    def test_default_not_found(self):
        self._set_rules("default_noexist")
        self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                self.context, "example:noexist", {})


class IsAdminCheckTestCase(test.NoDBTestCase):
    def setUp(self):
        super(IsAdminCheckTestCase, self).setUp()
        policy.init()

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

        self.assertEqual(check('target', dict(is_admin=True),
                               policy._ENFORCER), True)
        self.assertEqual(check('target', dict(is_admin=False),
                               policy._ENFORCER), False)

    def test_call_false(self):
        check = policy.IsAdminCheck('is_admin', 'False')

        self.assertEqual(check('target', dict(is_admin=True),
                               policy._ENFORCER), False)
        self.assertEqual(check('target', dict(is_admin=False),
                               policy._ENFORCER), True)


class AdminRolePolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(AdminRolePolicyTestCase, self).setUp()
        self.policy = self.useFixture(policy_fixture.RoleBasedPolicyFixture())
        self.context = context.RequestContext('fake', 'fake', roles=['member'])
        self.actions = policy.get_rules().keys()
        self.target = {}

    def test_enforce_admin_actions_with_nonadmin_context_throws(self):
        """Check if non-admin context passed to admin actions throws
           Policy not authorized exception
        """
        for action in self.actions:
            self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                          self.context, action, self.target)


class RealRolePolicyTestCase(test.NoDBTestCase):
    def setUp(self):
        super(RealRolePolicyTestCase, self).setUp()
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())
        self.non_admin_context = context.RequestContext('fake', 'fake',
                                                        roles=['member'])
        self.admin_context = context.RequestContext('fake', 'fake', True,
                                                     roles=['member'])
        self.target = {}
        self.fake_policy = jsonutils.loads(fake_policy.policy_data)

        self.admin_only_rules = (
"cells_scheduler_filter:TargetCellFilter",
"compute:unlock_override",
"compute:get_all_tenants",
"compute:create:forced_host",
"compute_extension:accounts",
"compute_extension:admin_actions",
"compute_extension:admin_actions:resetNetwork",
"compute_extension:admin_actions:injectNetworkInfo",
"compute_extension:admin_actions:migrateLive",
"compute_extension:admin_actions:resetState",
"compute_extension:admin_actions:migrate",
"compute_extension:aggregates",
"compute_extension:agents",
"compute_extension:baremetal_nodes",
"compute_extension:cells",
"compute_extension:cells:create",
"compute_extension:cells:delete",
"compute_extension:cells:update",
"compute_extension:cells:sync_instances",
"compute_extension:cloudpipe",
"compute_extension:cloudpipe_update",
"compute_extension:evacuate",
"compute_extension:extended_server_attributes",
"compute_extension:fixed_ips",
"compute_extension:flavor_access:addTenantAccess",
"compute_extension:flavor_access:removeTenantAccess",
"compute_extension:flavorextraspecs:create",
"compute_extension:flavorextraspecs:update",
"compute_extension:flavorextraspecs:delete",
"compute_extension:flavormanage",
"compute_extension:floating_ips_bulk",
"compute_extension:fping:all_tenants",
"compute_extension:hosts",
"compute_extension:hypervisors",
"compute_extension:instance_actions:events",
"compute_extension:instance_usage_audit_log",
"compute_extension:networks",
"compute_extension:networks_associate",
"compute_extension:quotas:update",
"compute_extension:quotas:delete",
"compute_extension:security_group_default_rules",
"compute_extension:server_diagnostics",
"compute_extension:services",
"compute_extension:shelveOffload",
"compute_extension:simple_tenant_usage:list",
"compute_extension:users",
"compute_extension:availability_zone:detail",
"compute_extension:used_limits_for_admin",
"compute_extension:migrations:index",
"compute_extension:os-assisted-volume-snapshots:create",
"compute_extension:os-assisted-volume-snapshots:delete",
"compute_extension:console_auth_tokens",
"compute_extension:os-server-external-events:create",
"os_compute_api:servers:create:forced_host",
"os_compute_api:servers:detail:get_all_tenants",
"os_compute_api:servers:index:get_all_tenants",
"os_compute_api:servers:show:host_status",
"os_compute_api:servers:migrations:force_complete",
"os_compute_api:servers:migrations:delete",
"network:attach_external_network",
"os_compute_api:os-admin-actions",
"os_compute_api:os-admin-actions:reset_network",
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
"os_compute_api:os-agents",
"os_compute_api:os-baremetal-nodes",
"os_compute_api:os-cells",
"os_compute_api:os-cells:create",
"os_compute_api:os-cells:delete",
"os_compute_api:os-cells:update",
"os_compute_api:os-cells:sync_instances",
"os_compute_api:os-cloudpipe",
"os_compute_api:os-evacuate",
"os_compute_api:os-extended-server-attributes",
"os_compute_api:os-fixed-ips",
"os_compute_api:os-flavor-access:remove_tenant_access",
"os_compute_api:os-flavor-access:add_tenant_access",
"os_compute_api:os-flavor-extra-specs:create",
"os_compute_api:os-flavor-extra-specs:update",
"os_compute_api:os-flavor-extra-specs:delete",
"os_compute_api:os-flavor-manage",
"os_compute_api:os-floating-ips-bulk",
"os_compute_api:os-floating-ip-dns:domain:delete",
"os_compute_api:os-floating-ip-dns:domain:update",
"os_compute_api:os-fping:all_tenants",
"os_compute_api:os-hosts",
"os_compute_api:os-hypervisors",
"os_compute_api:os-instance-actions:events",
"os_compute_api:os-instance-usage-audit-log",
"os_compute_api:os-lock-server:unlock:unlock_override",
"os_compute_api:os-migrate-server:migrate",
"os_compute_api:os-migrate-server:migrate_live",
"os_compute_api:os-networks",
"os_compute_api:os-networks-associate",
"os_compute_api:os-pci:index",
"os_compute_api:os-pci:detail",
"os_compute_api:os-pci:show",
"os_compute_api:os-quota-sets:update",
"os_compute_api:os-quota-sets:delete",
"os_compute_api:os-quota-sets:detail",
"os_compute_api:os-security-group-default-rules",
"os_compute_api:os-server-diagnostics",
"os_compute_api:os-services",
"os_compute_api:os-shelve:shelve_offload",
"os_compute_api:os-simple-tenant-usage:list",
"os_compute_api:os-availability-zone:detail",
"os_compute_api:os-used-limits",
"os_compute_api:os-migrations:index",
"os_compute_api:os-assisted-volume-snapshots:create",
"os_compute_api:os-assisted-volume-snapshots:delete",
"os_compute_api:os-console-auth-tokens",
"os_compute_api:os-quota-class-sets:update",
"os_compute_api:os-server-external-events:create",
"os_compute_api:servers:migrations:index",
"os_compute_api:servers:migrations:show",
)

        self.admin_or_owner_rules = (
"default",
"compute:start",
"compute:stop",
"compute:delete",
"compute:soft_delete",
"compute:force_delete",
"compute:lock",
"compute:unlock",
"compute_extension:admin_actions:pause",
"compute_extension:admin_actions:unpause",
"compute_extension:admin_actions:suspend",
"compute_extension:admin_actions:resume",
"compute_extension:admin_actions:lock",
"compute_extension:admin_actions:unlock",
"compute_extension:admin_actions:createBackup",
"compute_extension:simple_tenant_usage:show",
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
"os_compute_api:server-metadata:index",
"os_compute_api:server-metadata:show",
"os_compute_api:server-metadata:delete",
"os_compute_api:server-metadata:create",
"os_compute_api:server-metadata:update",
"os_compute_api:server-metadata:update_all",
"os_compute_api:os-simple-tenant-usage:show",
"os_compute_api:os-suspend-server:suspend",
"os_compute_api:os-suspend-server:resume",
"os_compute_api:os-tenant-networks",
"compute:create",
"compute:create:attach_network",
"compute:create:attach_volume",
"compute:get_all_instance_metadata",
"compute:get_all_instance_system_metadata",
"compute:get_console_output",
"compute:get_diagnostics",
"compute:delete_instance_metadata",
"compute:get",
"compute:get_all",
"compute:shelve",
"compute:shelve_offload",
"compute:snapshot_volume_backed",
"compute:unshelve",
"compute:resize",
"compute:confirm_resize",
"compute:revert_resize",
"compute:rebuild",
"compute:reboot",
"compute:volume_snapshot_create",
"compute:volume_snapshot_delete",
"compute:add_fixed_ip",
"compute:attach_interface",
"compute:detach_interface",
"compute:attach_volume",
"compute:detach_volume",
"compute:backup",
"compute:get_instance_diagnostics",
"compute:get_instance_metadata",
"compute:get_mks_console",
"compute:get_rdp_console",
"compute:get_serial_console",
"compute:get_spice_console",
"compute:get_vnc_console",
"compute:inject_network_info",
"compute:pause",
"compute:remove_fixed_ip",
"compute:rescue",
"compute:reset_network",
"compute:restore",
"compute:resume",
"compute:security_groups:add_to_instance",
"compute:security_groups:remove_from_instance",
"compute:set_admin_password",
"compute:snapshot",
"compute:suspend",
"compute:swap_volume",
"compute:unpause",
"compute:unrescue",
"compute:update",
"compute:update_instance_metadata",
"compute_extension:config_drive",
"compute_extension:os-tenant-networks",
"network:get_vif_by_mac_address",
"os_compute_api:extensions",
"os_compute_api:os-config-drive",
"os_compute_api:servers:confirm_resize",
"os_compute_api:servers:create",
"os_compute_api:servers:create:attach_network",
"os_compute_api:servers:create:attach_volume",
"os_compute_api:servers:create_image",
"os_compute_api:servers:delete",
"os_compute_api:servers:detail",
"os_compute_api:servers:index",
"os_compute_api:servers:reboot",
"os_compute_api:servers:rebuild",
"os_compute_api:servers:resize",
"os_compute_api:servers:revert_resize",
"os_compute_api:servers:show",
"os_compute_api:servers:update",
"compute_extension:attach_interfaces",
"compute_extension:certificates",
"compute_extension:console_output",
"compute_extension:consoles",
"compute_extension:createserverext",
"compute_extension:deferred_delete",
"compute_extension:disk_config",
"compute_extension:extended_status",
"compute_extension:extended_availability_zone",
"compute_extension:extended_ips",
"compute_extension:extended_ips_mac",
"compute_extension:extended_vif_net",
"compute_extension:extended_volumes",
"compute_extension:flavor_access",
"compute_extension:flavor_disabled",
"compute_extension:flavor_rxtx",
"compute_extension:flavor_swap",
"compute_extension:flavorextradata",
"compute_extension:flavorextraspecs:index",
"compute_extension:flavorextraspecs:show",
"compute_extension:floating_ip_dns",
"compute_extension:floating_ip_pools",
"compute_extension:floating_ips",
"compute_extension:fping",
"compute_extension:image_size",
"compute_extension:instance_actions",
"compute_extension:keypairs",
"compute_extension:keypairs:index",
"compute_extension:keypairs:show",
"compute_extension:keypairs:create",
"compute_extension:keypairs:delete",
"compute_extension:multinic",
"compute_extension:networks:view",
"compute_extension:quotas:show",
"compute_extension:quota_classes",
"compute_extension:rescue",
"compute_extension:security_groups",
"compute_extension:server_groups",
"compute_extension:server_password",
"compute_extension:server_usage",
"compute_extension:shelve",
"compute_extension:unshelve",
"compute_extension:virtual_interfaces",
"compute_extension:virtual_storage_arrays",
"compute_extension:volumes",
"compute_extension:volume_attachments:index",
"compute_extension:volume_attachments:show",
"compute_extension:volume_attachments:create",
"compute_extension:volume_attachments:update",
"compute_extension:volume_attachments:delete",
"compute_extension:volumetypes",
"compute_extension:availability_zone:list",
"network:get_all",
"network:get",
"network:create",
"network:delete",
"network:associate",
"network:disassociate",
"network:get_vifs_by_instance",
"network:allocate_for_instance",
"network:deallocate_for_instance",
"network:validate_networks",
"network:get_instance_uuids_by_ip_filter",
"network:get_instance_id_by_floating_address",
"network:setup_networks_on_host",
"network:get_backdoor_port",
"network:get_floating_ip",
"network:get_floating_ip_pools",
"network:get_floating_ip_by_address",
"network:get_floating_ips_by_project",
"network:get_floating_ips_by_fixed_address",
"network:allocate_floating_ip",
"network:associate_floating_ip",
"network:disassociate_floating_ip",
"network:release_floating_ip",
"network:migrate_instance_start",
"network:migrate_instance_finish",
"network:get_fixed_ip",
"network:get_fixed_ip_by_address",
"network:add_fixed_ip_to_instance",
"network:remove_fixed_ip_from_instance",
"network:add_network_to_project",
"network:get_instance_nw_info",
"network:get_dns_domains",
"network:add_dns_entry",
"network:modify_dns_entry",
"network:delete_dns_entry",
"network:get_dns_entries_by_address",
"network:get_dns_entries_by_name",
"network:create_private_dns_domain",
"network:create_public_dns_domain",
"network:delete_dns_domain",
"os_compute_api:servers:create_image:allow_volume_backed",
"os_compute_api:os-access-ips",
"os_compute_api:os-admin-password",
"os_compute_api:os-attach-interfaces",
"os_compute_api:os-certificates:create",
"os_compute_api:os-certificates:show",
"os_compute_api:os-consoles:create",
"os_compute_api:os-consoles:delete",
"os_compute_api:os-consoles:index",
"os_compute_api:os-consoles:show",
"os_compute_api:os-console-output",
"os_compute_api:os-remote-consoles",
"os_compute_api:os-deferred-delete",
"os_compute_api:os-disk-config",
"os_compute_api:os-extended-status",
"os_compute_api:os-extended-availability-zone",
"os_compute_api:os-extended-volumes",
"os_compute_api:os-flavor-access",
"os_compute_api:os-flavor-rxtx",
"os_compute_api:flavors",
"os_compute_api:os-flavor-extra-specs:index",
"os_compute_api:os-flavor-extra-specs:show",
"os_compute_api:os-floating-ip-dns",
"os_compute_api:os-floating-ip-pools",
"os_compute_api:os-floating-ips",
"os_compute_api:os-fping",
"os_compute_api:image-size",
"os_compute_api:os-instance-actions",
"os_compute_api:os-keypairs",
"os_compute_api:limits",
"os_compute_api:os-multinic",
"os_compute_api:os-networks:view",
"os_compute_api:os-pci:pci_servers",
"os_compute_api:os-rescue",
"os_compute_api:os-security-groups",
"os_compute_api:os-server-password",
"os_compute_api:os-server-usage",
"os_compute_api:os-server-groups",
"os_compute_api:os-shelve:shelve",
"os_compute_api:os-shelve:unshelve",
"os_compute_api:os-virtual-interfaces",
"os_compute_api:os-volumes",
"os_compute_api:os-volumes-attachments:index",
"os_compute_api:os-volumes-attachments:show",
"os_compute_api:os-volumes-attachments:create",
"os_compute_api:os-volumes-attachments:update",
"os_compute_api:os-volumes-attachments:delete",
"os_compute_api:os-availability-zone:list",
)

        self.non_admin_only_rules = (
"compute_extension:hide_server_addresses",
"os_compute_api:os-hide-server-addresses")

        self.allow_all_rules = (
"os_compute_api:os-quota-sets:defaults",
"os_compute_api:extensions:discoverable",
"os_compute_api:os-access-ips:discoverable",
"os_compute_api:os-admin-actions:discoverable",
"os_compute_api:os-admin-password:discoverable",
"os_compute_api:os-aggregates:discoverable",
"os_compute_api:os-agents:discoverable",
"os_compute_api:os-attach-interfaces:discoverable",
"os_compute_api:os-baremetal-nodes:discoverable",
"os_compute_api:os-block-device-mapping-v1:discoverable",
"os_compute_api:os-cells:discoverable",
"os_compute_api:os-certificates:discoverable",
"os_compute_api:os-cloudpipe:discoverable",
"os_compute_api:os-consoles:discoverable",
"os_compute_api:os-console-output:discoverable",
"os_compute_api:os-remote-consoles:discoverable",
"os_compute_api:os-create-backup:discoverable",
"os_compute_api:os-deferred-delete:discoverable",
"os_compute_api:os-disk-config:discoverable",
"os_compute_api:os-evacuate:discoverable",
"os_compute_api:os-extended-server-attributes:discoverable",
"os_compute_api:os-extended-status:discoverable",
"os_compute_api:os-extended-availability-zone:discoverable",
"os_compute_api:extension_info:discoverable",
"os_compute_api:os-extended-volumes:discoverable",
"os_compute_api:os-fixed-ips:discoverable",
"os_compute_api:os-flavor-access:discoverable",
"os_compute_api:os-flavor-rxtx:discoverable",
"os_compute_api:flavors:discoverable",
"os_compute_api:os-flavor-extra-specs:discoverable",
"os_compute_api:os-flavor-manage:discoverable",
"os_compute_api:os-floating-ip-dns:discoverable",
"os_compute_api:os-floating-ip-pools:discoverable",
"os_compute_api:os-floating-ips:discoverable",
"os_compute_api:os-floating-ips-bulk:discoverable",
"os_compute_api:os-fping:discoverable",
"os_compute_api:os-hide-server-addresses:discoverable",
"os_compute_api:os-hosts:discoverable",
"os_compute_api:os-hypervisors:discoverable",
"os_compute_api:images:discoverable",
"os_compute_api:image-size:discoverable",
"os_compute_api:os-instance-actions:discoverable",
"os_compute_api:os-instance-usage-audit-log:discoverable",
"os_compute_api:ips:discoverable",
"os_compute_api:os-keypairs:discoverable",
"os_compute_api:limits:discoverable",
"os_compute_api:os-lock-server:discoverable",
"os_compute_api:os-migrate-server:discoverable",
"os_compute_api:os-multinic:discoverable",
"os_compute_api:os-networks:discoverable",
"os_compute_api:os-networks-associate:discoverable",
"os_compute_api:os-pause-server:discoverable",
"os_compute_api:os-pci:discoverable",
"os_compute_api:os-personality:discoverable",
"os_compute_api:os-preserve-ephemeral-rebuild:discoverable",
"os_compute_api:os-quota-sets:discoverable",
"os_compute_api:os-quota-class-sets:discoverable",
"os_compute_api:os-rescue:discoverable",
"os_compute_api:os-scheduler-hints:discoverable",
"os_compute_api:os-security-group-default-rules:discoverable",
"os_compute_api:os-security-groups:discoverable",
"os_compute_api:os-server-diagnostics:discoverable",
"os_compute_api:os-server-password:discoverable",
"os_compute_api:os-server-usage:discoverable",
"os_compute_api:os-server-groups:discoverable",
"os_compute_api:os-services:discoverable",
"os_compute_api:server-metadata:discoverable",
"os_compute_api:servers:discoverable",
"os_compute_api:os-shelve:shelve:discoverable",
"os_compute_api:os-simple-tenant-usage:discoverable",
"os_compute_api:os-suspend-server:discoverable",
"os_compute_api:os-tenant-networks:discoverable",
"os_compute_api:os-user-data:discoverable",
"os_compute_api:os-virtual-interfaces:discoverable",
"os_compute_api:os-volumes:discoverable",
"os_compute_api:os-volumes-attachments:discoverable",
"os_compute_api:os-availability-zone:discoverable",
"os_compute_api:os-used-limits:discoverable",
"os_compute_api:os-migrations:discoverable",
"os_compute_api:os-assisted-volume-snapshots:discoverable",
)

    def test_all_rules_in_sample_file(self):
        special_rules = ["context_is_admin", "admin_or_owner", "default"]
        for (name, rule) in self.fake_policy.items():
            if name in special_rules:
                continue
            self.assertIn(name, policy.get_rules())

    def test_admin_only_rules(self):
        for rule in self.admin_only_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                              self.non_admin_context, rule, self.target)
            policy.enforce(self.admin_context, rule, self.target)

    def test_non_admin_only_rules(self):
        for rule in self.non_admin_only_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                              self.admin_context, rule, self.target)
            policy.enforce(self.non_admin_context, rule, self.target)

    def test_admin_or_owner_rules(self):
        for rule in self.admin_or_owner_rules:
            self.assertRaises(exception.PolicyNotAuthorized, policy.enforce,
                              self.non_admin_context, rule, self.target)
            policy.enforce(self.non_admin_context, rule,
                           {'project_id': 'fake', 'user_id': 'fake'})

    def test_no_empty_rules(self):
        rules = policy.get_rules()
        for rule in rules:
            self.assertNotEqual('', str(rule),
                    '%s should not be empty, use "@" instead if the policy '
                    'should allow everything' % rule)

    def test_allow_all_rules(self):
        for rule in self.allow_all_rules:
            policy.enforce(self.non_admin_context, rule, self.target)

    def test_rule_missing(self):
        rules = policy.get_rules()
        # eliqiao os_compute_api:os-quota-class-sets:show requires
        # admin=True or quota_class match, this rule won't belong to
        # admin_only, non_admin, admin_or_user, empty_rule
        special_rules = ('admin_api', 'admin_or_owner', 'context_is_admin',
                         'os_compute_api:os-quota-class-sets:show')
        result = set(rules.keys()) - set(self.admin_only_rules +
            self.admin_or_owner_rules + self.non_admin_only_rules +
            self.allow_all_rules + special_rules)
        self.assertEqual(set([]), result)

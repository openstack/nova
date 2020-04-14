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
from nova.api.openstack.compute import servers
from nova.compute import api as compute
from nova.compute import vm_states
from nova import exception
from nova.network import neutron
from nova import objects
from nova.objects import fields
from nova.objects.instance_group import InstanceGroup
from nova.policies import extended_server_attributes as ea_policies
from nova.policies import servers as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class ServersPolicyTest(base.BasePolicyTest):
    """Test Servers APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServersPolicyTest, self).setUp()
        self.controller = servers.ServersController()
        self.m_controller = migrate_server.MigrateServerController()
        self.rule_trusted_certs = policies.SERVERS % 'create:trusted_certs'
        self.rule_attach_network = policies.SERVERS % 'create:attach_network'
        self.rule_attach_volume = policies.SERVERS % 'create:attach_volume'
        self.rule_requested_destination = policies.REQUESTED_DESTINATION
        self.rule_forced_host = policies.SERVERS % 'create:forced_host'

        self.req = fakes.HTTPRequest.blank('')
        user_id = self.req.environ['nova.context'].user_id

        self.controller._view_builder._add_security_grps = mock.MagicMock()
        self.controller._view_builder._get_metadata = mock.MagicMock()
        self.controller._view_builder._get_addresses = mock.MagicMock()
        self.controller._view_builder._get_host_id = mock.MagicMock()
        self.controller._view_builder._get_fault = mock.MagicMock()

        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                user_id=user_id, vm_state=vm_states.ACTIVE,
                system_metadata={}, expected_attrs=['system_metadata'])

        self.mock_flavor = self.useFixture(
            fixtures.MockPatch('nova.compute.flavors.get_flavor_by_flavor_id'
                )).mock
        self.mock_flavor.return_value = fake_flavor.fake_flavor_obj(
                self.req.environ['nova.context'], flavorid='1')

        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.mock_get.return_value = self.instance

        self.mock_get_instance = self.useFixture(fixtures.MockPatchObject(
            self.controller, '_get_instance')).mock
        self.mock_get_instance.return_value = self.instance

        self.servers = [fakes.stub_instance_obj(
            1, vm_state=vm_states.ACTIVE, uuid=uuids.fake,
            project_id=self.project_id, user_id='user1'),
                        fakes.stub_instance_obj(
            2, vm_state=vm_states.ACTIVE, uuid=uuids.fake,
            project_id='proj2', user_id='user2')]
        fakes.stub_out_secgroup_api(
            self, security_groups=[{'name': 'default'}])
        self.mock_get_all = self.useFixture(fixtures.MockPatchObject(
            self.controller.compute_api, 'get_all')).mock
        self.body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
            },
        }
        self.extended_attr = ['OS-EXT-SRV-ATTR:host',
            'OS-EXT-SRV-ATTR:hypervisor_hostname',
            'OS-EXT-SRV-ATTR:instance_name',
            'OS-EXT-SRV-ATTR:hostname',
            'OS-EXT-SRV-ATTR:kernel_id',
            'OS-EXT-SRV-ATTR:launch_index',
            'OS-EXT-SRV-ATTR:ramdisk_id',
            'OS-EXT-SRV-ATTR:reservation_id',
            'OS-EXT-SRV-ATTR:root_device_name',
            'OS-EXT-SRV-ATTR:user_data'
        ]

        # Check that admin or and owner is able to update, delete
        # or perform server action.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to update, delete
        # or perform server action.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

        # Check that system reader or owner is able to get
        # the server.
        self.system_reader_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.system_member_context,
            self.system_reader_context, self.project_foo_context
        ]
        self.system_reader_or_owner_unauthorized_contexts = [
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

        # Check that everyone is able to list their own server.
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context]
        self.everyone_unauthorized_contexts = [
        ]
        # Check that admin is able to create server with host request
        # and get server extended attributes or host status.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to create server with host request
        # and get server extended attributes or host status.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that sustem reader is able to list the server
        # for all projects.
        self.system_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system reader is not able to list the server
        # for all projects.
        self.system_reader_unauthorized_contexts = [
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that project member is able to create serve
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context, self.system_foo_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context]
        # Check that non-project member is not able to create server
        self.project_member_unauthorized_contexts = [
        ]
        # Check that project admin is able to create server with requested
        # destination.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-project admin is not able to create server with
        # requested destination
        self.project_admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that no one is able to resize cross cell.
        self.cross_cell_authorized_contexts = []
        self.cross_cell_unauthorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context]
        # Check that admin is able to access the zero disk flavor
        # and external network policies.
        self.zero_disk_external_net_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to caccess the zero disk flavor
        # and external network policies.
        self.zero_disk_external_net_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that admin is able to get server extended attributes
        # or host status.
        self.server_attr_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to get server extended attributes
        # or host status.
        self.server_attr_admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

    def test_index_server_policy(self):

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            if 'project_id' in search_opts or 'user_id' in search_opts:
                return objects.InstanceList(objects=self.servers)
            else:
                raise

        self.mock_get_all.side_effect = fake_get_all

        rule_name = policies.SERVERS % 'index'
        self.common_policy_check(
            self.everyone_authorized_contexts,
            self.everyone_unauthorized_contexts,
            rule_name,
            self.controller.index,
            self.req)

    def test_index_all_project_server_policy(self):
        # 'index' policy is checked before 'index:get_all_tenants' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'index'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = policies.SERVERS % 'index:get_all_tenants'
        req = fakes.HTTPRequest.blank('/servers?all_tenants')

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('project_id', search_opts)
            return objects.InstanceList(objects=self.servers)

        self.mock_get_all.side_effect = fake_get_all

        self.common_policy_check(self.system_reader_authorized_contexts,
                                 self.system_reader_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 req)

    @mock.patch('nova.compute.api.API.get_all')
    def test_detail_list_server_policy(self, mock_get):

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            if 'project_id' in search_opts or 'user_id' in search_opts:
                return objects.InstanceList(objects=self.servers)
            else:
                raise

        self.mock_get_all.side_effect = fake_get_all

        rule_name = policies.SERVERS % 'detail'
        self.common_policy_check(
            self.everyone_authorized_contexts,
            self.everyone_unauthorized_contexts,
            rule_name,
            self.controller.detail,
            self.req)

    def test_detail_list_all_project_server_policy(self):
        # 'detail' policy is checked before 'detail:get_all_tenants' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'detail'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = policies.SERVERS % 'detail:get_all_tenants'
        req = fakes.HTTPRequest.blank('/servers?all_tenants')

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('project_id', search_opts)
            return objects.InstanceList(objects=self.servers)

        self.mock_get_all.side_effect = fake_get_all

        self.common_policy_check(self.system_reader_authorized_contexts,
                                 self.system_reader_unauthorized_contexts,
                                 rule_name,
                                 self.controller.detail,
                                 req)

    def test_index_server_allow_all_filters_policy(self):
        # 'index' policy is checked before 'allow_all_filters' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'index'
        self.policy.set_rules({rule: "@"}, overwrite=False)

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            if context in self.system_reader_unauthorized_contexts:
                self.assertNotIn('host', search_opts)
            if context in self.system_reader_authorized_contexts:
                self.assertIn('host', search_opts)
            return objects.InstanceList(objects=self.servers)

        self.mock_get_all.side_effect = fake_get_all

        req = fakes.HTTPRequest.blank('/servers?host=1')
        rule_name = policies.SERVERS % 'allow_all_filters'
        self.common_policy_check(
            self.system_reader_authorized_contexts,
            self.system_reader_unauthorized_contexts,
            rule_name,
            self.controller.index,
            req, fatal=False)

    def test_detail_server_allow_all_filters_policy(self):
        # 'detail' policy is checked before 'allow_all_filters' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'detail'
        self.policy.set_rules({rule: "@"}, overwrite=False)

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            if context in self.system_reader_unauthorized_contexts:
                self.assertNotIn('host', search_opts)
            if context in self.system_reader_authorized_contexts:
                self.assertIn('host', search_opts)
            return objects.InstanceList(objects=self.servers)
        self.mock_get_all.side_effect = fake_get_all

        req = fakes.HTTPRequest.blank('/servers?host=1')
        rule_name = policies.SERVERS % 'allow_all_filters'
        self.common_policy_check(
            self.system_reader_authorized_contexts,
            self.system_reader_unauthorized_contexts,
            rule_name,
            self.controller.detail,
            req, fatal=False)

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    def test_show_server_policy(self, mock_bdm):
        rule_name = policies.SERVERS % 'show'
        self.common_policy_check(
            self.system_reader_or_owner_authorized_contexts,
            self.system_reader_or_owner_unauthorized_contexts,
            rule_name,
            self.controller.show,
            self.req, self.instance.uuid)

    @mock.patch('nova.compute.api.API.create')
    def test_create_server_policy(self, mock_create):
        mock_create.return_value = ([self.instance], '')
        rule_name = policies.SERVERS % 'create'
        self.common_policy_check(self.project_member_authorized_contexts,
                                 self.project_member_unauthorized_contexts,
                                 rule_name,
                                 self.controller.create,
                                 self.req, body=self.body)

    @mock.patch('nova.compute.api.API.create')
    @mock.patch('nova.compute.api.API.parse_availability_zone')
    def test_create_forced_host_server_policy(self, mock_az, mock_create):
        # 'create' policy is checked before 'create:forced_host' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        mock_create.return_value = ([self.instance], '')
        mock_az.return_value = ('test', 'host', None)
        self.common_policy_check(self.project_admin_authorized_contexts,
                                 self.project_admin_unauthorized_contexts,
                                 self.rule_forced_host,
                                 self.controller.create,
                                 self.req, body=self.body)

    @mock.patch('nova.compute.api.API.create')
    def test_create_attach_volume_server_policy(self, mock_create):
        # 'create' policy is checked before 'create:attach_volume' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        mock_create.return_value = ([self.instance], '')
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
                'block_device_mapping': [{'device_name': 'foo'}],
            },
        }
        self.common_policy_check(self.project_member_authorized_contexts,
                                 self.project_member_unauthorized_contexts,
                                 self.rule_attach_volume,
                                 self.controller.create,
                                 self.req, body=body)

    @mock.patch('nova.compute.api.API.create')
    def test_create_attach_network_server_policy(self, mock_create):
        # 'create' policy is checked before 'create:attach_network' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        mock_create.return_value = ([self.instance], '')
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
                'networks': [{
                    'uuid': uuids.fake_id
                }],
            },
        }
        self.common_policy_check(self.project_member_authorized_contexts,
                                 self.project_member_unauthorized_contexts,
                                 self.rule_attach_network,
                                 self.controller.create,
                                 self.req, body=body)

    @mock.patch('nova.compute.api.API.create')
    def test_create_trusted_certs_server_policy(self, mock_create):
        # 'create' policy is checked before 'create:trusted_certs' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.63')
        mock_create.return_value = ([self.instance], '')
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
                'trusted_image_certificates': [uuids.fake_id],
                'networks': [{
                    'uuid': uuids.fake_id
                }],

            },
        }
        self.common_policy_check(self.project_member_authorized_contexts,
                                 self.project_member_unauthorized_contexts,
                                 self.rule_trusted_certs,
                                 self.controller.create,
                                 req, body=body)

    @mock.patch('nova.compute.api.API.delete')
    def test_delete_server_policy(self, mock_delete):
        rule_name = policies.SERVERS % 'delete'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.delete,
                                 self.req, self.instance.uuid)

    def test_delete_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'delete'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller.delete,
            req, self.instance.uuid)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.delete')
    def test_delete_server_overridden_policy_pass_with_same_user(
        self, mock_delete):
        rule_name = policies.SERVERS % 'delete'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        self.controller.delete(self.req,
                               self.instance.uuid)

    @mock.patch('nova.compute.api.API.update_instance')
    def test_update_server_policy(self, mock_update):
        rule_name = policies.SERVERS % 'update'
        body = {'server': {'name': 'test'}}

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.update,
                                 self.req, self.instance.uuid, body=body)

    def test_update_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'update'
        body = {'server': {'name': 'test'}}
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller.update,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.update_instance')
    def test_update_server_overridden_policy_pass_with_same_user(
        self, mock_update):
        rule_name = policies.SERVERS % 'update'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        body = {'server': {'name': 'test'}}
        self.controller.update(self.req,
                               self.instance.uuid, body=body)

    @mock.patch('nova.compute.api.API.confirm_resize')
    def test_confirm_resize_server_policy(self, mock_confirm_resize):
        rule_name = policies.SERVERS % 'confirm_resize'

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_confirm_resize,
                                 self.req, self.instance.uuid,
                                 body={'confirmResize': 'null'})

    @mock.patch('nova.compute.api.API.revert_resize')
    def test_revert_resize_server_policy(self, mock_revert_resize):
        rule_name = policies.SERVERS % 'revert_resize'

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_revert_resize,
                                 self.req, self.instance.uuid,
                                 body={'revertResize': 'null'})

    @mock.patch('nova.compute.api.API.reboot')
    def test_reboot_server_policy(self, mock_reboot):
        rule_name = policies.SERVERS % 'reboot'

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_reboot,
                                 self.req, self.instance.uuid,
                                 body={'reboot': {'type': 'soft'}})

    @mock.patch('nova.api.openstack.common.'
            'instance_has_port_with_resource_request')
    @mock.patch('nova.compute.api.API.resize')
    def test_resize_server_policy(self, mock_resize, mock_port):
        rule_name = policies.SERVERS % 'resize'
        mock_port.return_value = False
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_resize,
                                 self.req, self.instance.uuid,
                                 body={'resize': {'flavorRef': 'f1'}})

    def test_resize_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'resize'
        body = {'resize': {'flavorRef': 'f1'}}
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._action_resize,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.api.openstack.common.'
            'instance_has_port_with_resource_request')
    @mock.patch('nova.compute.api.API.resize')
    def test_resize_server_overridden_policy_pass_with_same_user(
        self, mock_resize, mock_port):
        rule_name = policies.SERVERS % 'resize'
        mock_port.return_value = False
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        body = {'resize': {'flavorRef': 'f1'}}
        self.controller._action_resize(self.req,
                                       self.instance.uuid, body=body)

    @mock.patch('nova.compute.api.API.start')
    def test_start_server_policy(self, mock_start):
        rule_name = policies.SERVERS % 'start'

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._start_server,
                                 self.req, self.instance.uuid,
                                 body={'os-start': 'null'})

    @mock.patch('nova.compute.api.API.stop')
    def test_stop_server_policy(self, mock_stop):
        rule_name = policies.SERVERS % 'stop'

        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._stop_server,
                                 self.req, self.instance.uuid,
                                 body={'os-stop': 'null'})

    def test_stop_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'stop'
        body = {'os-stop': 'null'}
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._stop_server,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.stop')
    def test_stop_server_overridden_policy_pass_with_same_user(
        self, mock_stop):
        rule_name = policies.SERVERS % 'stop'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        body = {'os-stop': 'null'}
        self.controller._stop_server(self.req,
                                     self.instance.uuid, body=body)

    @mock.patch('nova.compute.api.API.rebuild')
    def test_rebuild_server_policy(self, mock_rebuild):
        rule_name = policies.SERVERS % 'rebuild'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_rebuild,
                                 self.req, self.instance.uuid,
                                 body={'rebuild': {"imageRef": uuids.fake_id}})

    def test_rebuild_server_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'rebuild'
        body = {'rebuild': {"imageRef": uuids.fake_id}}
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._action_rebuild,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.rebuild')
    def test_rebuild_server_overridden_policy_pass_with_same_user(
        self, mock_rebuild):
        rule_name = policies.SERVERS % 'rebuild'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        body = {'rebuild': {"imageRef": uuids.fake_id}}
        self.controller._action_rebuild(self.req,
                                        self.instance.uuid, body=body)

    @mock.patch('nova.compute.api.API.rebuild')
    def test_rebuild_trusted_certs_server_policy(self, mock_rebuild):
        # 'rebuild' policy is checked before 'rebuild:trusted_certs' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'rebuild'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.63')
        rule_name = policies.SERVERS % 'rebuild:trusted_certs'
        body = {
            'rebuild': {
                'imageRef': uuids.fake_id,
                'trusted_image_certificates': [uuids.fake_id],
            },
        }
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_rebuild,
                                 req, self.instance.uuid, body=body)

    def test_rebuild_trusted_certs_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('', version='2.63')
        req.environ['nova.context'].user_id = 'other-user'
        rule = policies.SERVERS % 'rebuild'
        rule_name = policies.SERVERS % 'rebuild:trusted_certs'
        body = {
            'rebuild': {
                'imageRef': uuids.fake_id,
                'trusted_image_certificates': [uuids.fake_id],
            },
        }
        self.policy.set_rules(
            {rule: "@",
             rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, self.controller._action_rebuild,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.rebuild')
    def test_rebuild_trusted_certs_overridden_policy_pass_with_same_user(
        self, mock_rebuild):
        req = fakes.HTTPRequest.blank('', version='2.63')
        rule = policies.SERVERS % 'rebuild'
        rule_name = policies.SERVERS % 'rebuild:trusted_certs'
        body = {
            'rebuild': {
                'imageRef': uuids.fake_id,
                'trusted_image_certificates': [uuids.fake_id],
            },
        }
        self.policy.set_rules(
            {rule: "@",
             rule_name: "user_id:%(user_id)s"}, overwrite=False)
        self.controller._action_rebuild(req,
                                        self.instance.uuid, body=body)

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.image.glance.API.generate_image_url')
    @mock.patch('nova.compute.api.API.snapshot_volume_backed')
    def test_create_image_server_policy(self, mock_snapshot, mock_image,
        mock_bdm):
        rule_name = policies.SERVERS % 'create_image'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_create_image,
                                 self.req, self.instance.uuid,
                                 body={'createImage': {"name": 'test'}})

    @mock.patch('nova.objects.BlockDeviceMappingList.get_by_instance_uuid')
    @mock.patch('nova.image.glance.API.generate_image_url')
    @mock.patch('nova.compute.api.API.snapshot_volume_backed')
    def test_create_image_allow_volume_backed_server_policy(self,
        mock_snapshot, mock_image, mock_bdm):
        # 'create_image' policy is checked before
        # 'create_image:allow_volume_backed' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create_image'
        self.policy.set_rules({rule: "@"}, overwrite=False)

        rule_name = policies.SERVERS % 'create_image:allow_volume_backed'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_create_image,
                                 self.req, self.instance.uuid,
                                 body={'createImage': {"name": 'test'}})

    @mock.patch('nova.compute.api.API.trigger_crash_dump')
    def test_trigger_crash_dump_server_policy(self, mock_crash):
        rule_name = policies.SERVERS % 'trigger_crash_dump'
        req = fakes.HTTPRequest.blank('', version='2.17')
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller._action_trigger_crash_dump,
                                 req, self.instance.uuid,
                                 body={'trigger_crash_dump': None})

    def test_trigger_crash_dump_policy_failed_with_other_user(self):
        # Change the user_id in request context.
        req = fakes.HTTPRequest.blank('', version='2.17')
        req.environ['nova.context'].user_id = 'other-user'
        rule_name = policies.SERVERS % 'trigger_crash_dump'
        body = {'trigger_crash_dump': None}
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._action_trigger_crash_dump,
            req, self.instance.uuid, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch('nova.compute.api.API.trigger_crash_dump')
    def test_trigger_crash_dump_overridden_policy_pass_with_same_user(
        self, mock_crash):
        req = fakes.HTTPRequest.blank('', version='2.17')
        rule_name = policies.SERVERS % 'trigger_crash_dump'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"},
            overwrite=False)
        body = {'trigger_crash_dump': None}
        self.controller._action_trigger_crash_dump(req,
            self.instance.uuid, body=body)

    def test_server_detail_with_extended_attr_policy(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            return objects.InstanceList(objects=self.servers)
        self.mock_get_all.side_effect = fake_get_all

        rule = policies.SERVERS % 'detail'
        # server 'detail' policy is checked before extended attributes
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.3')
        rule_name = ea_policies.BASE_POLICY_NAME
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.detail, req,
            fatal=False)
        for attr in self.extended_attr:
            for resp in authorize_res:
                self.assertIn(attr, resp['servers'][0])
            for resp in unauthorize_res:
                self.assertNotIn(attr, resp['servers'][0])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    def test_server_show_with_extended_attr_policy(self, mock_get, mock_block):
        rule = policies.SERVERS % 'show'
        # server 'show' policy is checked before extended attributes
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.3')
        rule_name = ea_policies.BASE_POLICY_NAME
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.show, req, 'fake',
            fatal=False)
        for attr in self.extended_attr:
            for resp in authorize_res:
                self.assertIn(attr, resp['server'])
            for resp in unauthorize_res:
                self.assertNotIn(attr, resp['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    @mock.patch('nova.compute.api.API.rebuild')
    def test_server_rebuild_with_extended_attr_policy(self, mock_rebuild,
        mock_get, mock_bdm):
        rule = policies.SERVERS % 'rebuild'
        # server 'rebuild' policy is checked before extended attributes
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = ea_policies.BASE_POLICY_NAME
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller._action_rebuild,
            req, self.instance.uuid,
            body={'rebuild': {"imageRef": uuids.fake_id}},
            fatal=False)
        for attr in self.extended_attr:
            # NOTE(gmann): user_data attribute is always present in
            # rebuild response since 2.47.
            if attr == 'OS-EXT-SRV-ATTR:user_data':
                continue
            for resp in authorize_res:
                self.assertIn(attr, resp.obj['server'])
            for resp in unauthorize_res:
                self.assertNotIn(attr, resp.obj['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch.object(InstanceGroup, 'get_by_instance_uuid')
    @mock.patch('nova.compute.api.API.update_instance')
    def test_server_update_with_extended_attr_policy(self,
        mock_update, mock_group, mock_bdm):
        rule = policies.SERVERS % 'update'
        # server 'update' policy is checked before extended attributes
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = ea_policies.BASE_POLICY_NAME
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.update,
            req, self.instance.uuid,
            body={'server': {'name': 'test'}},
            fatal=False)
        for attr in self.extended_attr:
            for resp in authorize_res:
                self.assertIn(attr, resp['server'])
            for resp in unauthorize_res:
                self.assertNotIn(attr, resp['server'])

    def test_server_detail_with_host_status_policy(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            return objects.InstanceList(objects=self.servers)
        self.mock_get_all.side_effect = fake_get_all

        rule = policies.SERVERS % 'detail'
        # server 'detail' policy is checked before host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.16')
        rule_name = policies.SERVERS % 'show:host_status'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.detail, req,
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['servers'][0])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['servers'][0])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    def test_server_show_with_host_status_policy(self,
        mock_status, mock_block):
        rule = policies.SERVERS % 'show'
        # server 'show' policy is checked before host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.16')
        rule_name = policies.SERVERS % 'show:host_status'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.show, req, 'fake',
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['server'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    @mock.patch('nova.compute.api.API.rebuild')
    def test_server_rebuild_with_host_status_policy(self, mock_rebuild,
        mock_status, mock_bdm):
        rule = policies.SERVERS % 'rebuild'
        # server 'rebuild' policy is checked before host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = policies.SERVERS % 'show:host_status'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller._action_rebuild,
            req, self.instance.uuid,
            body={'rebuild': {"imageRef": uuids.fake_id}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp.obj['server'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp.obj['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch.object(InstanceGroup, 'get_by_instance_uuid')
    @mock.patch('nova.compute.api.API.update_instance')
    def test_server_update_with_host_status_policy(self,
        mock_update, mock_group, mock_bdm):
        rule = policies.SERVERS % 'update'
        # server 'update' policy is checked before host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = policies.SERVERS % 'show:host_status'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.update,
            req, self.instance.uuid,
            body={'server': {'name': 'test'}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['server'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['server'])

    @mock.patch('nova.compute.api.API.get_instances_host_statuses')
    def test_server_detail_with_unknown_host_status_policy(self, mock_status):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            return objects.InstanceList(objects=self.servers)
        self.mock_get_all.side_effect = fake_get_all
        host_statuses = {}
        for server in self.servers:
            host_statuses.update({server.uuid: fields.HostStatus.UNKNOWN})
        mock_status.return_value = host_statuses
        rule = policies.SERVERS % 'detail'
        # server 'detail' policy is checked before unknown host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts. To verify the unknown host_status
        # policy we need to disallow host_status policy for everyone.
        rule_host_status = policies.SERVERS % 'show:host_status'
        self.policy.set_rules({
            rule: "@",
            rule_host_status: "!"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.16')
        rule_name = policies.SERVERS % 'show:host_status:unknown-only'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.detail, req,
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['servers'][0])
            self.assertEqual(fields.HostStatus.UNKNOWN,
                resp['servers'][0]['host_status'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['servers'][0])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    def test_server_show_with_unknown_host_status_policy(self,
        mock_status, mock_block):
        mock_status.return_value = fields.HostStatus.UNKNOWN
        rule = policies.SERVERS % 'show'
        # server 'show' policy is checked before unknown host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts. To verify the unknown host_status
        # policy we need to disallow host_status policy for everyone.
        rule_host_status = policies.SERVERS % 'show:host_status'
        self.policy.set_rules({
            rule: "@",
            rule_host_status: "!"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.16')
        rule_name = policies.SERVERS % 'show:host_status:unknown-only'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.show, req, 'fake',
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['server'])
            self.assertEqual(
                fields.HostStatus.UNKNOWN, resp['server']['host_status'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    @mock.patch('nova.compute.api.API.rebuild')
    def test_server_rebuild_with_unknown_host_status_policy(self, mock_rebuild,
        mock_status, mock_bdm):
        mock_status.return_value = fields.HostStatus.UNKNOWN
        rule = policies.SERVERS % 'rebuild'
        # server 'rebuild' policy is checked before unknown host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts. To verify the unknown host_status
        # policy we need to disallow host_status policy for everyone.
        rule_host_status = policies.SERVERS % 'show:host_status'
        self.policy.set_rules({
            rule: "@",
            rule_host_status: "!"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = policies.SERVERS % 'show:host_status:unknown-only'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller._action_rebuild,
            req, self.instance.uuid,
            body={'rebuild': {"imageRef": uuids.fake_id}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp.obj['server'])
            self.assertEqual(
                fields.HostStatus.UNKNOWN, resp.obj['server']['host_status'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp.obj['server'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    @mock.patch.object(InstanceGroup, 'get_by_instance_uuid')
    @mock.patch('nova.compute.api.API.update_instance')
    def test_server_update_with_unknown_host_status_policy(self,
        mock_update, mock_group, mock_status, mock_bdm):
        mock_status.return_value = fields.HostStatus.UNKNOWN
        rule = policies.SERVERS % 'update'
        # server 'update' policy is checked before unknown host_status
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts. To verify the unknown host_status
        # policy we need to disallow host_status policy for everyone.
        rule_host_status = policies.SERVERS % 'show:host_status'
        self.policy.set_rules({
            rule: "@",
            rule_host_status: "!"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.75')
        rule_name = policies.SERVERS % 'show:host_status:unknown-only'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.server_attr_admin_authorized_contexts,
            self.server_attr_admin_unauthorized_contexts,
            rule_name, self.controller.update,
            req, self.instance.uuid,
            body={'server': {'name': 'test'}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('host_status', resp['server'])
            self.assertEqual(
                fields.HostStatus.UNKNOWN, resp['server']['host_status'])
        for resp in unauthorize_res:
            self.assertNotIn('host_status', resp['server'])

    @mock.patch('nova.compute.api.API.create')
    def test_create_requested_destination_server_policy(self,
        mock_create):
        # 'create' policy is checked before 'create:requested_destination' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = policies.SERVERS % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.74')

        def fake_create(context, *args, **kwargs):
            for attr in ['requested_host', 'requested_hypervisor_hostname']:
                if context in self.project_admin_authorized_contexts:
                    self.assertIn(attr, kwargs)
                if context in self.project_admin_unauthorized_contexts:
                    self.assertNotIn(attr, kwargs)
            return ([self.instance], '')
        mock_create.side_effect = fake_create

        body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
                'networks': [{
                    'uuid': uuids.fake_id
                }],
                'host': 'fake',
                'hypervisor_hostname': 'fake'
            },
        }

        self.common_policy_check(self.project_admin_authorized_contexts,
                                 self.project_admin_unauthorized_contexts,
                                 self.rule_requested_destination,
                                 self.controller.create,
                                 req, body=body)

    @mock.patch('nova.compute.api.API._check_requested_networks')
    @mock.patch('nova.compute.api.API._allow_resize_to_same_host')
    @mock.patch('nova.objects.RequestSpec.get_by_instance_uuid')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch('nova.api.openstack.common.get_instance')
    @mock.patch('nova.api.openstack.common.'
        'instance_has_port_with_resource_request')
    @mock.patch('nova.conductor.ComputeTaskAPI.resize_instance')
    def test_cross_cell_resize_server_policy(self,
        mock_resize, mock_port, mock_get, mock_save, mock_rs,
        mock_allow, m_net):
        self.stub_out('nova.compute.api.API.get_instance_host_status',
            lambda x, y: "UP")

        # 'migrate' policy is checked before 'resize:cross_cell' so
        # we have to allow it for everyone otherwise it will
        # fail for unauthorized contexts here.
        rule = 'os_compute_api:os-migrate-server:migrate'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        rule_name = policies.CROSS_CELL_RESIZE
        mock_port.return_value = False
        req = fakes.HTTPRequest.blank('', version='2.56')

        def fake_get(*args, **kwargs):
            return fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                user_id='fake-user', vm_state=vm_states.ACTIVE,
                launched_at=timeutils.utcnow())

        mock_get.side_effect = fake_get

        def fake_validate(context, instance,
            host_name, allow_cross_cell_resize):
            if context in self.cross_cell_authorized_contexts:
                self.assertTrue(allow_cross_cell_resize)
            if context in self.cross_cell_unauthorized_contexts:
                self.assertFalse(allow_cross_cell_resize)
            return objects.ComputeNode(host=1, hypervisor_hostname=2)

        self.stub_out(
                'nova.compute.api.API._validate_host_for_cold_migrate',
                fake_validate)

        self.common_policy_check(self.cross_cell_authorized_contexts,
                                 self.cross_cell_unauthorized_contexts,
                                 rule_name,
                                 self.m_controller._migrate,
                                 req, self.instance.uuid,
                                 body={'migrate': {'host': 'fake'}},
                                 fatal=False)

    def test_network_attach_external_network_policy(self):
        # NOTE(gmann): Testing policy 'network:attach_external_network'
        # which raise different error then PolicyNotAuthorized
        # if not allowed.
        neutron_api = neutron.API()
        for context in self.zero_disk_external_net_authorized_contexts:
            neutron_api._check_external_network_attach(context,
                    [{'id': 1, 'router:external': 'ext'}])
        for context in self.zero_disk_external_net_unauthorized_contexts:
            self.assertRaises(exception.ExternalNetworkAttachForbidden,
                              neutron_api._check_external_network_attach,
                              context, [{'id': 1, 'router:external': 'ext'}])

    def test_zero_disk_flavor_policy(self):
        # NOTE(gmann): Testing policy 'create:zero_disk_flavor'
        # which raise different error then PolicyNotAuthorized
        # if not allowed.
        image = {'id': uuids.image_id, 'status': 'foo'}
        flavor = objects.Flavor(
            vcpus=1, memory_mb=512, root_gb=0, extra_specs={'hw:pmu': "true"})
        compute_api = compute.API()
        for context in self.zero_disk_external_net_authorized_contexts:
            compute_api._validate_flavor_image_nostatus(context,
                    image, flavor, None)
        for context in self.zero_disk_external_net_unauthorized_contexts:
            self.assertRaises(
                exception.BootFromVolumeRequiredForZeroDiskFlavor,
                compute_api._validate_flavor_image_nostatus,
                context, image, flavor, None)


class ServersScopeTypePolicyTest(ServersPolicyTest):
    """Test Servers APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServersScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # These policy are project scoped only and 'create' policy is checked
        # first so even we allow it for everyone the system scoped context
        # cannot validate these as they fail on 'create' policy due to
        # scope_type. So we need to set rule name as None to skip the policy
        # error message assertion in base class. These rule name are only used
        # for error message assertion.
        self.rule_trusted_certs = None
        self.rule_attach_network = None
        self.rule_attach_volume = None
        self.rule_requested_destination = None
        self.rule_forced_host = None

        # Check that system admin is able to create server with host request
        # and get server extended attributes or host status.
        self.admin_authorized_contexts = [
            self.system_admin_context
        ]
        # Check that non-system/admin is not able to create server with
        # host request and get server extended attributes or host status.
        self.admin_unauthorized_contexts = [
            self.project_admin_context, self.legacy_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that system reader is able to list the server
        # for all projects.
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system reader is not able to list the server
        # for all projects.
        self.system_reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

        # Check if project member can create the server.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_reader_context
        ]
        # Check if non-project member cannot create the server.
        self.project_member_unauthorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context
        ]

        # Check that project admin is able to create server with requested
        # destination.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context]
        # Check that non-project admin is not able to create server with
        # requested destination
        self.project_admin_unauthorized_contexts = [
            self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]


class ServersNoLegacyPolicyTest(ServersScopeTypePolicyTest):
    """Test Servers APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(ServersNoLegacyPolicyTest, self).setUp()

        # Check that system admin or owner is able to update, delete
        # or perform server action.
        self.admin_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.project_member_context,
        ]
        # Check that non-system and non-admin/owner is not able to update,
        # delete or perform server action.
        self.admin_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context]

        # Check that system reader or projct owner is able to get
        # server.
        self.system_reader_or_owner_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context,
        ]

        # Check that non-system reader nd non-admin/owner is not able to get
        # server.
        self.system_reader_or_owner_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.other_project_member_context,
            self.other_project_reader_context
        ]
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.system_member_context, self.system_reader_context,
            self.other_project_member_context
        ]
        self.everyone_unauthorized_contexts = [
            self.project_foo_context,
            self.system_foo_context
        ]
        # Check if project member can create the server.
        self.project_member_authorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context,
            self.other_project_member_context
        ]
        # Check if non-project member cannot create the server.
        self.project_member_unauthorized_contexts = [
            self.system_admin_context,
            self.system_member_context, self.project_reader_context,
            self.project_foo_context, self.other_project_reader_context,
            self.system_reader_context, self.system_foo_context
        ]
        # Check that system admin is able to get server extended attributes
        # or host status.
        self.server_attr_admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system admin is not able to get server extended
        # attributes or host status.
        self.server_attr_admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

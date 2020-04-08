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

from nova.api.openstack.compute import servers
from nova.compute import vm_states
from nova import exception
from nova import objects
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
                user_id=user_id, vm_state=vm_states.ACTIVE)

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

        # Check that admin or and owner is able to get and delete
        # the server.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context]
        # Check that non-admin/owner is not able to get and delete
        # the server.
        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

        # Check that everyone is able to list their own server.
        self.everyone_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context]
        self.everyone_unauthorized_contexts = [
        ]
        # Check that admin is able to list the server
        # for all projects.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to list the server
        # for all projects.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context
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
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req)

    def test_index_all_project_server_policy(self):
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

        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
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
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
                                 self.controller.detail,
                                 self.req)

    def test_detail_list_all_project_server_policy(self):
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

        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name,
                                 self.controller.detail,
                                 req)

    def test_index_server_allow_all_filters_policy(self):

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            if context in self.admin_unauthorized_contexts:
                self.assertNotIn('host', search_opts)
            if context in self.admin_authorized_contexts:
                self.assertIn('host', search_opts)
            return objects.InstanceList(objects=self.servers)

        self.mock_get_all.side_effect = fake_get_all

        req = fakes.HTTPRequest.blank('/servers?host=1')
        rule_name = policies.SERVERS % 'allow_all_filters'
        self.common_policy_check(
            self.admin_authorized_contexts,
            self.admin_unauthorized_contexts,
            rule_name,
            self.controller.index,
            req, fatal=False)

    def test_show_server_policy(self):
        rule_name = policies.SERVERS % 'show'
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name,
                                 self.controller.show,
                                 self.req, self.instance.uuid)

    @mock.patch('nova.compute.api.API.create')
    def test_create_server_policy(self, mock_create):
        mock_create.return_value = ([self.instance], '')
        rule_name = policies.SERVERS % 'create'
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
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
        rule_name = policies.SERVERS % 'create:forced_host'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name,
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
        rule_name = policies.SERVERS % 'create:attach_volume'
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': uuids.fake_id,
                'flavorRef': uuids.fake_id,
                'block_device_mapping': [{'device_name': 'foo'}],
            },
        }
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
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
        rule_name = policies.SERVERS % 'create:attach_network'
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
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
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
        rule_name = policies.SERVERS % 'create:trusted_certs'
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
        self.common_policy_check(self.everyone_authorized_contexts,
                                 self.everyone_unauthorized_contexts,
                                 rule_name,
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
             rule_name: "user_id:%(user_id)s"})
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
             rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
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
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'trigger_crash_dump': None}
        self.controller._action_trigger_crash_dump(req,
            self.instance.uuid, body=body)


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

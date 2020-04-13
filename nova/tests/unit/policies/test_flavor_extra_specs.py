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

from nova.api.openstack.compute import flavor_manage
from nova.api.openstack.compute import flavors
from nova.api.openstack.compute import flavors_extraspecs
from nova.api.openstack.compute import servers
from nova.compute import vm_states
from nova import objects
from nova.policies import flavor_extra_specs as policies
from nova.policies import flavor_manage as fm_policies
from nova.policies import servers as s_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


class FlavorExtraSpecsPolicyTest(base.BasePolicyTest):
    """Test Flavor Extra Specs APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorExtraSpecsPolicyTest, self).setUp()
        self.controller = flavors_extraspecs.FlavorExtraSpecsController()
        self.flavor_ctrl = flavors.FlavorsController()
        self.fm_ctrl = flavor_manage.FlavorManageController()
        self.server_ctrl = servers.ServersController()
        self.req = fakes.HTTPRequest.blank('')
        self.server_ctrl._view_builder._add_security_grps = mock.MagicMock()
        self.server_ctrl._view_builder._get_metadata = mock.MagicMock()
        self.server_ctrl._view_builder._get_addresses = mock.MagicMock()
        self.server_ctrl._view_builder._get_host_id = mock.MagicMock()
        self.server_ctrl._view_builder._get_fault = mock.MagicMock()
        self.server_ctrl._view_builder._add_host_status = mock.MagicMock()

        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                vm_state=vm_states.ACTIVE)

        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        self.mock_get.return_value = self.instance

        fakes.stub_out_secgroup_api(
            self, security_groups=[{'name': 'default'}])
        self.mock_get_all = self.useFixture(fixtures.MockPatchObject(
            self.server_ctrl.compute_api, 'get_all')).mock
        self.mock_get_all.return_value = objects.InstanceList(
            objects=[self.instance])

        def get_flavor_extra_specs(context, flavor_id):
            return fake_flavor.fake_flavor_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                is_public=False, extra_specs={'hw:cpu_policy': 'shared'},
                expected_attrs='extra_specs')

        self.stub_out('nova.api.openstack.common.get_flavor',
                      get_flavor_extra_specs)

        # Check that all are able to get flavor extra specs.
        self.all_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        self.all_unauthorized_contexts = []
        # Check that all system scoped are able to get flavor extra specs.
        self.all_system_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        self.all_system_unauthorized_contexts = []

        # Check that admin is able to create, update and delete flavor
        # extra specs.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to create, update and
        # delete flavor extra specs.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

    @mock.patch('nova.objects.Flavor.save')
    def test_create_flavor_extra_specs_policy(self, mock_save):
        body = {'extra_specs': {'hw:numa_nodes': '1'}}
        rule_name = policies.POLICY_ROOT % 'create'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name,
                                 self.controller.create,
                                 self.req, '1234',
                                 body=body)

    @mock.patch('nova.objects.Flavor._flavor_extra_specs_del')
    @mock.patch('nova.objects.Flavor.save')
    def test_delete_flavor_extra_specs_policy(self, mock_save, mock_delete):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name,
                                 self.controller.delete,
                                 self.req, '1234', 'hw:cpu_policy')

    @mock.patch('nova.objects.Flavor.save')
    def test_update_flavor_extra_specs_policy(self, mock_save):
        body = {'hw:cpu_policy': 'shared'}
        rule_name = policies.POLICY_ROOT % 'update'
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name,
                                 self.controller.update,
                                 self.req, '1234', 'hw:cpu_policy',
                                 body=body)

    def test_show_flavor_extra_specs_policy(self):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_check(self.all_authorized_contexts,
                                 self.all_unauthorized_contexts,
                                 rule_name,
                                 self.controller.show,
                                 self.req, '1234',
                                 'hw:cpu_policy')

    def test_index_flavor_extra_specs_policy(self):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_check(self.all_authorized_contexts,
                                 self.all_unauthorized_contexts,
                                 rule_name,
                                 self.controller.index,
                                 self.req, '1234')

    def test_flavor_detail_with_extra_specs_policy(self):
        fakes.stub_out_flavor_get_all(self)
        rule_name = policies.POLICY_ROOT % 'index'
        req = fakes.HTTPRequest.blank('', version='2.61')
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts, self.all_unauthorized_contexts,
            rule_name, self.flavor_ctrl.detail, req,
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['flavors'][0])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['flavors'][0])

    def test_flavor_show_with_extra_specs_policy(self):
        fakes.stub_out_flavor_get_by_flavor_id(self)
        rule_name = policies.POLICY_ROOT % 'index'
        req = fakes.HTTPRequest.blank('', version='2.61')
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts, self.all_unauthorized_contexts,
            rule_name, self.flavor_ctrl.show, req, '1',
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['flavor'])

    def test_flavor_create_with_extra_specs_policy(self):
        rule_name = policies.POLICY_ROOT % 'index'
        # 'create' policy is checked before flavor extra specs 'index' policy
        # so we have to allow it for everyone otherwise it will fail first
        # for unauthorized contexts.
        rule = fm_policies.POLICY_ROOT % 'create'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.61')

        def fake_create(newflavor):
            newflavor['flavorid'] = uuids.fake_id
            newflavor["name"] = 'test'
            newflavor["memory_mb"] = 512
            newflavor["vcpus"] = 2
            newflavor["root_gb"] = 1
            newflavor["ephemeral_gb"] = 1
            newflavor["swap"] = 512
            newflavor["rxtx_factor"] = 1.0
            newflavor["is_public"] = True
            newflavor["disabled"] = False
            newflavor["extra_specs"] = {}

        self.stub_out("nova.objects.Flavor.create", fake_create)
        body = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
            }
        }
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_system_authorized_contexts,
            self.all_system_unauthorized_contexts,
            rule_name, self.fm_ctrl._create, req, body=body,
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['flavor'])

    @mock.patch('nova.objects.Flavor.save')
    def test_flavor_update_with_extra_specs_policy(self, mock_save):
        fakes.stub_out_flavor_get_by_flavor_id(self)
        rule_name = policies.POLICY_ROOT % 'index'
        # 'update' policy is checked before flavor extra specs 'index' policy
        # so we have to allow it for everyone otherwise it will fail first
        # for unauthorized contexts.
        rule = fm_policies.POLICY_ROOT % 'update'
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.61')

        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_system_authorized_contexts,
            self.all_system_unauthorized_contexts,
            rule_name, self.fm_ctrl._update, req, '1',
            body={'flavor': {'description': None}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['flavor'])

    def test_server_detail_with_extra_specs_policy(self):
        rule = s_policies.SERVERS % 'detail'
        # server 'detail' policy is checked before flavor extra specs 'index'
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.47')
        rule_name = policies.POLICY_ROOT % 'index'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts, self.all_unauthorized_contexts,
            rule_name, self.server_ctrl.detail, req,
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['servers'][0]['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['servers'][0]['flavor'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    def test_server_show_with_extra_specs_policy(self, mock_get, mock_block):
        rule = s_policies.SERVERS % 'show'
        # server 'show' policy is checked before flavor extra specs 'index'
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.47')
        rule_name = policies.POLICY_ROOT % 'index'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts,
            self.all_unauthorized_contexts,
            rule_name, self.server_ctrl.show, req, 'fake',
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['server']['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['server']['flavor'])

    @mock.patch('nova.objects.BlockDeviceMappingList.bdms_by_instance_uuid')
    @mock.patch('nova.compute.api.API.get_instance_host_status')
    @mock.patch('nova.compute.api.API.rebuild')
    def test_server_rebuild_with_extra_specs_policy(self, mock_rebuild,
        mock_get, mock_bdm):
        rule = s_policies.SERVERS % 'rebuild'
        # server 'rebuild' policy is checked before flavor extra specs 'index'
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.47')
        rule_name = policies.POLICY_ROOT % 'index'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts,
            self.all_unauthorized_contexts,
            rule_name, self.server_ctrl._action_rebuild,
            req, self.instance.uuid,
            body={'rebuild': {"imageRef": uuids.fake_id}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp.obj['server']['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp.obj['server']['flavor'])

    @mock.patch('nova.compute.api.API.update_instance')
    def test_server_update_with_extra_specs_policy(self, mock_update):
        rule = s_policies.SERVERS % 'update'
        # server 'update' policy is checked before flavor extra specs 'index'
        # policy so we have to allow it for everyone otherwise it will fail
        # first for unauthorized contexts.
        self.policy.set_rules({rule: "@"}, overwrite=False)
        req = fakes.HTTPRequest.blank('', version='2.47')
        rule_name = policies.POLICY_ROOT % 'index'
        authorize_res, unauthorize_res = self.common_policy_check(
            self.all_authorized_contexts,
            self.all_unauthorized_contexts,
            rule_name, self.server_ctrl.update,
            req, self.instance.uuid,
            body={'server': {'name': 'test'}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['server']['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['server']['flavor'])


class FlavorExtraSpecsScopeTypePolicyTest(FlavorExtraSpecsPolicyTest):
    """Test Flavor Extra Specs APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorExtraSpecsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that all system scoped are able to get flavor extra specs.
        self.all_system_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context
        ]
        self.all_system_unauthorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]
        # Check that system admin is able to create, update and delete flavor
        # extra specs.
        self.admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system admin is not able to create, update and
        # delete flavor extra specs.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]


class FlavorExtraSpecsNoLegacyPolicyTest(FlavorExtraSpecsScopeTypePolicyTest):
    """Test Flavor Extra Specs APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(FlavorExtraSpecsNoLegacyPolicyTest, self).setUp()
        # Check that system or project reader are able to get flavor
        # extra specs.
        self.all_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.system_member_context,
            self.system_reader_context, self.other_project_member_context,
            self.other_project_reader_context
        ]
        self.all_unauthorized_contexts = [
            self.project_foo_context, self.system_foo_context
        ]
        # Check that all system scoped reader are able to get flavor
        # extra specs.
        self.all_system_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context
        ]
        self.all_system_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context
        ]

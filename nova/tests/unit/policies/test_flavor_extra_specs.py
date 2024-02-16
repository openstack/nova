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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import flavors
from nova.api.openstack.compute import flavors_extraspecs
from nova.policies import flavor_extra_specs as policies
from nova.policies import flavor_manage as fm_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_flavor
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
        self.fm_ctrl = flavors.FlavorsController()
        self.req = fakes.HTTPRequest.blank('')

        def get_flavor_extra_specs(context, flavor_id):
            return fake_flavor.fake_flavor_obj(
                self.project_member_context,
                id=1, uuid=uuids.fake_id, project_id=self.project_id,
                is_public=False, extra_specs={'hw:cpu_policy': 'shared'},
                expected_attrs='extra_specs')

        self.stub_out('nova.api.openstack.common.get_flavor',
                      get_flavor_extra_specs)

        # In the base/legacy case, all project and system contexts are
        # authorized in the "anyone" case.
        self.all_authorized_contexts = (self.all_project_contexts |
                                        self.all_system_contexts)

        # In the base/legacy case, all project and system contexts are
        # authorized in the case of things that distinguish between
        # scopes, since scope checking is disabled.
        self.all_project_authorized_contexts = (self.all_project_contexts |
                                               self.all_system_contexts)

        # In the base/legacy case, any admin is an admin.
        self.admin_authorized_contexts = set([self.project_admin_context,
                                              self.system_admin_context,
                                              self.legacy_admin_context])

    @mock.patch('nova.objects.Flavor.save')
    def test_create_flavor_extra_specs_policy(self, mock_save):
        body = {'extra_specs': {'hw:numa_nodes': '1'}}
        rule_name = policies.POLICY_ROOT % 'create'
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name,
                                self.controller.create,
                                self.req, '1234',
                                body=body)

    @mock.patch('nova.objects.Flavor._flavor_extra_specs_del')
    @mock.patch('nova.objects.Flavor.save')
    def test_delete_flavor_extra_specs_policy(self, mock_save, mock_delete):
        rule_name = policies.POLICY_ROOT % 'delete'
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name,
                                self.controller.delete,
                                self.req, '1234', 'hw:cpu_policy')

    @mock.patch('nova.objects.Flavor.save')
    def test_update_flavor_extra_specs_policy(self, mock_save):
        body = {'hw:cpu_policy': 'shared'}
        rule_name = policies.POLICY_ROOT % 'update'
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name,
                                self.controller.update,
                                self.req, '1234', 'hw:cpu_policy',
                                body=body)

    def test_show_flavor_extra_specs_policy(self):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_auth(self.all_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, '1234',
                                'hw:cpu_policy')

    def test_index_flavor_extra_specs_policy(self):
        rule_name = policies.POLICY_ROOT % 'index'
        self.common_policy_auth(self.all_authorized_contexts,
                                rule_name,
                                self.controller.index,
                                self.req, '1234')

    def test_flavor_detail_with_extra_specs_policy(self):
        fakes.stub_out_flavor_get_all(self)
        rule_name = policies.POLICY_ROOT % 'index'
        req = fakes.HTTPRequest.blank('', version='2.61')
        authorize_res, unauthorize_res = self.common_policy_auth(
            self.all_authorized_contexts,
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
        authorize_res, unauthorize_res = self.common_policy_auth(
            self.all_authorized_contexts,
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
        authorize_res, unauthorize_res = self.common_policy_auth(
            self.all_project_authorized_contexts,
            rule_name, self.fm_ctrl.create, req, body=body,
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

        authorize_res, unauthorize_res = self.common_policy_auth(
            self.all_project_authorized_contexts,
            rule_name, self.fm_ctrl.update, req, '1',
            body={'flavor': {'description': None}},
            fatal=False)
        for resp in authorize_res:
            self.assertIn('extra_specs', resp['flavor'])
        for resp in unauthorize_res:
            self.assertNotIn('extra_specs', resp['flavor'])


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

        # Only project users are authorized
        self.reduce_set('all_project_authorized', self.all_project_contexts)
        self.reduce_set('all_authorized', self.all_project_contexts)

        # Only admins can do admin things
        self.admin_authorized_contexts = [self.legacy_admin_context,
                                          self.project_admin_context]


class FlavorExtraSpecsNoLegacyNoScopeTest(FlavorExtraSpecsPolicyTest):
    """Test Flavor Extra Specs API policies with deprecated rules
    disabled, but scope checking still disabled.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(FlavorExtraSpecsNoLegacyNoScopeTest, self).setUp()

        # Disabling legacy rules means that random roles no longer
        # have power, but without scope checking there is no
        # difference between project and system
        everything_but_foo = (
            self.all_project_contexts | self.all_system_contexts) - set([
                self.system_foo_context,
                self.project_foo_context,
            ])
        self.reduce_set('all_project_authorized', everything_but_foo)
        self.reduce_set('all_authorized', everything_but_foo)


class FlavorExtraSpecsNoLegacyPolicyTest(FlavorExtraSpecsScopeTypePolicyTest):
    """Test Flavor Extra Specs APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(FlavorExtraSpecsNoLegacyPolicyTest, self).setUp()
        # Non-legacy rules do not imply random roles have any
        # access. Same note as above, regarding other_project_*
        # contexts. With scope checking enabled, project and system
        # contexts stay separate.
        self.reduce_set(
            'all_project_authorized',
            self.all_project_contexts - set([self.project_foo_context]))
        everything_but_foo_and_system = (
            self.all_contexts - set([
                self.project_foo_context,
            ]) - self.all_system_contexts)
        self.reduce_set('all_authorized', everything_but_foo_and_system)

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
from nova.policies import flavor_manage as fm_policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class FlavorManagePolicyTest(base.BasePolicyTest):
    """Test os-flavor-manage APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorManagePolicyTest, self).setUp()
        self.controller = flavors.FlavorsController()
        self.req = fakes.HTTPRequest.blank('')
        # With legacy rule and no scope checks, all admin can manage
        # the flavors.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    def test_create_flavor_policy(self):
        rule_name = fm_policies.POLICY_ROOT % 'create'

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
        self.stub_out("nova.objects.Flavor.create", fake_create)
        body = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
            }
        }
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name, self.controller.create,
                                self.req, body=body)

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    @mock.patch('nova.objects.Flavor.save')
    def test_update_flavor_policy(self, mock_save, mock_get):
        rule_name = fm_policies.POLICY_ROOT % 'update'
        req = fakes.HTTPRequest.blank('', version='2.55')
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name, self.controller.update,
                                req, uuids.fake_id,
                                body={'flavor': {'description': None}})

    @mock.patch('nova.objects.Flavor.destroy')
    def test_delete_flavor_policy(self, mock_delete):
        rule_name = fm_policies.POLICY_ROOT % 'delete'
        self.common_policy_auth(self.admin_authorized_contexts,
                                rule_name, self.controller.delete,
                                self.req, uuids.fake_id)


class FlavorManageNoLegacyNoScopeTest(FlavorManagePolicyTest):
    """Test Flavor Access API policies with deprecated rules
    disabled, but scope checking still disabled.
    """

    without_deprecated_rules = True


class FlavorManageScopeTypePolicyTest(FlavorManagePolicyTest):
    """Test os-flavor-manage APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(FlavorManageScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope enabled, only project admin is able to manage
        # the flavors.
        self.admin_authorized_contexts = [
            self.legacy_admin_context,
            self.project_admin_context]


class FlavorManageScopeTypeNoLegacyPolicyTest(
        FlavorManageScopeTypePolicyTest):
    """Test Flavor Manage APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

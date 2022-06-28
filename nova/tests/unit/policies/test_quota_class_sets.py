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

from nova.api.openstack.compute import quota_classes
from nova.policies import quota_class_sets as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class QuotaClassSetsPolicyTest(base.BasePolicyTest):
    """Test Quota Class Set APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(QuotaClassSetsPolicyTest, self).setUp()
        self.controller = quota_classes.QuotaClassSetsController()
        self.req = fakes.HTTPRequest.blank('')

        # With legacy rule and scope check disabled by default, system admin,
        # legacy admin, and project admin will be able to get, update quota
        # class.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]

    @mock.patch('nova.objects.Quotas.update_class')
    def test_update_quota_class_sets_policy(self, mock_update):
        rule_name = policies.POLICY_ROOT % 'update'
        body = {'quota_class_set':
                    {'metadata_items': 128,
                        'ram': 51200, 'floating_ips': -1,
                        'fixed_ips': -1, 'instances': 10,
                        'injected_files': 5, 'cores': 20}}
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.update,
                                self.req, 'test_class',
                                body=body)

    @mock.patch('nova.quota.QUOTAS.get_class_quotas')
    def test_show_quota_class_sets_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, 'test_class')


class QuotaClassSetsNoLegacyNoScopePolicyTest(QuotaClassSetsPolicyTest):
    """Test QuotaClassSets APIs policies with no legacy deprecated rules
    and no scope checks which means new defaults only. In this case
    system admin, legacy admin, and project admin will be able to get
    update quota class. Legacy admin will be allowed as policy
    is just admin if no scope checks.

    """
    without_deprecated_rules = True


class QuotaClassSetsScopeTypePolicyTest(QuotaClassSetsPolicyTest):
    """Test Quota Class Sets APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(QuotaClassSetsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope checks enable, only project admins are able to
        # update and get quota class.
        self.project_admin_authorized_contexts = [self.legacy_admin_context,
                                                  self.project_admin_context]


class QuotaClassScopeTypeNoLegacyPolicyTest(QuotaClassSetsScopeTypePolicyTest):
    """Test QuotaClassSets APIs policies with no legacy deprecated rules
    and scope checks enabled which means scope + new defaults so
    only system admin is able to update and get quota class.

    """
    without_deprecated_rules = True

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

from nova.api.openstack.compute import quota_sets
from nova import exception
from nova.policies import quota_sets as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class QuotaSetsPolicyTest(base.BasePolicyTest):
    """Test Quota Sets APIs policies with all possible context.
    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(QuotaSetsPolicyTest, self).setUp()
        self.controller = quota_sets.QuotaSetsController()
        self.controller._validate_quota_limit = mock.MagicMock()
        self.req = fakes.HTTPRequest.blank('')
        self.project_id = self.req.environ['nova.context'].project_id

        # With legacy rule all admin is able to update or revert their quota
        # to default or get other project quota.
        self.project_admin_authorized_contexts = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context])
        # With legacy rule, everyone is able to get their own quota.
        self.project_reader_authorized_contexts = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context])
        # Everyone is able to get the default quota
        self.everyone_authorized_contexts = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context])

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    @mock.patch('nova.quota.QUOTAS.get_settable_quotas')
    def test_update_quota_sets_policy(self, mock_update, mock_get):
        rule_name = policies.POLICY_ROOT % 'update'
        body = {'quota_set': {
                    'instances': 50,
                    'cores': 50}
               }
        for cxtx in self.project_admin_authorized_contexts:
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            self.controller.update(req, cxtx.project_id, body=body)
        for cxtx in (self.all_contexts -
                set(self.project_admin_authorized_contexts)):
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, self.controller.update,
                req, cxtx.project_id, body=body)
            self.assertEqual(
                "Policy doesn't allow %s to be performed." % rule_name,
                exc.format_message())

    @mock.patch('nova.objects.Quotas.destroy_all_by_project')
    def test_delete_quota_sets_policy(self, mock_delete):
        rule_name = policies.POLICY_ROOT % 'delete'
        for cxtx in self.project_admin_authorized_contexts:
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            self.controller.delete(req, cxtx.project_id)
        for cxtx in (self.all_contexts -
                set(self.project_admin_authorized_contexts)):
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, self.controller.delete,
                req, cxtx.project_id)
            self.assertEqual(
                "Policy doesn't allow %s to be performed." % rule_name,
                exc.format_message())

    @mock.patch('nova.quota.QUOTAS.get_defaults')
    def test_default_quota_sets_policy(self, mock_default):
        rule_name = policies.POLICY_ROOT % 'defaults'
        self.common_policy_auth(self.everyone_authorized_contexts,
                                rule_name,
                                self.controller.defaults,
                                self.req, self.project_id)

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_detail_quota_sets_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'detail'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.detail,
                                self.req, 'try-other-project')
        # Check if project reader or higher roles are able to get
        # their own quota
        for cxtx in self.project_reader_authorized_contexts:
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            self.controller.detail(req, cxtx.project_id)

    @mock.patch('nova.quota.QUOTAS.get_project_quotas')
    def test_show_quota_sets_policy(self, mock_get):
        rule_name = policies.POLICY_ROOT % 'show'
        self.common_policy_auth(self.project_admin_authorized_contexts,
                                rule_name,
                                self.controller.show,
                                self.req, 'try-other-project')
        # Check if project reader or higher roles are able to get
        # their own quota
        for cxtx in self.project_reader_authorized_contexts:
            req = fakes.HTTPRequest.blank('')
            req.environ['nova.context'] = cxtx
            self.controller.show(req, cxtx.project_id)


class QuotaSetsNoLegacyNoScopePolicyTest(QuotaSetsPolicyTest):
    """Test QuotaSets APIs policies with no legacy deprecated rules
    and no scope checks.

    """

    without_deprecated_rules = True

    def setUp(self):
        super(QuotaSetsNoLegacyNoScopePolicyTest, self).setUp()
        # Even with no legacy rule, because any admin requesting
        # update/revert quota for their own project will be allowed.
        # And any admin will be able to get other project quota.
        self.project_admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # With no legacy rule, other project and foo role will not be
        # able to get the quota.
        self.project_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.project_member_context,
            self.project_reader_context]


class QuotaSetsScopeTypePolicyTest(QuotaSetsPolicyTest):
    """Test Quota Sets APIs policies with system scope enabled.
    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(QuotaSetsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # With scope enabled, system users will be disallowed.
        self.reduce_set('project_admin_authorized', set([
            self.legacy_admin_context,
            self.project_admin_context]))
        self.reduce_set('project_reader_authorized',
                        self.all_project_contexts)
        self.everyone_authorized_contexts = self.all_project_contexts


class QuotaSetsScopeTypeNoLegacyPolicyTest(QuotaSetsScopeTypePolicyTest):
    """Test Quota Sets APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(QuotaSetsScopeTypeNoLegacyPolicyTest, self).setUp()
        # With scope enabled and no legacy, system and
        # non-reader/member users are disallowed.
        self.reduce_set('project_reader_authorized',
                        self.all_project_contexts -
                        set([self.project_foo_context]))

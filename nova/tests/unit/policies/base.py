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
import copy

from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova import exception
from nova import test
from nova.tests.unit import policy_fixture


LOG = logging.getLogger(__name__)


class BasePolicyTest(test.TestCase):
    # NOTE(gmann): Set this flag to True if you would like to tests the
    # new behaviour of policy without deprecated rules.
    # This means you can simulate the phase when policies completely
    # switch to new behaviour by removing the support of old rules.
    without_deprecated_rules = False

    # Add rules here other than base rules which need to override
    # to remove the deprecated rules.
    # For Example:
    # rules_without_deprecation{
    #    "os_compute_api:os-deferred-delete:restore":
    #        "rule:system_admin_or_owner"}
    rules_without_deprecation = {}

    def setUp(self):
        super(BasePolicyTest, self).setUp()
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())

        self.admin_project_id = uuids.admin_project_id
        self.project_id = uuids.project_id
        self.project_id_other = uuids.project_id_other

        # all context are with implied roles.
        self.legacy_admin_context = nova_context.RequestContext(
                user_id="legacy_admin", project_id=self.admin_project_id,
                roles=['admin', 'member', 'reader'])

        # system scoped users
        self.system_admin_context = nova_context.RequestContext(
                user_id="admin",
                roles=['admin', 'member', 'reader'], system_scope='all')

        self.system_member_context = nova_context.RequestContext(
                user_id="member",
                roles=['member', 'reader'], system_scope='all')

        self.system_reader_context = nova_context.RequestContext(
                user_id="reader", roles=['reader'], system_scope='all')

        self.system_foo_context = nova_context.RequestContext(
                user_id="foo", roles=['foo'], system_scope='all')

        # project scoped users
        self.project_admin_context = nova_context.RequestContext(
                user_id="project_admin", project_id=self.project_id,
                roles=['admin', 'member', 'reader'])

        self.project_member_context = nova_context.RequestContext(
                user_id="project_member", project_id=self.project_id,
                roles=['member', 'reader'])

        self.project_reader_context = nova_context.RequestContext(
                user_id="project_reader", project_id=self.project_id,
                roles=['reader'])

        self.project_foo_context = nova_context.RequestContext(
                user_id="project_foo", project_id=self.project_id,
                roles=['foo'])

        self.other_project_member_context = nova_context.RequestContext(
                user_id="other_project_member",
                project_id=self.project_id_other,
                roles=['member', 'reader'])

        self.other_project_reader_context = nova_context.RequestContext(
                user_id="other_project_member",
                project_id=self.project_id_other,
                roles=['reader'])

        self.all_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.other_project_member_context,
            self.project_foo_context, self.other_project_reader_context
        ]

        if self.without_deprecated_rules:
            # To simulate the new world, remove deprecations by overriding
            # rules which has the deprecated rules.
            self.rules_without_deprecation.update({
                "system_admin_or_owner":
                    "rule:system_admin_api or rule:project_member_api",
                "system_or_project_reader":
                    "rule:system_reader_api or rule:project_reader_api",
                "system_admin_api":
                    "role:admin and system_scope:all",
                "system_reader_api":
                    "role:reader and system_scope:all",
                "project_member_api":
                    "role:member and project_id:%(project_id)s",
            })
            self.policy.set_rules(self.rules_without_deprecation,
                                  overwrite=False)

    def common_policy_check(self, authorized_contexts,
                            unauthorized_contexts, rule_name,
                            func, req, *arg, **kwarg):

        # NOTE(brinzhang): When fatal=False is passed as a parameter
        # in context.can(), we cannot get the desired ensure_raises().
        # At this time, we can call ensure_return() to assert the func's
        # response to ensure that changes are right.
        fatal = kwarg.pop('fatal', True)
        authorized_response = []
        unauthorize_response = []

        # TODO(gmann): we need to add the new context
        # self.other_project_reader_context in all tests and then remove
        # this conditional adjusment.
        test_context = authorized_contexts + unauthorized_contexts
        test_context_len = len(test_context)
        if self.other_project_reader_context not in test_context:
            test_context_len += 1
        self.assertEqual(len(self.all_contexts), test_context_len,
                        "Expected testing context are mismatch. check all "
                        "contexts mentioned in self.all_contexts are tested")

        def ensure_return(req, *args, **kwargs):
            return func(req, *arg, **kwargs)

        def ensure_raises(req, *args, **kwargs):
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, func, req, *arg, **kwarg)
            # NOTE(gmann): In case of multi-policy APIs, PolicyNotAuthorized
            # exception can be raised from either of the policy so checking
            # the error message, which includes the rule name, can mismatch.
            # Tests verifying the multi policy can pass rule_name as None
            # to skip the error message assert.
            if rule_name is not None:
                self.assertEqual(
                    "Policy doesn't allow %s to be performed." %
                    rule_name, exc.format_message())
        # Verify all the context having allowed scope and roles pass
        # the policy check.
        for context in authorized_contexts:
            LOG.info("Testing authorized context: %s", context)
            req.environ['nova.context'] = context
            args1 = copy.deepcopy(arg)
            kwargs1 = copy.deepcopy(kwarg)
            if not fatal:
                authorized_response.append(
                    ensure_return(req, *args1, **kwargs1))
            else:
                func(req, *args1, **kwargs1)

        # Verify all the context not having allowed scope or roles fail
        # the policy check.
        for context in unauthorized_contexts:
            LOG.info("Testing unauthorized context: %s", context)
            req.environ['nova.context'] = context
            args1 = copy.deepcopy(arg)
            kwargs1 = copy.deepcopy(kwarg)
            if not fatal:
                try:
                    unauthorize_response.append(
                        ensure_return(req, *args1, **kwargs1))
                    # NOTE(gmann): We need to ignore the PolicyNotAuthorized
                    # exception here so that we can add the correct response
                    # in unauthorize_response for the case of fatal=False.
                    # This handle the case of multi policy checks where tests
                    # are verifying the second policy via the response of
                    # fatal-False and ignoring the response checks where the
                    # first policy itself fail to pass (even test override the
                    # first policy to allow for everyone but still, scope
                    # checks can leads to PolicyNotAuthorized error).
                    # For example: flavor extra specs policy for GET flavor
                    # API. In that case, flavor extra spec policy is checked
                    # after the GET flavor policy. So any context failing on
                    # GET flavor will raise the  PolicyNotAuthorized and for
                    # that case we do not have any way to verify the flavor
                    # extra specs so skip that context to check in test.
                except exception.PolicyNotAuthorized:
                    continue
            else:
                ensure_raises(req, *args1, **kwargs1)

        return authorized_response, unauthorize_response

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
from nova.tests import fixtures


LOG = logging.getLogger(__name__)


def rule_if_system(system_rule, non_system_rule, context):
    """Helper function to pick a rule based on system-ness of context.

    This can be used (with functools.partial) to choose between two
    rule names, based on whether or not the context has system
    scope. Specifically if we will fail the parent of a nested policy
    check based on scope_types=['project'], this can be used to choose
    the parent rule name for the error message check in
    common_policy_check().

    """
    if context.system_scope:
        return system_rule
    else:
        return non_system_rule


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
    #        "rule:project_admin_api"}
    rules_without_deprecation = {}

    def setUp(self):
        super(BasePolicyTest, self).setUp()
        # TODO(gmann): enforce_scope and enforce_new_defaults are enabled
        # by default in the code so disable them in base test class until
        # we have deprecated rules and their tests. We have enforce_scope
        # and no-legacy tests which are explicitly enabling scope and new
        # defaults to test the new defaults and scope. In future, once
        # we remove the deprecated rules, along with refactoring the unit
        # tests we can remove overriding the oslo policy flags.
        self.flags(enforce_scope=False, group="oslo_policy")
        if not self.without_deprecated_rules:
            self.flags(enforce_new_defaults=False, group="oslo_policy")
        self.useFixture(fixtures.NeutronFixture(self))
        self.policy = self.useFixture(fixtures.RealPolicyFixture())

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

        self.all_contexts = set([
            self.legacy_admin_context, self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.other_project_member_context,
            self.project_foo_context, self.other_project_reader_context
        ])

        # All the project contexts for easy access.
        self.all_project_contexts = set([
            self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ])
        # All the system contexts for easy access.
        self.all_system_contexts = set([
            self.system_admin_context, self.system_foo_context,
            self.system_member_context, self.system_reader_context,
        ])
        # A few commmon set of contexts to be used in tests
        #
        # With scope disable and no legacy rule, any admin,
        # project members have access. No other role in that project
        # will have access.
        self.project_member_or_admin_with_no_scope_no_legacy = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
        ])
        # With scope enable and legacy rule, only project scoped admin
        # and any role in that project will have access.
        self.project_m_r_or_admin_with_scope_and_legacy = set([
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context,
            self.project_foo_context
        ])
        # With scope enable and no legacy rule, only project scoped admin
        # and project members have access. No other role in that project
        # or system scoped token will have access.
        self.project_member_or_admin_with_scope_no_legacy = set([
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context
        ])
        # With scope disable and no legacy rule, any admin,
        # project members, and project reader have access. No other
        # role in that project will have access.
        self.project_reader_or_admin_with_no_scope_no_legacy = set([
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context
        ])
        # With scope enable and no legacy rule, only project scoped admin,
        # project members, and project reader have access. No other role
        # in that project or system scoped token will have access.
        self.project_reader_or_admin_with_scope_no_legacy = set([
            self.legacy_admin_context, self.project_admin_context,
            self.project_member_context, self.project_reader_context
        ])

        if self.without_deprecated_rules:
            # To simulate the new world, remove deprecations by overriding
            # rules which has the deprecated rules.
            self.rules_without_deprecation.update({
                "context_is_admin":
                    "role:admin",
                "project_reader_or_admin":
                    "rule:project_reader_api or rule:context_is_admin",
                "project_admin_api":
                    "role:admin and project_id:%(project_id)s",
                "project_member_api":
                    "role:member and project_id:%(project_id)s",
                "project_reader_api":
                    "role:reader and project_id:%(project_id)s",
                "project_member_or_admin":
                    "rule:project_member_api or rule:context_is_admin",
                "project_reader_or_admin":
                    "rule:project_reader_api or rule:context_is_admin",
            })
            self.policy.set_rules(self.rules_without_deprecation,
                                  overwrite=False)

    def reduce_set(self, name, new_set):
        """Reduce a named set of contexts in a subclass.

        This removes things from a set in a child test class by taking
        a new set, but asserts that no *new* contexts are added over
        what is defined in the parent.

        :param name: The name of a set of contexts on self
                     (i.e. 'project' for self.project_contexts
        :param new_set: The new set of contexts that should be used in
                        the above set. The new_set is asserted to be a
                        perfect subset of the existing set
        """
        current = getattr(self, '%s_contexts' % name)

        errors = ','.join(x.user_id for x in new_set - current)
        self.assertEqual('', errors,
                         'Attempt to reduce set would add %s' % errors)

        LOG.info('%s.%s_contexts: removing %s',
                 self.__class__.__name__,
                 name,
                 ','.join(x.user_id for x in current - new_set))
        setattr(self, '%s_contexts' % name, new_set)

    def common_policy_auth(self, authorized_contexts,
                           rule_name,
                           func, req, *arg, **kwarg):
        """Check a policy rule against a set of authorized contexts.

        This is exactly like common_policy_check, except that it
        assumes any contexts not in the authorized set are in the
        unauthorized set.
        """
        # The unauthorized users are any not in the authorized set.
        unauth = list(set(self.all_contexts) - set(authorized_contexts))
        # In case a set was passed in, convert to list for stable ordering.
        authorized_contexts = list(authorized_contexts)
        # Log both sets in the order we will test them to aid debugging of
        # fatal=False responses.
        LOG.info('Authorized users: %s', list(
            x.user_id for x in authorized_contexts))
        LOG.info('Unauthorized users: %s', list(x.user_id for x in unauth))
        return self.common_policy_check(authorized_contexts, unauth,
                                        rule_name, func, req, *arg, **kwarg)

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

        self.assertEqual(len(self.all_contexts),
                         len(authorized_contexts) + len(
                             unauthorized_contexts),
                        "Expected testing context are mismatch. check all "
                        "contexts mentioned in self.all_contexts are tested")

        def ensure_return(req, *args, **kwargs):
            return func(req, *arg, **kwargs)

        def ensure_raises(req, *args, **kwargs):
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, func, req, *arg, **kwarg)
            # NOTE(danms): We may need to check a different rule_name
            # as the enforced policy, based on the context we are
            # using. Examples are multi-policy APIs for similar
            # reasons as below. If we are passed a function for
            # rule_name, call it with the context being used to
            # determine the rule_name we should verify.
            if callable(rule_name):
                actual_rule_name = rule_name(req.environ['nova.context'])
            else:
                actual_rule_name = rule_name
            # NOTE(gmann): In case of multi-policy APIs, PolicyNotAuthorized
            # exception can be raised from either of the policy so checking
            # the error message, which includes the rule name, can mismatch.
            # Tests verifying the multi policy can pass rule_name as None
            # to skip the error message assert.
            if actual_rule_name is not None:
                self.assertEqual(
                    "Policy doesn't allow %s to be performed." %
                    actual_rule_name, exc.format_message())
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

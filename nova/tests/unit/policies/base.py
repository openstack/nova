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

from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova import exception
from nova import test
from nova.tests.unit import policy_fixture


LOG = logging.getLogger(__name__)


class BasePolicyTest(test.TestCase):

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

        self.all_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.project_reader_context, self.other_project_member_context,
            self.project_foo_context,
        ]

    def common_policy_check(self, authorized_contexts,
                            unauthorized_contexts, rule_name,
                            func, req, *arg, **kwarg):

        self.assertEqual(len(self.all_contexts),
                         len(authorized_contexts) + len(
                             unauthorized_contexts),
                         "Few context are missing. check all contexts "
                         "mentioned in self.all_contexts are tested")

        def ensure_raises(req):
            exc = self.assertRaises(
                exception.PolicyNotAuthorized, func, req, *arg, **kwarg)
            self.assertEqual(
                "Policy doesn't allow %s to be performed." %
                rule_name, exc.format_message())
        # Verify all the context having allowed scope and roles pass
        # the policy check.
        for context in authorized_contexts:
            LOG.info("Testing authorized context: %s", context)
            req.environ['nova.context'] = context
            func(req, *arg, **kwarg)
        # Verify all the context not having allowed scope or roles fail
        # the policy check.
        for context in unauthorized_contexts:
            LOG.info("Testing unauthorized context: %s", context)
            req.environ['nova.context'] = context
            ensure_raises(req)

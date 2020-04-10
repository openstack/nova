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

import mock

from nova.api.openstack.compute import console_auth_tokens
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class ConsoleAuthTokensPolicyTest(base.BasePolicyTest):
    """Test Console Auth Tokens APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ConsoleAuthTokensPolicyTest, self).setUp()
        self.controller = console_auth_tokens.ConsoleAuthTokensController()
        self.req = fakes.HTTPRequest.blank('', version='2.31')

        # Check that system reader is able to get console connection
        # information.
        # NOTE(gmann): Until old default rule which is admin_api is
        # deprecated and not removed, project admin and legacy admin
        # will be able to get console. This make sure that existing
        # tokens will keep working even we have changed this policy defaults
        # to reader role.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to get console connection
        # information.
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context]

    @mock.patch('nova.objects.ConsoleAuthToken.validate')
    def test_console_connect_info_token_policy(self, mock_validate):
        rule_name = "os_compute_api:os-console-auth-tokens"
        self.common_policy_check(self.reader_authorized_contexts,
                                 self.reader_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, fakes.FAKE_UUID)


class ConsoleAuthTokensScopeTypePolicyTest(ConsoleAuthTokensPolicyTest):
    """Test Console Auth Tokens APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ConsoleAuthTokensScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system reader is able to get console connection
        # information.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system-reader is not able to get console connection
        # information.
        self.reader_unauthorized_contexts = [
            self.legacy_admin_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]

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

from nova.api.openstack.compute import services as services_v21
from nova import exception
from nova.policies import base as base_policy
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base
from nova.tests.unit import policy_fixture


class ServicesPolicyTest(base.BasePolicyTest):
    """Test os-services APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServicesPolicyTest, self).setUp()
        self.controller = services_v21.ServiceController()
        self.req = fakes.HTTPRequest.blank('/services')
        # Check that admin is able to change the service
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to change the service
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]

        # Check that system scoped admin, member and reader are able to
        # read the service data.
        # NOTE(gmann): Until old default rule which is admin_api is
        # deprecated and not removed, project admin and legacy admin
        # will be able to read the service data. This make sure that existing
        # tokens will keep working even we have changed this policy defaults
        # to reader role.
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-system-reader are not able to read the service
        # data
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context,
            self.other_project_reader_context,
        ]

    def test_delete_service_policy(self):
        rule_name = "os_compute_api:os-services:delete"
        with mock.patch('nova.compute.api.HostAPI.service_get_by_id'):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.delete,
                                     self.req, 1)

    def test_index_service_policy(self):
        rule_name = "os_compute_api:os-services:list"
        with mock.patch('nova.compute.api.HostAPI.service_get_all'):
            self.common_policy_check(self.reader_authorized_contexts,
                                     self.reader_unauthorized_contexts,
                                     rule_name, self.controller.index,
                                     self.req)

    def test_old_update_service_policy(self):
        rule_name = "os_compute_api:os-services:update"
        body = {'host': 'host1', 'binary': 'nova-compute'}
        update = 'nova.compute.api.HostAPI.service_update_by_host_and_binary'
        with mock.patch(update):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.update,
                                     self.req, 'enable', body=body)

    def test_update_service_policy(self):
        rule_name = "os_compute_api:os-services:update"
        req = fakes.HTTPRequest.blank(
            '', version=services_v21.UUID_FOR_ID_MIN_VERSION)
        service = self.start_service(
            'compute', 'fake-compute-host').service_ref
        with mock.patch('nova.compute.api.HostAPI.service_update'):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.update,
                                     req, service.uuid,
                                     body={'status': 'enabled'})


class ServicesScopeTypePolicyTest(ServicesPolicyTest):
    """Test os-services APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scopped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServicesScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system admin is able to change the service
        self.admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system or non-admin is not able to change the service
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]

        # Check that system admin, member and reader are able to read the
        # service data
        self.reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context]
        # Check that non-system or non-reader are not able to read the service
        # data
        self.reader_unauthorized_contexts = [
            self.system_foo_context, self.legacy_admin_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.other_project_reader_context,
            self.project_foo_context, self.project_reader_context
        ]


class ServicesDeprecatedPolicyTest(base.BasePolicyTest):
    """Test os-services APIs Deprecated policies.

    This class checks if deprecated policy rules are
    overridden by user on policy.yaml file then they
    still work because oslo.policy add deprecated rules
    in logical OR condition and enforce them for policy
    checks if overridden.
    """

    def setUp(self):
        super(ServicesDeprecatedPolicyTest, self).setUp()
        self.controller = services_v21.ServiceController()
        self.member_req = fakes.HTTPRequest.blank('')
        self.member_req.environ['nova.context'] = self.system_reader_context
        self.reader_req = fakes.HTTPRequest.blank('')
        self.reader_req.environ['nova.context'] = self.project_reader_context
        self.deprecated_policy = "os_compute_api:os-services"
        # Overridde rule with different checks than defaults so that we can
        # verify the rule overridden case.
        override_rules = {self.deprecated_policy: base_policy.SYSTEM_READER}
        # NOTE(gmann): Only override the deprecated rule in policy file so
        # that
        # we can verify if overridden checks are considered by oslo.policy.
        # Oslo.policy will consider the overridden rules if:
        #  1. overridden deprecated rule's checks are different than defaults
        #  2. new rules are not present in policy file
        self.policy = self.useFixture(policy_fixture.OverridePolicyFixture(
                                      rules_in_file=override_rules))

    def test_deprecated_policy_overridden_rule_is_checked(self):
        # Test to verify if deprecatd overridden policy is working.

        # check for success as member role. Deprecated rule
        # has been overridden with member checks in policy.yaml
        # If member role pass it means overridden rule is enforced by
        # olso.policy because new default is system admin and the old
        # default is admin.
        with mock.patch('nova.compute.api.HostAPI.service_get_by_id'):
            self.controller.index(self.member_req)

        # check for failure with reader context.
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.index, self.reader_req)
        self.assertEqual(
            "Policy doesn't allow os_compute_api:os-services:list to be"
            " performed.",
            exc.format_message())

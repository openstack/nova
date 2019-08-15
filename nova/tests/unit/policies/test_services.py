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
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


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
            self.project_foo_context, self.project_reader_context
        ]

    def test_delete_service_policy(self):
        rule_name = "os_compute_api:os-services"
        with mock.patch('nova.compute.api.HostAPI.service_get_by_id'):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.delete,
                                     self.req, 1)

    def test_index_service_policy(self):
        rule_name = "os_compute_api:os-services"
        with mock.patch('nova.compute.api.HostAPI.service_get_all'):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.index,
                                     self.req)

    def test_old_update_service_policy(self):
        rule_name = "os_compute_api:os-services"
        body = {'host': 'host1', 'binary': 'nova-compute'}
        update = 'nova.compute.api.HostAPI.service_update_by_host_and_binary'
        with mock.patch(update):
            self.common_policy_check(self.admin_authorized_contexts,
                                     self.admin_unauthorized_contexts,
                                     rule_name, self.controller.update,
                                     self.req, 'enable', body=body)

    def test_update_service_policy(self):
        rule_name = "os_compute_api:os-services"
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

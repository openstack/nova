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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import evacuate
from nova.compute import vm_states
from nova import exception
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.policies import base


def fake_service_get_by_compute_host(self, context, host):
    return {'host_name': host,
            'service': 'compute',
            'zone': 'nova'
           }


class EvacuatePolicyTest(base.BasePolicyTest):
    """Test Evacuate APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(EvacuatePolicyTest, self).setUp()
        self.controller = evacuate.EvacuateController()
        self.req = fakes.HTTPRequest.blank('')
        self.user_req = fakes.HTTPRequest.blank('')
        user_id = self.user_req.environ['nova.context'].user_id
        self.stub_out('nova.compute.api.HostAPI.service_get_by_compute_host',
                      fake_service_get_by_compute_host)
        self.stub_out(
            'nova.api.openstack.common.'
            'instance_has_port_with_resource_request',
            lambda *args, **kwargs: False)
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.compute.api.API.get')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
                self.project_member_context, project_id=self.project_id,
                id=1, uuid=uuid, user_id=user_id, vm_state=vm_states.ACTIVE,
                task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance
        # Check that admin is able to evacuate the server
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context]
        # Check that non-admin is not able to evacuate the server
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]

    @mock.patch('nova.compute.api.API.evacuate')
    def test_evacuate_policy(self, mock_evacuate):
        rule_name = "os_compute_api:os-evacuate"
        body = {'evacuate': {'host': 'my-host',
                             'onSharedStorage': 'False',
                             'adminPass': 'admin_pass'}
               }
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller._evacuate,
                                 self.req, uuids.fake_id,
                                 body=body)

    def test_evacuate_policy_failed_with_other_user(self):
        rule_name = "os_compute_api:os-evacuate"
        # Change the user_id in request context.
        self.user_req.environ['nova.context'].user_id = 'other-user'
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'evacuate': {'host': 'my-host',
                             'onSharedStorage': 'False',
                             'adminPass': 'MyNewPass'
                             }}
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._evacuate, self.user_req,
                                fakes.FAKE_UUID, body=body)
        self.assertEqual(
                      "Policy doesn't allow %s to be performed." % rule_name,
                      exc.format_message())

    @mock.patch('nova.compute.api.API.evacuate')
    def test_evacuate_policy_pass_with_same_user(self, evacuate_mock):
        rule_name = "os_compute_api:os-evacuate"
        self.policy.set_rules({rule_name: "user_id:%(user_id)s"})
        body = {'evacuate': {'host': 'my-host',
                             'onSharedStorage': 'False',
                             'adminPass': 'MyNewPass'
                             }}
        self.controller._evacuate(self.user_req, fakes.FAKE_UUID, body=body)
        evacuate_mock.assert_called_once_with(
            self.user_req.environ['nova.context'],
            mock.ANY, 'my-host', False,
            'MyNewPass', None)


class EvacuateScopeTypePolicyTest(EvacuatePolicyTest):
    """Test Evacuate APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scopped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(EvacuateScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")


class EvacuateNoLegacyPolicyTest(EvacuateScopeTypePolicyTest):
    """Test Evacuate APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system APIs.
    """
    without_deprecated_rules = True

    def setUp(self):
        super(EvacuateNoLegacyPolicyTest, self).setUp()

        # Check that system admin is able to evacuate server.
        self.admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system or non-admin is not able to evacuate
        # server.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]

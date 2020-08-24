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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.api.openstack.compute import server_external_events as ev
from nova.policies import server_external_events as policies
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.policies import base


class ServerExternalEventsPolicyTest(base.BasePolicyTest):
    """Test Server External Events APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerExternalEventsPolicyTest, self).setUp()
        self.controller = ev.ServerExternalEventsController()
        self.req = fakes.HTTPRequest.blank('')

        # Check that admin is able to create the server external events.
        self.admin_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context
        ]
        # Check that non-admin is not able to create the server
        # external events.
        self.admin_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]

    @mock.patch('nova.compute.api.API.external_instance_event')
    @mock.patch('nova.objects.InstanceMappingList.get_by_instance_uuids')
    @mock.patch('nova.objects.InstanceList.get_by_filters')
    def test_server_external_events_policy(self, mock_event, mock_get,
                                           mock_filter):
        rule_name = policies.POLICY_ROOT % 'create'
        body = {'events': [{'name': 'network-vif-plugged',
                           'server_uuid': uuids.fake_id,
                           'status': 'completed'}]
               }
        self.common_policy_check(self.admin_authorized_contexts,
                                 self.admin_unauthorized_contexts,
                                 rule_name, self.controller.create,
                                 self.req, body=body)


class ServerExternalEventsScopeTypePolicyTest(ServerExternalEventsPolicyTest):
    """Test Server External Events APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(ServerExternalEventsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that admin is able to create the server external events.
        self.admin_authorized_contexts = [
            self.system_admin_context,
        ]
        # Check that non-admin is not able to create the server
        # external events.
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.project_admin_context,
            self.system_member_context, self.system_reader_context,
            self.system_foo_context, self.project_member_context,
            self.project_reader_context, self.project_foo_context,
            self.other_project_member_context,
            self.other_project_reader_context,
        ]


class ServerExternalEventsNoLegacyPolicyTest(
        ServerExternalEventsScopeTypePolicyTest):
    """Test Server External Events APIs policies with system scope enabled,
    and no more deprecated rules.
    """
    without_deprecated_rules = True

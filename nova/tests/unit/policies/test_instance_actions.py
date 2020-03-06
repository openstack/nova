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
import fixtures
import mock

from oslo_policy import policy as oslo_policy
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import instance_actions as instance_actions_v21
from nova.compute import vm_states
from nova import policy
from nova.tests.unit.api.openstack.compute import test_instance_actions
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_server_actions
from nova.tests.unit.policies import base

FAKE_UUID = fake_server_actions.FAKE_UUID
FAKE_REQUEST_ID = fake_server_actions.FAKE_REQUEST_ID1


class InstanceActionsPolicyTest(base.BasePolicyTest):
    """Test os-instance-actions APIs policies with all possible context.

    This class defines the set of context with different roles
    which are allowed and not allowed to pass the policy checks.
    With those set of context, it will call the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(InstanceActionsPolicyTest, self).setUp()
        self.controller = instance_actions_v21.InstanceActionsController()
        self.req = fakes.HTTPRequest.blank('')
        self.fake_actions = copy.deepcopy(fake_server_actions.FAKE_ACTIONS)
        self.fake_events = copy.deepcopy(fake_server_actions.FAKE_EVENTS)

        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.api.openstack.common.get_instance')).mock
        uuid = uuids.fake_id
        self.instance = fake_instance.fake_instance_obj(
            self.project_member_context,
            id=1, uuid=uuid, project_id=self.project_id,
            vm_state=vm_states.ACTIVE,
            task_state=None, launched_at=timeutils.utcnow())
        self.mock_get.return_value = self.instance

        # Check that admin or owner is able to list/show
        # instance actions.
        self.admin_or_owner_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.project_foo_context,
            self.project_reader_context, self.project_member_context
        ]

        self.admin_or_owner_unauthorized_contexts = [
            self.system_member_context, self.system_reader_context,
            self.system_foo_context,
            self.other_project_member_context
        ]

        # Check that admin is able to show the instance actions
        # events.
        self.admin_authorized_contexts = [
            self.legacy_admin_context,
            self.system_admin_context,
            self.project_admin_context
        ]
        # Check that non-admin is not able to show the instance
        # actions events.
        self.admin_unauthorized_contexts = [
            self.system_member_context,
            self.system_reader_context,
            self.system_foo_context,
            self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context,
            self.project_reader_context
        ]

    def _set_policy_rules(self, overwrite=True):
        rules = {'os_compute_api:os-instance-actions': '@'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules),
                         overwrite=overwrite)

    def test_index_instance_action_policy(self):
        rule_name = "os_compute_api:os-instance-actions"
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name, self.controller.index,
                                 self.req, self.instance['uuid'])

    @mock.patch('nova.compute.api.InstanceActionAPI.action_get_by_request_id')
    def test_show_instance_action_policy(self, mock_action_get):
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        mock_action_get.return_value = fake_action
        rule_name = "os_compute_api:os-instance-actions"
        self.common_policy_check(self.admin_or_owner_authorized_contexts,
                                 self.admin_or_owner_unauthorized_contexts,
                                 rule_name, self.controller.show,
                                 self.req, self.instance['uuid'],
                                 fake_action['request_id'])

    @mock.patch('nova.objects.InstanceActionEventList.get_by_action')
    @mock.patch('nova.objects.InstanceAction.get_by_request_id')
    def test_show_instance_action_policy_with_events(
            self, mock_get_action, mock_get_events):
        """Test to ensure skip checking policy rule
        os_compute_api:os-instance-actions.
        """
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        mock_get_action.return_value = fake_action
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        mock_get_events.return_value = fake_events
        fake_action_fmt = test_instance_actions.format_action(
            copy.deepcopy(fake_action))

        self._set_policy_rules(overwrite=False)
        rule_name = "os_compute_api:os-instance-actions:events"
        authorize_res, unauthorize_res = self.common_policy_check(
            self.admin_authorized_contexts, self.admin_unauthorized_contexts,
            rule_name, self.controller.show, self.req, self.instance['uuid'],
            fake_action['request_id'], fatal=False)

        for action in authorize_res:
            # In order to unify the display forms of 'start_time' and
            # 'finish_time', format the results returned by the show api.
            res_fmt = test_instance_actions.format_action(
                action['instanceAction'])
            self.assertEqual(fake_action_fmt['events'], res_fmt['events'])

        for action in unauthorize_res:
            self.assertNotIn('events', action['instanceAction'])


class InstanceActionsScopeTypePolicyTest(InstanceActionsPolicyTest):
    """Test os-instance-actions APIs policies with system scope enabled.

    This class set the nova.conf [oslo_policy] enforce_scope to True,
    so that we can switch on the scope checking on oslo policy side.
    It defines the set of context with scoped token which are allowed
    and not allowed to pass the policy checks.
    With those set of context, it will run the API operation and
    verify the expected behaviour.
    """

    def setUp(self):
        super(InstanceActionsScopeTypePolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system admin is able to get the
        # instance action events
        self.admin_authorized_contexts = [
            self.system_admin_context]
        # Check that non-system or non-admin is not able to
        # get the instance action events
        self.admin_unauthorized_contexts = [
            self.legacy_admin_context, self.system_member_context,
            self.system_reader_context, self.system_foo_context,
            self.project_admin_context, self.project_member_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_reader_context
        ]

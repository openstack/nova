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

from nova.api.openstack import api_version_request
from oslo_policy import policy as oslo_policy
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova.api.openstack.compute import instance_actions as instance_actions_v21
from nova.compute import vm_states
from nova import exception
from nova.policies import base as base_policy
from nova.policies import instance_actions as ia_policies
from nova import policy
from nova.tests.unit.api.openstack.compute import test_instance_actions
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_server_actions
from nova.tests.unit.policies import base
from nova.tests.unit import policy_fixture

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

        # Check that system reader are able to show the instance
        # actions events.
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_member_context,
            self.system_reader_context, self.legacy_admin_context,
            self.project_admin_context]
        # Check that non-system-reader are not able to show the instance
        # actions events.
        self.system_reader_unauthorized_contexts = [
            self.system_foo_context, self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context]

        self.project_or_system_reader_authorized_contexts = [
            self.legacy_admin_context, self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context, self.project_foo_context
        ]

        self.project_or_system_reader_unauthorized_contexts = [
            self.system_foo_context,
            self.other_project_member_context
        ]

    def _set_policy_rules(self, overwrite=True):
        rules = {ia_policies.BASE_POLICY_NAME % 'show': '@'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules),
                         overwrite=overwrite)

    def test_index_instance_action_policy(self):
        rule_name = ia_policies.BASE_POLICY_NAME % "list"
        self.common_policy_check(
            self.project_or_system_reader_authorized_contexts,
            self.project_or_system_reader_unauthorized_contexts,
            rule_name, self.controller.index,
            self.req, self.instance['uuid'])

    @mock.patch('nova.compute.api.InstanceActionAPI.action_get_by_request_id')
    def test_show_instance_action_policy(self, mock_action_get):
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        mock_action_get.return_value = fake_action
        rule_name = ia_policies.BASE_POLICY_NAME % "show"
        self.common_policy_check(
            self.project_or_system_reader_authorized_contexts,
            self.project_or_system_reader_unauthorized_contexts,
            rule_name, self.controller.show,
            self.req, self.instance['uuid'], fake_action['request_id'])

    @mock.patch('nova.objects.InstanceActionEventList.get_by_action')
    @mock.patch('nova.objects.InstanceAction.get_by_request_id')
    def test_show_instance_action_policy_with_events(
            self, mock_get_action, mock_get_events):
        """Test to ensure skip checking policy rule
        'os_compute_api:os-instance-actions:show'.
        """
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        mock_get_action.return_value = fake_action
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        mock_get_events.return_value = fake_events
        fake_action_fmt = test_instance_actions.format_action(
            copy.deepcopy(fake_action))

        self._set_policy_rules(overwrite=False)
        rule_name = ia_policies.BASE_POLICY_NAME % "events"
        authorize_res, unauthorize_res = self.common_policy_check(
            self.system_reader_authorized_contexts,
            self.system_reader_unauthorized_contexts,
            rule_name, self.controller.show,
            self.req, self.instance['uuid'],
            fake_action['request_id'], fatal=False)

        for action in authorize_res:
            # In order to unify the display forms of 'start_time' and
            # 'finish_time', format the results returned by the show api.
            res_fmt = test_instance_actions.format_action(
                action['instanceAction'])
            self.assertEqual(fake_action_fmt['events'], res_fmt['events'])

        for action in unauthorize_res:
            self.assertNotIn('events', action['instanceAction'])


class InstanceActionsDeprecatedPolicyTest(base.BasePolicyTest):
    """Test os-instance-actions APIs Deprecated policies.

    This class checks if deprecated policy rules are overridden
    by user on policy.json file then they still work because
    oslo.policy add deprecated rules in logical OR condition
    and enforces them for policy checks if overridden.
    """

    def setUp(self):
        super(InstanceActionsDeprecatedPolicyTest, self).setUp()
        self.controller = instance_actions_v21.InstanceActionsController()
        self.admin_or_owner_req = fakes.HTTPRequest.blank('')
        self.admin_or_owner_req.environ[
                'nova.context'] = self.project_admin_context
        self.reader_req = fakes.HTTPRequest.blank('')
        self.reader_req.environ['nova.context'] = self.project_reader_context
        self.deprecated_policy = ia_policies.ROOT_POLICY
        # Overridde rule with different checks than defaults so that we can
        # verify the rule overridden case.
        override_rules = {
            self.deprecated_policy: base_policy.RULE_ADMIN_OR_OWNER,
        }
        # NOTE(brinzhang): Only override the deprecated rule in policy file
        # so that we can verify if overridden checks are considered by
        # oslo.policy.
        # Oslo.policy will consider the overridden rules if:
        # 1. overridden deprecated rule's checks are different than defaults
        # 2. new rules are not present in policy file
        self.policy = self.useFixture(policy_fixture.OverridePolicyFixture(
                                      rules_in_file=override_rules))

    @mock.patch('nova.compute.api.InstanceActionAPI.actions_get')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_deprecated_policy_overridden_rule_is_checked(
            self, mock_instance_get, mock_actions_get):
        # Test to verify if deprecatd overridden policy is working.

        instance = fake_instance.fake_instance_obj(
            self.admin_or_owner_req.environ['nova.context'])

        # Check for success as admin_or_owner role. Deprecated rule
        # has been overridden with admin checks in policy.json
        # If admin role pass it means overridden rule is enforced by
        # olso.policy because new default is system reader and the old
        # default is admin.
        self.controller.index(self.admin_or_owner_req, instance['uuid'])

        # check for failure with reader context.
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.index,
                                self.reader_req,
                                instance['uuid'])
        self.assertEqual(
            "Policy doesn't allow os_compute_api:os-instance-actions:list "
            "to be performed.", exc.format_message())


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

    @mock.patch('nova.objects.InstanceActionEventList.get_by_action')
    @mock.patch('nova.objects.InstanceAction.get_by_request_id')
    def test_show_instance_action_policy_with_show_details(
            self, mock_get_action, mock_get_events):
        """Test to ensure skip checking policy rule
        'os_compute_api:os-instance-actions:show'.
        """
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.84')
        fake_action = self.fake_actions[FAKE_UUID][FAKE_REQUEST_ID]
        mock_get_action.return_value = fake_action
        fake_events = self.fake_events[fake_action['id']]
        fake_action['events'] = fake_events
        mock_get_events.return_value = fake_events
        fake_action_fmt = test_instance_actions.format_action(
            copy.deepcopy(fake_action))

        self._set_policy_rules(overwrite=False)
        rule_name = ia_policies.BASE_POLICY_NAME % "events:details"
        authorize_res, unauthorize_res = self.common_policy_check(
            self.system_reader_authorized_contexts,
            self.system_reader_unauthorized_contexts,
            rule_name, self.controller.show,
            self.req, self.instance['uuid'],
            fake_action['request_id'], fatal=False)

        for action in authorize_res:
            # Ensure the 'details' field in the action events
            for event in action['instanceAction']['events']:
                self.assertIn('details', event)
            # In order to unify the display forms of 'start_time' and
            # 'finish_time', format the results returned by the show api.
            res_fmt = test_instance_actions.format_action(
                action['instanceAction'])
            self.assertEqual(fake_action_fmt['events'], res_fmt['events'])

        # Because of the microversion > '2.51', that will be contain
        # 'events' in the os-instance-actions show api response, but the
        # 'details' should not contain in the action events.
        for action in unauthorize_res:
            # Ensure the 'details' field not in the action events
            for event in action['instanceAction']['events']:
                self.assertNotIn('details', event)


class InstanceActionsNoLegacyPolicyTest(InstanceActionsPolicyTest):
    """Test os-instance-actions APIs policies with system scope enabled,
    and no more deprecated rules that allow the legacy admin API to
    access system_admin_or_owner APIs.
    """
    without_deprecated_rules = True
    rules_without_deprecation = {
        ia_policies.BASE_POLICY_NAME % 'list':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        ia_policies.BASE_POLICY_NAME % 'show':
            base_policy.PROJECT_READER_OR_SYSTEM_READER,
        ia_policies.BASE_POLICY_NAME % 'events':
            base_policy.SYSTEM_READER,
    }

    def setUp(self):
        super(InstanceActionsNoLegacyPolicyTest, self).setUp()
        self.flags(enforce_scope=True, group="oslo_policy")

        # Check that system reader are able to get the
        # instance action events.
        self.system_reader_authorized_contexts = [
            self.system_admin_context, self.system_reader_context,
            self.system_member_context]
        # Check that non-system-reader are not able to
        # get the instance action events
        self.system_reader_unauthorized_contexts = [
            self.project_admin_context,
            self.system_foo_context, self.legacy_admin_context,
            self.other_project_member_context,
            self.project_foo_context, self.project_member_context,
            self.project_reader_context]

        # Check that system or projct reader is able to
        # show the instance actions events.
        self.project_or_system_reader_authorized_contexts = [
            self.system_admin_context,
            self.project_admin_context, self.system_member_context,
            self.system_reader_context, self.project_reader_context,
            self.project_member_context,
        ]

        # Check that non-system or non-project reader is not able to
        # show the instance actions events.
        self.project_or_system_reader_unauthorized_contexts = [
            self.legacy_admin_context, self.project_foo_context,
            self.system_foo_context, self.other_project_member_context
        ]

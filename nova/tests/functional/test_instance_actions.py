# Copyright 2016 IBM Corp.
#
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
from oslo_policy import policy as oslo_policy

from nova import exception
from nova import policy
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class InstanceActionsTestV2(integrated_helpers._IntegratedTestBase):
    """Tests Instance Actions API"""

    def test_get_instance_actions(self):
        server = self._create_server()
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual('create', actions[0]['action'])

    def test_get_instance_actions_deleted(self):
        server = self._create_server()
        self._delete_server(server)
        self.assertRaises(client.OpenStackApiNotFoundException,
                          self.api.get_instance_actions,
                          server['id'])


class InstanceActionsTestV21(InstanceActionsTestV2):
    api_major_version = 'v2.1'


class InstanceActionsTestV221(InstanceActionsTestV21):
    microversion = '2.21'

    def setUp(self):
        super(InstanceActionsTestV221, self).setUp()
        self.api.microversion = self.microversion

    def test_get_instance_actions_deleted(self):
        server = self._create_server()
        self._delete_server(server)
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual('delete', actions[0]['action'])
        self.assertEqual('create', actions[1]['action'])


class HypervisorError(Exception):
    """This is just used to make sure the exception type is in the events."""
    pass


class InstanceActionEventFaultsTestCase(
    test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Tests for the instance action event details reporting from the API"""

    def setUp(self):
        super(InstanceActionEventFaultsTestCase, self).setUp()
        # Setup the standard fixtures.
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(policy_fixture.RealPolicyFixture())

        # Start the compute services.
        self.start_service('conductor')
        self.start_service('scheduler')
        self.compute = self.start_service('compute')
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

    def _set_policy_rules(self, overwrite=True):
        rules = {'os_compute_api:os-instance-actions:show': '',
                 'os_compute_api:os-instance-actions:events:details':
                     'project_id:%(project_id)s'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules),
                         overwrite=overwrite)

    def test_instance_action_event_details_non_nova_exception(self):
        """Creates a server using the non-admin user, then reboot it which
        will generate a non-NovaException fault and put the instance into
        ERROR status. Then checks that fault details are visible.
        """

        # Create the server with the non-admin user.
        server = self._build_server(
            networks=[{'port': nova_fixtures.NeutronFixture.port_1['id']}])
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Stop the server before rebooting it so that after the driver.reboot
        # method raises an exception, the fake driver does not report the
        # instance power state as running - that will make the compute manager
        # set the instance vm_state to error.
        self.api.post_server_action(server['id'], {'os-stop': None})
        server = self._wait_for_state_change(server, 'SHUTOFF')

        # Stub out the compute driver reboot method to raise a non-nova
        # exception to simulate some error from the underlying hypervisor
        # which in this case we are going to say has sensitive content.
        error_msg = 'sensitive info'
        with mock.patch.object(
                self.compute.manager.driver, 'reboot',
                side_effect=HypervisorError(error_msg)) as mock_reboot:
            reboot_request = {'reboot': {'type': 'HARD'}}
            self.api.post_server_action(server['id'], reboot_request)
            # In this case we wait for the status to change to ERROR using
            # the non-admin user so we can assert the fault details. We also
            # wait for the task_state to be None since the wrap_instance_fault
            # decorator runs before the reverts_task_state decorator so we will
            # be sure the fault is set on the server.
            server = self._wait_for_server_parameter(
                server, {'status': 'ERROR', 'OS-EXT-STS:task_state': None},
                api=self.api)
            mock_reboot.assert_called_once()

        self._set_policy_rules(overwrite=False)

        server_id = server['id']
        # Calls GET on the server actions and verifies that the reboot
        # action expected in the response.
        response = self.api.api_get('/servers/%s/os-instance-actions' %
                                    server_id)
        server_actions = response.body['instanceActions']
        for actions in server_actions:
            if actions['action'] == 'reboot':
                reboot_request_id = actions['request_id']
        # non admin shows instance actions details and verifies the 'details'
        # in the action events via 'request_id', since microversion 2.51 that
        # we can show events, but in microversion 2.84 that we can show
        # 'details' for non-admin.
        self.api.microversion = '2.84'
        action_events_response = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' % (server_id,
                                                    reboot_request_id))
        reboot_action = action_events_response.body['instanceAction']
        # Since reboot action failed, the 'message' property in reboot action
        # should be 'Error', otherwise it's None.
        self.assertEqual('Error', reboot_action['message'])
        reboot_action_events = reboot_action['events']
        # The instance action events from the non-admin user API response
        # should not have 'traceback' in it.
        self.assertNotIn('traceback', reboot_action_events[0])
        # And the sensitive details from the non-nova exception should not be
        # in the details.
        self.assertIn('details', reboot_action_events[0])
        self.assertNotIn(error_msg, reboot_action_events[0]['details'])
        # The exception type class name should be in the details.
        self.assertIn('HypervisorError', reboot_action_events[0]['details'])

        # Get the server fault details for the admin user.
        self.admin_api.microversion = '2.84'
        action_events_response = self.admin_api.api_get(
            '/servers/%s/os-instance-actions/%s' % (server_id,
                                                    reboot_request_id))
        reboot_action = action_events_response.body['instanceAction']
        self.assertEqual('Error', reboot_action['message'])
        reboot_action_events = reboot_action['events']
        # The admin can see the fault details which includes the traceback,
        # and make sure the traceback is there by looking for part of it.
        self.assertIn('traceback', reboot_action_events[0])
        self.assertIn('in reboot_instance',
                      reboot_action_events[0]['traceback'])
        # The exception type class name should be in the details for the admin
        # user as well since the fault handling code cannot distinguish who
        # is going to see the message so it only sets class name.
        self.assertIn('HypervisorError', reboot_action_events[0]['details'])

    def test_instance_action_event_details_with_nova_exception(self):
        """Creates a server using the non-admin user, then reboot it which
        will generate a nova exception fault and put the instance into
        ERROR status. Then checks that fault details are visible.
        """

        # Create the server with the non-admin user.
        server = self._build_server(
            networks=[{'port': nova_fixtures.NeutronFixture.port_1['id']}])
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Stop the server before rebooting it so that after the driver.reboot
        # method raises an exception, the fake driver does not report the
        # instance power state as running - that will make the compute manager
        # set the instance vm_state to error.
        self.api.post_server_action(server['id'], {'os-stop': None})
        server = self._wait_for_state_change(server, 'SHUTOFF')

        # Stub out the compute driver reboot method to raise a nova
        # exception 'InstanceRebootFailure' to simulate some error.
        exc_reason = 'reboot failure'
        with mock.patch.object(
                self.compute.manager.driver, 'reboot',
                side_effect=exception.InstanceRebootFailure(reason=exc_reason)
            ) as mock_reboot:
            reboot_request = {'reboot': {'type': 'HARD'}}
            self.api.post_server_action(server['id'], reboot_request)
            # In this case we wait for the status to change to ERROR using
            # the non-admin user so we can assert the fault details. We also
            # wait for the task_state to be None since the wrap_instance_fault
            # decorator runs before the reverts_task_state decorator so we will
            # be sure the fault is set on the server.
            server = self._wait_for_server_parameter(
                server, {'status': 'ERROR', 'OS-EXT-STS:task_state': None},
                api=self.api)
            mock_reboot.assert_called_once()

        self._set_policy_rules(overwrite=False)

        server_id = server['id']
        # Calls GET on the server actions and verifies that the reboot
        # action expected in the response.
        response = self.api.api_get('/servers/%s/os-instance-actions' %
                                    server_id)
        server_actions = response.body['instanceActions']
        for actions in server_actions:
            if actions['action'] == 'reboot':
                reboot_request_id = actions['request_id']

        # non admin shows instance actions details and verifies the 'details'
        # in the action events via 'request_id', since microversion 2.51 that
        # we can show events, but in microversion 2.84 that we can show
        # 'details' for non-admin.
        self.api.microversion = '2.84'
        action_events_response = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' % (server_id,
                                                    reboot_request_id))
        reboot_action = action_events_response.body['instanceAction']
        # Since reboot action failed, the 'message' property in reboot action
        # should be 'Error', otherwise it's None.
        self.assertEqual('Error', reboot_action['message'])
        reboot_action_events = reboot_action['events']
        # The instance action events from the non-admin user API response
        # should not have 'traceback' in it.
        self.assertNotIn('traceback', reboot_action_events[0])
        # The nova exception format message should be in the details.
        self.assertIn('details', reboot_action_events[0])
        self.assertIn(exc_reason, reboot_action_events[0]['details'])

        # Get the server fault details for the admin user.
        self.admin_api.microversion = '2.84'
        action_events_response = self.admin_api.api_get(
            '/servers/%s/os-instance-actions/%s' % (server_id,
                                                    reboot_request_id))
        reboot_action = action_events_response.body['instanceAction']
        self.assertEqual('Error', reboot_action['message'])
        reboot_action_events = reboot_action['events']
        # The admin can see the fault details which includes the traceback,
        # and make sure the traceback is there by looking for part of it.
        self.assertIn('traceback', reboot_action_events[0])
        self.assertIn('in reboot_instance',
                      reboot_action_events[0]['traceback'])
        # The nova exception format message should be in the details.
        self.assertIn(exc_reason, reboot_action_events[0]['details'])

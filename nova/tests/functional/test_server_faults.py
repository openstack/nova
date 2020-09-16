# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class HypervisorError(Exception):
    """This is just used to make sure the exception type is in the fault."""
    pass


class ServerFaultTestCase(test.TestCase,
                          integrated_helpers.InstanceHelperMixin):
    """Tests for the server faults reporting from the API."""

    def setUp(self):
        super(ServerFaultTestCase, self).setUp()
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(policy_fixture.RealPolicyFixture())

        # Start the compute services.
        self.start_service('conductor')
        self.start_service('scheduler')
        self.compute = self.start_service('compute')
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

    def test_server_fault_non_nova_exception(self):
        """Creates a server using the non-admin user, then reboots it which
        will generate a non-NovaException fault and put the instance into
        ERROR status. Then checks that fault details are only visible to the
        admin user.
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
        # The server fault from the non-admin user API response should not
        # have details in it.
        self.assertIn('fault', server)
        fault = server['fault']
        self.assertNotIn('details', fault)
        # And the sensitive details from the non-nova exception should not be
        # in the message.
        self.assertIn('message', fault)
        self.assertNotIn(error_msg, fault['message'])
        # The exception type class name should be in the message.
        self.assertIn('HypervisorError', fault['message'])

        # Get the server fault details for the admin user.
        server = self.admin_api.get_server(server['id'])
        fault = server['fault']
        # The admin can see the fault details which includes the traceback.
        self.assertIn('details', fault)
        # The details also contain the exception message (which is not in the
        # fault message).
        self.assertIn(error_msg, fault['details'])
        # Make sure the traceback is there by looking for part of it.
        self.assertIn('in reboot_instance', fault['details'])
        # The exception type class name should be in the message for the admin
        # user as well since the fault handling code cannot distinguish who
        # is going to see the message so it only sets class name.
        self.assertIn('HypervisorError', fault['message'])

# Copyright 2017 IBM Corp.
#
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

import time

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.unit import cast_as_call
from nova.tests.unit import policy_fixture


class TestDeleteFromCell0CheckQuota(test.TestCase):
    """This tests a regression introduced in the Ocata release.

    In Ocata we started building instances in conductor for cells v2. If we
    can't schedule the instance, it gets put into ERROR state, the instance
    record is created in the cell0 database and the BuildRequest is deleted.

    In the API:

    1) quota.reserve creates a reservation record and updates the resource
       usage record to increment 'reserved' which is counted as part of
       usage.
    2) quota.commit deletes the reservation record and updates the resource
       usage record to decrement 'reserved' and increment 'in_use' which is
       counted as part of usage

    When the user deletes the instance, the API code sees that the instance is
    living in cell0 and deletes it from cell0. The original quota reservation
    was made in the cell (nova) database and usage was not decremented.

    So a user that has several failed instance builds eventually runs out of
    quota even though they successfully deleted their servers.
    """

    def setUp(self):
        super(TestDeleteFromCell0CheckQuota, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api

        self.start_service('conductor')
        self.start_service('scheduler')

        # We don't actually start a compute service; this way we don't have any
        # compute hosts to schedule the instance to and will go into error and
        # be put into cell0.

        self.useFixture(cast_as_call.CastAsCall(self))

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def _wait_for_instance_status(self, server_id, status):
        timeout = 0.0
        server = self.api.get_server(server_id)
        while server['status'] != status and timeout < 10.0:
            time.sleep(.1)
            timeout += .1
            server = self.api.get_server(server_id)
        if server['status'] != status:
            self.fail('Timed out waiting for server %s to have status: %s.' %
                      (server_id, status))
        return server

    def _wait_for_instance_delete(self, server_id):
        timeout = 0.0
        while timeout < 10.0:
            try:
                server = self.api.get_server(server_id)
            except client.OpenStackApiNotFoundException:
                # the instance is gone so we're happy
                return
            else:
                time.sleep(.1)
                timeout += .1

        self.fail('Timed out waiting for server %s to be deleted. '
                  'Current vm_state: %s. Current task_state: %s' %
                  (server_id, server['OS-EXT-STS:vm_state'],
                   server['OS-EXT-STS:task_state']))

    def _delete_server(self, server):
        try:
            self.api.delete_server(server['id'])
        except client.OpenStackApiNotFoundException:
            pass

    def test_delete_error_instance_in_cell0_and_check_quota(self):
        """Tests deleting the error instance in cell0 and quota.

        This test will create the server which will fail to schedule because
        there is no compute to send it to. This will trigger the conductor
        manager to put the instance into ERROR state and create it in cell0.

        The test asserts that quota was decremented. Then it deletes the
        instance and will check quota again after the instance is gone.
        """
        # Get the current quota usage
        starting_usage = self.api.get_limits()

        # Create the server which we expect to go into ERROR state.
        server = dict(
            name='cell0-quota-test',
            imageRef=self.image_id,
            flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server})
        self.addCleanup(self._delete_server, server)
        self._wait_for_instance_status(server['id'], 'ERROR')

        # Check quota to see we've incremented usage by 1.
        current_usage = self.api.get_limits()
        self.assertEqual(starting_usage['absolute']['totalInstancesUsed'] + 1,
                         current_usage['absolute']['totalInstancesUsed'])

        # Now delete the server and wait for it to be gone.
        self._delete_server(server)
        self._wait_for_instance_delete(server['id'])

        # Now check the quota again. Since the bug is fixed, ending usage
        # should be current usage - 1.
        ending_usage = self.api.get_limits()
        self.assertEqual(current_usage['absolute']['totalInstancesUsed'] - 1,
                         ending_usage['absolute']['totalInstancesUsed'])

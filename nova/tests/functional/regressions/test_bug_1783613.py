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

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestDeleteWhileBootingInstanceNotFound(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """This tests a regression in the Ocata release.

    In Ocata we started building instances in conductor for cells v2. If create
    and delete requests are racing, we can have a situation where we never
    decrement the quota during a delete.

    In the API:

    When the user deletes an instance while it is booting, we first try to
    delete the build request record. If we succeed in doing that, we will
    expect the boot process to be halted by conductor.

    When conductor finds the build request gone, it knows that the user has
    requested a delete from the API and will start cleaning up resources. This
    includes deleting the instance record, if it has already been created, and
    it is created before the conductor tries to delete the build request.

    If the API succeeds in deleting the build request, it looks up the instance
    record and will only decrement quota if it finds the instance. The problem
    is that the instance can be NotFound if:

    a) Conductor has not yet created the instance record or
    b) Conductor deleted the instance record after finding the API deleted it

    So if this happens during a race between create and delete, we will never
    decrement the quota.
    """

    def setUp(self):
        super(TestDeleteWhileBootingInstanceNotFound, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        # This is needed for the network_api.validate_networks check in the API
        self.useFixture(nova_fixtures.NeutronFixture(self))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        # NOTE(melwitt): We intentionally do not start a conductor service in
        # this test because we want to force the ordering such that the API
        # deletes the build request during a concurrent DELETE from the user
        # while the instance is being created, before the conductor has a
        # chance to delete the build request as part of the create flow.

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

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

    def _delete_server(self, server_id):
        try:
            self.api.delete_server(server_id)
        except client.OpenStackApiNotFoundException:
            pass

    def test_delete_while_booting_instance_lookup_fails(self):
        # Get the current quota usage
        starting_usage = self.api.get_limits()

        server_req = dict(name='test', imageRef=self.image_id,
                          flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server_req})

        # Check quota to see we've incremented usage by 1.
        current_usage = self.api.get_limits()
        self.assertEqual(starting_usage['absolute']['totalInstancesUsed'] + 1,
                         current_usage['absolute']['totalInstancesUsed'])
        self.assertEqual(starting_usage['absolute']['totalCoresUsed'] + 1,
                         current_usage['absolute']['totalCoresUsed'])
        self.assertEqual(starting_usage['absolute']['totalRAMUsed'] + 512,
                         current_usage['absolute']['totalRAMUsed'])

        # Stub out the API to make the instance lookup fail, simulating if
        # conductor hadn't yet created it yet or deleted it after the build
        # request was deleted by the API.
        self.stub_out('nova.compute.api.API._lookup_instance',
                      lambda *a, **k: (None, None))

        # Now delete the server and wait for it to be gone.
        self._delete_server(server['id'])
        self._wait_for_instance_delete(server['id'])

        # Now check the quota again. Since the bug is fixed, ending usage
        # should be current usage - 1.
        ending_usage = self.api.get_limits()
        self.assertEqual(current_usage['absolute']['totalInstancesUsed'] - 1,
                         ending_usage['absolute']['totalInstancesUsed'])
        self.assertEqual(current_usage['absolute']['totalCoresUsed'] - 1,
                         ending_usage['absolute']['totalCoresUsed'])
        self.assertEqual(current_usage['absolute']['totalRAMUsed'] - 512,
                         ending_usage['absolute']['totalRAMUsed'])

    def test_delete_while_booting_instance_destroy_fails(self):
        # Get the current quota usage
        starting_usage = self.api.get_limits()

        server_req = dict(name='test', imageRef=self.image_id,
                          flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server_req})

        # Check quota to see we've incremented usage by 1.
        current_usage = self.api.get_limits()
        self.assertEqual(starting_usage['absolute']['totalInstancesUsed'] + 1,
                         current_usage['absolute']['totalInstancesUsed'])
        self.assertEqual(starting_usage['absolute']['totalCoresUsed'] + 1,
                         current_usage['absolute']['totalCoresUsed'])
        self.assertEqual(starting_usage['absolute']['totalRAMUsed'] + 512,
                         current_usage['absolute']['totalRAMUsed'])

        # Stub out the API to make the instance destroy raise InstanceNotFound,
        # simulating if conductor already deleted it.
        # If conductor deleted the instance out from under us in the API
        # *after* we looked up the instance and found it, we will get
        # InstanceNotFound from instance.destroy() and quotas.rollback() won't
        # be the right choice. It's only the right choice if we're racing with
        # another delete request, not if we're racing with a create request.
        def fake_destroy(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id=server['id'])

        self.stub_out('nova.objects.Instance.destroy', fake_destroy)

        # Now delete the server and wait for it to be gone.
        self._delete_server(server['id'])
        self._wait_for_instance_delete(server['id'])

        # Now check the quota again. Since the bug is fixed, ending usage
        # should be current usage - 1.
        ending_usage = self.api.get_limits()
        self.assertEqual(current_usage['absolute']['totalInstancesUsed'] - 1,
                         ending_usage['absolute']['totalInstancesUsed'])
        self.assertEqual(current_usage['absolute']['totalCoresUsed'] - 1,
                         ending_usage['absolute']['totalCoresUsed'])
        self.assertEqual(current_usage['absolute']['totalRAMUsed'] - 512,
                         ending_usage['absolute']['totalRAMUsed'])

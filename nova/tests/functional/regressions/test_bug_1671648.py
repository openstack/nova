# Copyright 2017 Huawei Technologies Co.,LTD.
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

from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import cast_as_call
from nova.tests.unit import fake_network
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestRetryBetweenComputeNodeBuilds(test.TestCase):
    """This tests a regression introduced in the Ocata release.

    In Ocata we started building instances in conductor for cells v2. That
    uses a new "schedule_and_build_instances" in the ConductorManager rather
    than the old "build_instances" method and duplicates a lot of the same
    logic, but it missed populating the "retry" value in the scheduler filter
    properties. As a result, failures to build an instance on a compute node
    which would normally result in a retry of the build on another compute
    node are not actually happening.
    """

    def setUp(self):
        super(TestRetryBetweenComputeNodeBuilds, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())

        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))

        # This stubs out the network allocation in compute.
        fake_network.set_stub_network_methods(self)

        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        self.useFixture(nova_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        # The admin API is used to get the server details to verify the
        # host on which the server was built.
        self.admin_api = api_fixture.admin_api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.start_service('conductor')
        self.start_service('consoleauth')

        # Configure a minimal filter scheduler setup.
        self.flags(enabled_filters=['ComputeFilter'],
                   group='filter_scheduler')
        self.start_service('scheduler')

        # We start two compute services because we're going to fake one
        # of them to fail the build so we can trigger the retry code.
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.image_id = self.admin_api.get_images()[0]['id']
        self.flavor_id = self.admin_api.get_flavors()[0]['id']

        # This is our flag that we set when we hit the first host and
        # made it fail.
        self.failed_host = None
        self.attempts = 0

        def fake_claim_init(_self, ctxt, instance, nodename, tracker,
                            *args, **kwargs):
            self.attempts += 1
            if self.failed_host is None:
                # Set the failed_host value to the
                # ResourceTracker.host value.
                self.failed_host = tracker.host
                raise exception.ComputeResourcesUnavailable(
                    reason='failure on host %s' % tracker.host)
            # We have to set this since we are stubbing out Claim.__init__
            # and self.claimed_numa_topology is set in the parent class' init.
            _self.claimed_numa_topology = None

        self.stub_out('nova.compute.claims.Claim.__init__', fake_claim_init)

    def _wait_for_instance_status(self, server_id, status):
        timeout = 0.0
        server = self.admin_api.get_server(server_id)
        while server['status'] != status and timeout < 10.0:
            time.sleep(.1)
            timeout += .1
            server = self.admin_api.get_server(server_id)
        if server['status'] != status:
            self.fail('Timed out waiting for server %s to have status: %s. '
                      'Current status: %s. Build attempts: %s' %
                      (server_id, status, server['status'], self.attempts))
        return server

    def test_retry_build_on_compute_error(self):
        """Tests the retry operation between compute nodes when one fails.

        This tests the scenario that we have two compute services and we
        try to build a single server. The test is setup such that the
        scheduler picks the first host which we mock out to fail the claim.
        This should then trigger a retry to the second host.
        """
        # Create the server which we expect to go to ERROR state because
        # of the regression bug. Once the bug is fixed, we should assert
        # that the server goes to ACTIVE status and is on the second host
        # after the retry operation.
        server = dict(
            name='retry-test',
            imageRef=self.image_id,
            flavorRef=self.flavor_id)
        server = self.admin_api.post_server({'server': server})
        self.addCleanup(self.admin_api.delete_server, server['id'])
        server = self._wait_for_instance_status(server['id'], 'ERROR')

        # Assert that there is no host for the failed server. This should
        # assert that the host is not the failed host once the bug is fixed.
        self.assertIsNone(server['OS-EXT-SRV-ATTR:hypervisor_hostname'])

        # Assert that we did not retry. Once the bug is fixed, this should
        # be equal to 2.
        self.assertEqual(1, self.attempts)

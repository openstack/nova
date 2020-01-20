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

import nova.compute
from nova import exception
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class PinnedComputeRpcTests(integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        # Use a custom weigher to make sure that we have a predictable host
        # selection order during scheduling
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        super(PinnedComputeRpcTests, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')
        self.compute3 = self._start_compute(host='host3')

    def _test_reschedule_migration_with_compute_rpc_pin(self, version_cap):
        self.flags(compute=version_cap, group='upgrade_levels')

        server_req = self._build_server(networks='none')
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(server, 'ACTIVE')

        orig_claim = nova.compute.resource_tracker.ResourceTracker.resize_claim
        claim_calls = []

        def fake_orig_claim(
                _self, context, instance, instance_type, nodename,
                *args, **kwargs):
            if not claim_calls:
                claim_calls.append(nodename)
                raise exception.ComputeResourcesUnavailable(
                    reason='Simulated claim failure')
            else:
                claim_calls.append(nodename)
                return orig_claim(
                    _self, context, instance, instance_type, nodename, *args,
                    **kwargs)

        with mock.patch(
                'nova.compute.resource_tracker.ResourceTracker.resize_claim',
                new=fake_orig_claim):
            # Now migrate the server which is going to fail on the first
            # destination but then will be rescheduled.
            self.api.post_server_action(server['id'], {'migrate': None})

            # We expect that the instance is on host3 as the scheduler
            # selected host2 due to our weigher and the cold migrate failed
            # there and re-scheduled to host3 were it succeeded.
            self._wait_for_server_parameter(server, {
                'OS-EXT-SRV-ATTR:host': 'host3',
                'OS-EXT-STS:task_state': None,
                'status': 'VERIFY_RESIZE'})

        # we ensure that there was a failed and then a successful claim call
        self.assertEqual(['host2', 'host3'], claim_calls)

    def test_reschedule_migration_5_1(self):
        self._test_reschedule_migration_with_compute_rpc_pin('5.1')

    def test_reschedule_migration_5_0(self):
        self._test_reschedule_migration_with_compute_rpc_pin('5.0')

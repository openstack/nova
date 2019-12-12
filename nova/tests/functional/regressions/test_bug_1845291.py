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

import nova
from nova import exception
from nova.tests.functional import integrated_helpers


class ForcedHostMissingReScheduleTestCase(
    integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(ForcedHostMissingReScheduleTestCase, self).setUp()
        self._start_compute(host="host1")
        self._start_compute(host="host2")
        self._start_compute(host="host3")

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_boot_with_az_and_host_then_migrate_re_schedules(self):
        """Ensure that re-schedule is possible on migration even if the server
        is originally booted with forced host.

        The _boot_and_check_allocations() will start a server forced to host1.
        Then a migration is triggered. Both host2 and host3 are valid targets.
        But the test mocks resize_claim to make the first dest host fail and
        expects that nova will try the alternative host.
        """

        server = self._boot_and_check_allocations(
            self.flavor1, 'host1')

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
            # destination but then will expect to be rescheduled.
            self.api.post_server_action(server['id'], {'migrate': None})

            # We expect that the instance re-scheduled but successfully ended
            # up on the second destination host.
            self._wait_for_server_parameter(server, {
                 'OS-EXT-STS:task_state': None,
                 'status': 'VERIFY_RESIZE'})

        # we ensure that there was a failed and then a successful claim call
        self.assertEqual(2, len(claim_calls))

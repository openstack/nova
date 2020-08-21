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
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class BuildRescheduleClaimFailsTestCase(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Regression test case for bug 1837955 where a server build fails on the
    primary host and then attempting to allocate resources on the alternate
    host, the alternate host is full and the allocations claim in placement
    fails, resulting in the build failing due to MaxRetriesExceeded and the
    server going to ERROR status.
    """
    compute_driver = 'fake.SmallFakeDriver'

    def _wait_for_unversioned_notification(self, event_type):
        for x in range(20):  # wait up to 10 seconds
            for notification in fake_notifier.NOTIFICATIONS:
                if notification.event_type == event_type:
                    return notification
            time.sleep(.5)
        self.fail('Timed out waiting for unversioned notification %s. Got: %s'
                  % (event_type, fake_notifier.NOTIFICATIONS))

    def test_build_reschedule_alt_host_alloc_fails(self):
        # Start two compute services so we have one alternate host.
        # Set cpu_allocation_ratio=1.0 to make placement inventory
        # and allocations for VCPU easier to manage.
        self.flags(cpu_allocation_ratio=1.0)
        for x in range(2):
            self._start_compute('host%i' % x)

        def fake_instance_claim(_self, _context, _inst, nodename, *a, **kw):
            # Before triggering the reschedule to the other host, max out the
            # capacity on the alternate host.
            alt_nodename = 'host0' if nodename == 'host1' else 'host1'
            rp_uuid = self._get_provider_uuid_by_host(alt_nodename)
            inventories = self._get_provider_inventory(rp_uuid)
            # Fake some other consumer taking all of the VCPU on the alt host.
            # Since we set cpu_allocation_ratio=1.0 the total is the total
            # capacity for VCPU on the host.
            total_vcpu = inventories['VCPU']['total']
            alt_consumer = '7d32d0bc-af16-44b2-8019-a24925d76152'
            allocs = {
                'allocations': {
                    rp_uuid: {
                        'resources': {
                            'VCPU': total_vcpu
                        }
                    }
                },
                'project_id': self.api.project_id,
                'user_id': self.api.project_id
            }
            resp = self.placement.put(
                '/allocations/%s' % alt_consumer, allocs, version='1.12')
            self.assertEqual(204, resp.status, resp.content)
            raise exception.ComputeResourcesUnavailable(reason='overhead!')

        # Stub out the instance claim (regardless of which host the scheduler
        # picks as the primary) to trigger a reschedule.
        self.stub_out('nova.compute.manager.resource_tracker.ResourceTracker.'
                      'instance_claim', fake_instance_claim)

        # Now that our stub is in place, try to create a server and wait for it
        # to go to ERROR status.
        server_req = self._build_server(
            networks=[{'port': self.neutron.port_1['id']}])
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(server, 'ERROR')

        # Wait for the MaxRetriesExceeded fault to be recorded.
        # set_vm_state_and_notify sets the vm_state to ERROR before the fault
        # is recorded but after the notification is sent. So wait for the
        # unversioned notification to show up and then get the fault.
        self._wait_for_unversioned_notification(
            'compute_task.build_instances')
        server = self.api.get_server(server['id'])
        self.assertIn('fault', server)
        self.assertIn('Exceeded maximum number of retries',
                      server['fault']['message'])

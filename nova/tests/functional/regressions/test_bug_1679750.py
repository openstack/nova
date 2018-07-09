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

from nova.scheduler.client import report as reportclient
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestLocalDeleteAllocations(test.TestCase,
                                 integrated_helpers.InstanceHelperMixin):
    def setUp(self):
        super(TestLocalDeleteAllocations, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        # The NeutronFixture is needed to show security groups for a server.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        placement = self.useFixture(nova_fixtures.PlacementFixture())
        self.placement_api = placement.api
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        # We need the latest microversion to force-down the compute service
        self.admin_api.microversion = 'latest'
        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.start_service('conductor')
        self.start_service('consoleauth')

        self.flags(enabled_filters=['RetryFilter', 'ComputeFilter'],
                   group='filter_scheduler')
        self.start_service('scheduler')

        self.compute = self.start_service('compute')

        self.useFixture(cast_as_call.CastAsCall(self))

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def _get_usages(self, rp_uuid):
        fmt = '/resource_providers/%(uuid)s/usages'
        resp = self.placement_api.get(fmt % {'uuid': rp_uuid})
        return resp.body['usages']

    # NOTE(mriedem): It would be preferable to use the PlacementFixture as
    # a context manager but that causes some issues when trying to delete the
    # server in test_local_delete_removes_allocations_after_compute_restart.
    def _stub_compute_api_to_not_configure_placement(self):
        """Prior to the compute API deleting allocations in the "local delete"
        case, nova.conf for nova-api might not be configured for talking to
        the placement service, so we can mock that behavior by stubbing out
        the placement client in the compute API to no-op as if safe_connect
        failed and returned None to the caller.
        """
        orig_delete_alloc = (
            reportclient.SchedulerReportClient.delete_allocation_for_instance)
        self.call_count = 0

        def fake_delete_allocation_for_instance(*args, **kwargs):
            # The first call will be from the API, so ignore that one and
            # return None like the @safe_connect decorator would if nova-api
            # wasn't configured to talk to placement.
            if self.call_count:
                orig_delete_alloc(*args, **kwargs)
            else:
                self.call_count += 1

        self.stub_out('nova.scheduler.client.report.SchedulerReportClient.'
                      'delete_allocation_for_instance',
                      fake_delete_allocation_for_instance)

    def test_local_delete_removes_allocations_after_compute_restart(self):
        """Tests that allocations are removed after a local delete.

        This tests the scenario where a server is local deleted (because the
        compute host is down) and we want to make sure that its allocations
        have been cleaned up once the nova-compute service restarts.
        """
        self._stub_compute_api_to_not_configure_placement()
        # Get allocations, make sure they are 0.
        resp = self.placement_api.get('/resource_providers')
        rp_uuid = resp.body['resource_providers'][0]['uuid']
        usages_before = self._get_usages(rp_uuid)
        for usage in usages_before.values():
            self.assertEqual(0, usage)

        # Create a server.
        server = self._build_minimal_create_server_request(self.api,
            'local-delete-test', self.image_id, self.flavor_id, 'none')
        server = self.admin_api.post_server({'server': server})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Assert usages are non zero now.
        usages_during = self._get_usages(rp_uuid)
        for usage in usages_during.values():
            self.assertNotEqual(0, usage)

        # Force-down compute to trigger local delete.
        self.compute.stop()
        compute_service_id = self.admin_api.get_services(
            host=self.compute.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute_service_id, {'forced_down': True})

        # Delete the server (will be a local delete because compute is down).
        self.api.delete_server(server['id'])

        # Assert usages are still non-zero.
        usages_during = self._get_usages(rp_uuid)
        for usage in usages_during.values():
            self.assertNotEqual(0, usage)

        # Start the compute service again. Before it comes up, it will call the
        # update_available_resource code in the ResourceTracker which is what
        # "heals" the allocations for the deleted instance.
        self.compute.start()

        # Get the allocations again to check against the original.
        usages_after = self._get_usages(rp_uuid)

        # They should match.
        self.assertEqual(usages_before, usages_after)

    def test_local_delete_removes_allocations_from_api(self):
        """Tests that the compute API deletes allocations when the compute
        service on which the instance was running is down.
        """
        # Get allocations, make sure they are 0.
        resp = self.placement_api.get('/resource_providers')
        rp_uuid = resp.body['resource_providers'][0]['uuid']
        usages_before = self._get_usages(rp_uuid)
        for usage in usages_before.values():
            self.assertEqual(0, usage)

        # Create a server.
        server = self._build_minimal_create_server_request(self.api,
            'local-delete-test', self.image_id, self.flavor_id, 'none')
        server = self.admin_api.post_server({'server': server})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Assert usages are non zero now.
        usages_during = self._get_usages(rp_uuid)
        for usage in usages_during.values():
            self.assertNotEqual(0, usage)

        # Force-down compute to trigger local delete.
        self.compute.stop()
        compute_service_id = self.admin_api.get_services(
            host=self.compute.host, binary='nova-compute')[0]['id']
        self.admin_api.put_service(compute_service_id, {'forced_down': True})

        # Delete the server (will be a local delete because compute is down).
        self.api.delete_server(server['id'])

        # Get the allocations again to make sure they were deleted.
        usages_after = self._get_usages(rp_uuid)

        # They should match.
        self.assertEqual(usages_before, usages_after)

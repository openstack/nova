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

from nova.compute import instance_actions
from nova.scheduler.client import query as query_client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image


class DeletedServerAllocationRevertTest(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests for bug 1848343 introduced in Queens where reverting a
    migration-based allocation can re-create and leak allocations for a
    deleted server if the server is deleted during a migration (resize,
    cold or live).
    """
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(DeletedServerAllocationRevertTest, self).setUp()
        # Start two computes so we can migrate between them.
        self._start_compute('host1')
        self._start_compute('host2')

    def _create_server(self, name):
        """Creates a server with the given name and returns the server,
        source host and target host.
        """
        server = self._build_minimal_create_server_request(
            self.api, name, image_uuid=fake_image.get_valid_image_id(),
            networks='none')
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        source_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host2' if source_host == 'host1' else 'host1'
        return server, source_host, target_host

    def _assert_no_allocations(self, server):
        # There should be no allocations on either host1 or host2.
        providers = self._get_all_providers()
        for rp in providers:
            allocations = self._get_allocations_by_provider_uuid(rp['uuid'])
            # FIXME(mriedem): This is bug 1848343 where rollback
            # reverts the allocations and moves the source host allocations
            # held by the migration consumer back to the now-deleted instance
            # consumer.
            if rp['name'] == server['OS-EXT-SRV-ATTR:host']:
                self.assertFlavorMatchesAllocation(
                    server['flavor'], server['id'], rp['uuid'])
            else:
                self.assertEqual({}, allocations,
                                 'Leaked allocations on provider: %s (%s)' %
                                 (rp['uuid'], rp['name']))

    def test_migration_task_rollback(self):
        """Tests a scenario where the MigrationTask swaps the allocations
        for a cold migrate (or resize, it does not matter) and then fails and
        rolls back allocations before RPC casting to prep_resize on the dest
        host.
        """
        server, source_host, target_host = self._create_server(
            'test_migration_task_rollback')
        # Disable the target compute service to trigger a NoValidHost from
        # the scheduler which happens after MigrationTask has moved the source
        # node allocations to the migration record.
        target_service = self.computes[target_host].service_ref
        self.api.put_service(target_service.uuid, {'status': 'disabled'})

        # Wrap the select_destinations call so we can delete the server
        # concurrently while scheduling.
        original_select_dests = \
            query_client.SchedulerQueryClient.select_destinations

        def wrap_select_dests(*args, **kwargs):
            # Simulate concurrently deleting the server while scheduling.
            self.api.delete_server(server['id'])
            self._wait_until_deleted(server)
            return original_select_dests(*args, **kwargs)

        self.stub_out('nova.scheduler.client.query.SchedulerQueryClient.'
                      'select_destinations', wrap_select_dests)

        # Now start the cold migration which will fail due to NoValidHost.
        # Note that we get a 404 back because this is a blocking call until
        # conductor RPC casts to prep_resize on the selected dest host but
        # we never get that far.
        self.api.post_server_action(server['id'], {'migrate': None},
                                    check_response_status=[404])
        # We cannot monitor the migration from the API since it is deleted
        # when the instance is deleted so just wait for the failed instance
        # action event after the task rollback happens.
        self._wait_for_action_fail_completion(
            server, instance_actions.MIGRATE, 'cold_migrate', api=self.api)
        self._assert_no_allocations(server)

    # TODO(mriedem): Should have similar tests for live migration and
    # resize failing in the compute service rather than conductor.

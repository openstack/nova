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
from nova.compute import manager as compute_manager
from nova.scheduler.client import query as query_client
from nova.tests.functional import integrated_helpers


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

    def _create_server(self):
        """Creates and return a server along with a source host and target
        host.
        """
        server = super()._create_server(networks='none')
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

    def _disable_target_host(self, target_host):
        # Disable the target compute service to trigger a NoValidHost from
        # the scheduler which happens after conductor has moved the source
        # node allocations to the migration record.
        target_service = self.computes[target_host].service_ref
        self.api.put_service(target_service.uuid, {'status': 'disabled'})

    def _stub_delete_server_during_scheduling(self, server):
        # Wrap the select_destinations call so we can delete the server
        # concurrently while scheduling.
        original_select_dests = \
            query_client.SchedulerQueryClient.select_destinations

        def wrap_select_dests(*args, **kwargs):
            # Simulate concurrently deleting the server while scheduling.
            self._delete_server(server)
            return original_select_dests(*args, **kwargs)

        self.stub_out('nova.scheduler.client.query.SchedulerQueryClient.'
                      'select_destinations', wrap_select_dests)

    def test_migration_task_rollback(self):
        """Tests a scenario where the MigrationTask swaps the allocations
        for a cold migrate (or resize, it does not matter) and then fails and
        rolls back allocations before RPC casting to prep_resize on the dest
        host.
        """
        server, source_host, target_host = self._create_server()
        self._disable_target_host(target_host)
        self._stub_delete_server_during_scheduling(server)

        # Now start the cold migration which will fail due to NoValidHost.
        self.api.post_server_action(server['id'], {'migrate': None},
                                    check_response_status=[202])
        # We cannot monitor the migration from the API since it is deleted
        # when the instance is deleted so just wait for the failed instance
        # action event after the task rollback happens.
        # Note that we get InstanceNotFound rather than NoValidHost because
        # the NoValidHost handler in ComputeTaskManager._cold_migrate calls
        # _set_vm_state_and_notify which raises InstanceNotFound and masks
        # the NoValidHost error.
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'InstanceNotFound')
        self._assert_no_allocations(server)

    def test_live_migration_task_rollback(self):
        """Tests a scenario where the LiveMigrationTask swaps the allocations
        for a live migration and then fails and rolls back allocations before
        RPC casting to live_migration on the source host.
        """
        server, source_host, target_host = self._create_server()
        self._disable_target_host(target_host)
        self._stub_delete_server_during_scheduling(server)

        # Now start the live migration which will fail due to NoValidHost.
        body = {'os-migrateLive': {'host': None, 'block_migration': 'auto'}}
        self.api.post_server_action(server['id'], body)
        # We cannot monitor the migration from the API since it is deleted
        # when the instance is deleted so just wait for the failed instance
        # action event after the task rollback happens.
        self._wait_for_action_fail_completion(
            server, instance_actions.LIVE_MIGRATION,
            'conductor_live_migrate_instance')
        self._assert_no_allocations(server)

    def test_migrate_on_compute_fail(self):
        """Tests a scenario where during the _prep_resize on the dest host
        the instance is gone which triggers a failure and revert of the
        migration-based allocations created in conductor.
        """
        server, source_host, target_host = self._create_server()

        # Wrap _prep_resize so we can concurrently delete the server.
        original_prep_resize = compute_manager.ComputeManager._prep_resize

        def wrap_prep_resize(*args, **kwargs):
            self._delete_server(server)
            return original_prep_resize(*args, **kwargs)

        self.stub_out('nova.compute.manager.ComputeManager._prep_resize',
                      wrap_prep_resize)

        # Now start the cold migration which will fail in the dest compute.
        self.api.post_server_action(server['id'], {'migrate': None})
        # We cannot monitor the migration from the API since it is deleted
        # when the instance is deleted so just wait for the failed instance
        # action event after the allocation revert happens.
        self._wait_for_action_fail_completion(
            server, instance_actions.MIGRATE, 'compute_prep_resize')
        self._assert_no_allocations(server)

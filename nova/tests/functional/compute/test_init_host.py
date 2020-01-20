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
import time

from nova import context as nova_context
from nova import objects
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class ComputeManagerInitHostTestCase(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Tests various actions performed when the nova-compute service starts."""

    compute_driver = 'fake.MediumFakeDriver'

    def test_migrate_disk_and_power_off_crash_finish_revert_migration(self):
        """Tests the scenario that the compute service crashes while the
        driver's migrate_disk_and_power_off method is running (we could be
        slow transferring disks or something when it crashed) and on restart
        of the compute service the driver's finish_revert_migration method
        is called to cleanup the source host and reset the instance task_state.
        """
        # Start two compute service so we migrate across hosts.
        for x in range(2):
            self._start_compute('host%d' % x)
        # Create a server, it does not matter on which host it lands.
        server = self._build_server(networks='auto')
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Save the source hostname for assertions later.
        source_host = server['OS-EXT-SRV-ATTR:host']

        def fake_migrate_disk_and_power_off(*args, **kwargs):
            # Simulate the source compute service crashing by restarting it.
            self.restart_compute_service(self.computes[source_host])
            # We have to keep the method from returning before asserting the
            # _init_instance restart behavior otherwise resize_instance will
            # fail and set the instance to ERROR status, revert allocations,
            # etc which is not realistic if the service actually crashed while
            # migrate_disk_and_power_off was running.
            # The sleep value needs to be large to avoid this waking up and
            # interfering with other tests running on the same worker.
            time.sleep(1000000)

        source_driver = self.computes[source_host].manager.driver
        with mock.patch.object(source_driver, 'migrate_disk_and_power_off',
                               side_effect=fake_migrate_disk_and_power_off):
            # Initiate a cold migration from the source host.
            self.admin_api.post_server_action(server['id'], {'migrate': None})
            # Now wait for the task_state to be reset to None during
            # _init_instance.
            server = self._wait_for_server_parameter(server, {
                    'status': 'ACTIVE',
                    'OS-EXT-STS:task_state': None,
                    'OS-EXT-SRV-ATTR:host': source_host
                }
            )

        # Assert we went through the _init_instance processing we expect.
        log_out = self.stdlog.logger.output
        self.assertIn('Instance found in migrating state during startup. '
                      'Resetting task_state', log_out)
        # Assert that driver.finish_revert_migration did not raise an error.
        self.assertNotIn('Failed to revert crashed migration', log_out)

        # The migration status should be "error" rather than stuck as
        # "migrating".
        context = nova_context.get_admin_context()
        # FIXME(mriedem): This is bug 1836369 because we would normally expect
        # Migration.get_by_instance_and_status to raise
        # MigrationNotFoundByStatus since the status should be "error".
        objects.Migration.get_by_instance_and_status(
            context, server['id'], 'migrating')

        # Assert things related to the resize get cleaned up:
        # - things set on the instance during prep_resize like:
        #   - migration_context
        #   - new_flavor
        #   - stashed old_vm_state in system_metadata
        # - migration-based allocations from conductor/scheduler, i.e. that the
        #   allocations created by the scheduler for the instance and dest host
        #   are gone and the source host allocations are back on the instance
        #   rather than the migration record
        instance = objects.Instance.get_by_uuid(
            context, server['id'], expected_attrs=[
                'migration_context', 'flavor', 'system_metadata'
            ])
        # FIXME(mriedem): Leaving these fields set on the instance is
        # bug 1836369.
        self.assertIsNotNone(instance.migration_context)
        self.assertIsNotNone(instance.new_flavor)
        self.assertEqual('active', instance.system_metadata['old_vm_state'])

        dest_host = 'host0' if source_host == 'host1' else 'host1'
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_host)
        dest_allocations = self._get_allocations_by_provider_uuid(dest_rp_uuid)
        # FIXME(mriedem): This is bug 1836369 because we orphaned the
        # allocations created by the scheduler for the server on the dest host.
        self.assertIn(server['id'], dest_allocations)
        source_rp_uuid = self._get_provider_uuid_by_host(source_host)
        source_allocations = self._get_allocations_by_provider_uuid(
            source_rp_uuid)
        # FIXME(mriedem): This is bug 1836369 because the server is running on
        # the source host but is not tracking allocations against the source
        # host.
        self.assertNotIn(server['id'], source_allocations)


class TestComputeRestartInstanceStuckInBuild(
        integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TestComputeRestartInstanceStuckInBuild, self).setUp()
        self.compute1 = self._start_compute(host='host1')

    def test_restart_compute_while_instance_waiting_for_resource_claim(self):
        """Test for bug 1833581 where an instance is stuck in
        BUILD state forever due to compute service is restarted before the
        resource claim finished.
        """

        # To reproduce the problem we need to stop / kill the compute service
        # when an instance build request has already reached the service but
        # the instance_claim() has not finished. One way that this
        # happens in practice is when multiple builds are waiting for the
        # 'nova-compute-resource' semaphore. So one way to reproduce this in
        # the test would be to grab that semaphore, boot an instance, wait for
        # it to reach the compute then stop the compute.
        # Unfortunately when we release the semaphore after the simulated
        # compute restart the original instance_claim execution continues as
        # the stopped compute is not 100% stopped in the func test env. Also
        # we cannot really keep the semaphore forever as this named semaphore
        # is shared between the old and new compute service.
        # There is another way to trigger the issue. We can inject a sleep into
        # instance_claim() to stop it. This is less realistic but it works in
        # the test env.
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')

        def sleep_forever(*args, **kwargs):
            time.sleep(1000000)

        with mock.patch('nova.compute.resource_tracker.ResourceTracker.'
                        'instance_claim') as mock_instance_claim:
            mock_instance_claim.side_effect = sleep_forever

            server = self.api.post_server({'server': server_req})
            self._wait_for_state_change(server, 'BUILD')

            # the instance.create.start is the closest thing to the
            # instance_claim call we can wait for in the test
            fake_notifier.wait_for_versioned_notifications(
                'instance.create.start')

            with mock.patch('nova.compute.manager.LOG.debug') as mock_log:
                self.restart_compute_service(self.compute1)

        # We expect that the instance is pushed to ERROR state during the
        # compute restart.
        self._wait_for_state_change(server, 'ERROR')
        mock_log.assert_called_with(
            'Instance spawn was interrupted before instance_claim, setting '
            'instance to ERROR state',
            instance=mock.ANY)

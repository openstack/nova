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

"""Functional tests for graceful shutdown of the Nova compute, conductor,
and scheduler services.

These tests verify that in-progress operations complete when a service
receives a graceful shutdown (SIGTERM, triggered via service.stop()).

Scenarios:
  1. Live migration – source compute gracefully shut down mid-migration
  2. Live migration – dest compute gracefully shut down mid-migration
  3. Cold migration – source compute gracefully shut down mid-migration
  4. Cold migration – dest compute gracefully shut down mid-migration
  5. Instance build – compute gracefully shut down during spawn
  6. Revert resize – dest compute gracefully shut down during revert
  7. Conductor – gracefully shut down with no in-progress tasks
  8. Scheduler – gracefully shut down with no in-progress tasks

  <We can add more operations testing here if needed>
"""

import threading
import time

import fixtures

import nova.conf
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova import utils

CONF = nova.conf.CONF


class GracefulShutdownTestBase(integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.FakeLiveMigrateDriver'
    microversion = 'latest'
    CAST_AS_CALL = False

    # Set operation completion timeout and additional 2 sec for manager to
    # timeout the graceful_shutdown() so that test will not hang if anything
    # goes wrong.
    OPERATION_TIMEOUT = 60
    MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT = OPERATION_TIMEOUT + 2

    def setUp(self):
        # NOTE(gmaan): report_interval/service_down_time control how fast
        # the compute service update status to "down". graceful shutdown
        # tests heavily rely on the service start/stop so we need a high
        # service_down_time here. Every test starts service during setUp
        # and wait for service being up. But if service_down_time is less
        # then during test execution, service status can be seen as down.
        # Many tests runs in heavy parallel load and in threading mode,
        # there is chance that service status heartbeat lags to report it in
        # DB then, DB will report service as down during test execution time.
        # so that a merely-delayed heartbeat (many tests running in
        # heavy parallel load and in threading mode can delay report_state)
        # is not mistaken for a stopped service.
        # service_down_time should be large enough so that wrong status update
        # can be avoided in mid of tests. Considering 30 sec enough for
        # service heartbeat thread to get its turn and update the service
        # status.
        self.flags(
            report_interval=1,
            service_down_time=30)
        super().setUp()
        self.flags(manager_shutdown_timeout=30)
        # NOTE(gmaan): Here _start_compute() create a fresh service and for
        # freshly created service, status is decided based on the 'created_at'
        # instead of 'last_seen_up' which means service is starting as 'up'
        # until first heartbeat arrives or service_down_time is elapsed.
        self._start_compute('src')
        self._start_compute('dest')

    def _setup_graceful_shutdown_mock(self, compute, operation_complete_event):
        # Manager graceful_shutdown() wait for operation_complete_event to
        # be set or MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT.
        shutdown_waiting = threading.Event()

        def coordinated_graceful_shutdown(timeout):
            shutdown_waiting.set()
            operation_complete_event.wait(
                timeout=self.MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT)
            compute.manager.cleanup_host()

        self.useFixture(fixtures.MockPatchObject(
            compute.manager, 'graceful_shutdown',
            side_effect=coordinated_graceful_shutdown))
        return shutdown_waiting

    def _stop_compute_gracefully(self, compute, timeout=30):
        t = threading.Thread(target=compute.stop)
        t.start()
        self.assertTrue(
            compute.manager._shutdown_in_progress.wait(timeout=timeout),
            'manager shutdown is not started yet')
        return t

    def _join_stop_thread(self, stop_thread, timeout=60):
        stop_thread.join(timeout=timeout)
        self.assertFalse(
            stop_thread.is_alive(),
            'Graceful shutdown thread did not complete within %ds' % timeout)

    def wait_for_service_stop(self, stop_thread, host,
                              binary='nova-compute', timeout=60):
        """Join stop_thread then poll until the service is down in the DB."""
        self._join_stop_thread(stop_thread, timeout=timeout)
        # self._wait_for_service_parameter polls the service status every
        # .5 sec, so wait for CONF.service_down_time + 10 sec worth of
        # retries whenever we poll for a service state ('up' or 'down')
        # change in this test class.
        max_retries = int(CONF.service_down_time / 0.5 + 10)
        self._wait_for_service_parameter(
            host, binary, {'state': 'down'}, max_retries=max_retries)

    def _restart_compute(self, hostname):
        self.computes.pop(hostname, None)
        self._start_compute(hostname)
        # NOTE(gmaan): In this case, existing service is started again
        # (restart service). When service is stopped, DB entry of that
        # service is not deleted but service status is 'down'. Once we
        # start it again then it remains 'down' until first heartbeat
        # arrives because this time it does not consider 'created_at'
        # instead it consider 'last_seen_up' to check the elapsed time.
        # That is why we need to explicitly wait for service to be 'up'.
        self._wait_for_service_parameter(
            hostname, 'nova-compute', {'state': 'up'}, max_retries=20)

    def _complete_live_migration(self, context, instance, dest, post_method,
                                  recover_method, block_migration=False,
                                  migrate_data=None):
        post_method(context, instance, dest, block_migration, migrate_data)


class TestComputeGracefulShutdown(GracefulShutdownTestBase):
    """Functional graceful-shutdown tests for the compute manager."""

    def test_live_migration_source_compute_graceful_shutdown(self):
        """Live migration completes when the source compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['src'].manager.driver, 'live_migration',
            side_effect=self._complete_live_migration,
            timeout=self.OPERATION_TIMEOUT))
        started, proceed = intercept.started, intercept.proceed

        # Kick off live migration asynchronously.
        self.api.post_server_action(
            server['id'],
            {'os-migrateLive': {'host': 'dest', 'block_migration': 'auto'}})

        # Wait until migration has entered the driver on the source.
        self.assertTrue(
            started.wait(timeout=30),
            'Timed out waiting for live migration to start on source driver')

        # Trigger graceful shutdown of source while migration is in-flight.
        stop_thread = self._stop_compute_gracefully(self.computes['src'])

        # Confirm the manager graceful_shutdown is called and waiting for the
        # operation to complete.
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for manager graceful_shutdown to be called')

        # Migration must not have completed before we unblock the driver.
        self.assertEqual(
            'MIGRATING', self.api.get_server(server['id'])['status'])

        # Confirm that live migration is waiting before signal it to proceed.
        self.assertGreater(proceed.waiter_count(), 0,
                           'live_migration not waiting and might be completed')
        # Allow the migration to proceed.
        proceed.set()

        # Verify migration completed successfully.
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['completed'])

        # Confirm graceful shutdown is still waiting.
        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for operation')
        # Mark operation complete and signal graceful_shutdown() to proceed.
        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'src')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted.
        self._restart_compute('src')
        self._delete_server(server)

    def test_live_migration_dest_compute_graceful_shutdown(self):
        """Live migration completes when the dest compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['dest'], operation_complete_event)

        # Pause post_live_migration_at_destination on dest so we can confirm
        # the migration is finalising there before triggering graceful
        # shutdown.
        plm_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['dest'].manager.driver,
            'post_live_migration_at_destination',
            timeout=self.OPERATION_TIMEOUT))
        plm_started, plm_proceed = plm_intercept.started, plm_intercept.proceed

        # Kick off live migration asynchronously.
        self.api.post_server_action(
            server['id'],
            {'os-migrateLive': {'host': 'dest', 'block_migration': 'auto'}})

        # Wait until post-migration work has started on dest.
        self.assertTrue(
            plm_started.wait(timeout=30),
            'Timed out waiting for post_live_migration_at_destination on dest')

        # Trigger graceful shutdown of dest while it is finishing the
        # migration.
        stop_thread = self._stop_compute_gracefully(self.computes['dest'])

        # Confirm the manager graceful_shutdown is called and waiting for the
        # operation to complete.
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for graceful_shutdown is called')
        self.assertEqual(
            'MIGRATING', self.api.get_server(server['id'])['status'])

        # Confirm the driver is waiting on plm_proceed.
        self.assertGreater(plm_proceed.waiter_count(), 0,
                           'post_live_migration_at_destination not blocking')
        # Allow post-migration work on dest to complete.
        plm_proceed.set()

        # The migration should complete and the instance should land on dest.
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['completed'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for operation')
        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'dest')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted
        self._restart_compute('dest')
        self._delete_server(server)

    def test_live_migration_dest_shutdown_before_post_live_migration(self):
        server = self._create_server(host='src', networks='none')

        # When the driver's live_migration() is invoked on the source,
        # pre_live_migration has already returned successfully on dest.
        intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['src'].manager.driver, 'live_migration',
            side_effect=self._complete_live_migration,
            timeout=self.OPERATION_TIMEOUT))
        started, proceed = intercept.started, intercept.proceed

        self.api.post_server_action(
            server['id'],
            {'os-migrateLive': {'host': 'dest', 'block_migration': 'auto'}})

        self.assertTrue(
            started.wait(timeout=30),
            'Timed out waiting for live migration to start on source driver')

        # pre_live_migration has completed on dest; dest must still be
        # tracking this live migration as in-progress.
        dest_manager = self.computes['dest'].manager
        self.assertIn(
            server['id'], dest_manager._pending_dest_live_migrations,
            'dest is not tracking the migration as in-progress after '
            'pre_live_migration returned')

        stop_thread = self._stop_compute_gracefully(self.computes['dest'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for the in-progress '
            'live migration to reach post_live_migration_at_destination')

        proceed.set()

        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['completed'])
        self.assertNotIn(
            server['id'], dest_manager._pending_dest_live_migrations)

        self.wait_for_service_stop(stop_thread, 'dest')

        self._restart_compute('dest')
        self._delete_server(server)

    def test_cold_migration_source_compute_graceful_shutdown(self):
        """Cold migration completes when the source compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        # Pause the disk-and-power-off phase on source.
        mdpo_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['src'].manager.driver,
            'migrate_disk_and_power_off',
            timeout=self.OPERATION_TIMEOUT))
        mdpo_started, mdpo_proceed = (
            mdpo_intercept.started, mdpo_intercept.proceed)

        # Start cold migration asynchronously.
        self.api.post_server_action(server['id'], {'migrate': None})

        self.assertTrue(
            mdpo_started.wait(timeout=30),
            'Timed out waiting for migrate_disk_and_power_off on source')

        # Trigger graceful shutdown of source compute.
        stop_thread = self._stop_compute_gracefully(self.computes['src'])

        # Confirm the manager graceful_shutdown is called and waiting for the
        # operation to complete.
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for graceful_shutdown is called')
        self.assertEqual(
            'RESIZE', self.api.get_server(server['id'])['status'])

        # Confirm the driver is waiting on mdpo_proceed.
        self.assertGreater(mdpo_proceed.waiter_count(), 0,
                           'migrate_disk_and_power_off not blocking')
        # Allow the disk-and-power-off phase to complete.
        mdpo_proceed.set()

        # Cold migration finishes in VERIFY_RESIZE awaiting confirm/revert.
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['finished'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for operation')
        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'src')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted after confirm rezie.
        self._restart_compute('src')
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self._delete_server(server)

    def test_cold_migration_dest_compute_graceful_shutdown(self):
        """Cold migration completes when the dest compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['dest'], operation_complete_event)

        # Pause finish_migration on dest (invoked inside finish_resize, which
        # is dispatched to dest's alt RPC server by the source compute).
        fm_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['dest'].manager.driver, 'finish_migration',
            timeout=self.OPERATION_TIMEOUT))
        fm_started, fm_proceed = fm_intercept.started, fm_intercept.proceed

        # Start cold migration asynchronously.
        self.api.post_server_action(server['id'], {'migrate': None})

        self.assertTrue(
            fm_started.wait(timeout=30),
            'Timed out waiting for finish_migration on dest')

        # Trigger graceful shutdown of dest compute.
        stop_thread = self._stop_compute_gracefully(self.computes['dest'])

        # Confirm the manager graceful_shutdown is called and waiting for the
        # operation to complete.
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for graceful_shutdown is called')
        self.assertEqual(
            'RESIZE', self.api.get_server(server['id'])['status'])

        # Confirm the driver is waiting on fm_proceed.
        self.assertGreater(fm_proceed.waiter_count(), 0,
                           'finish_migration not blocking')
        # Allow finish_migration to complete.
        fm_proceed.set()

        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['finished'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for operation')
        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'dest')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted after confirm resize.
        self._restart_compute('dest')
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self._delete_server(server)

    def test_cold_migration_dest_shutdown_before_resize_instance_completes(
            self):
        server = self._create_server(host='src', networks='none')

        mdpo_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['src'].manager.driver,
            'migrate_disk_and_power_off',
            timeout=self.OPERATION_TIMEOUT))
        mdpo_started, mdpo_proceed = (
            mdpo_intercept.started, mdpo_intercept.proceed)

        self.api.post_server_action(server['id'], {'migrate': None})

        self.assertTrue(
            mdpo_started.wait(timeout=30),
            'Timed out waiting for migrate_disk_and_power_off on source')

        # prep_resize has completed on dest; dest must still be tracking
        # this resize as in-progress.
        dest_manager = self.computes['dest'].manager
        self.assertIn(
            server['id'], dest_manager._pending_dest_resizes,
            'dest is not tracking the resize as in-progress after prep_resize '
            'returned')

        stop_thread = self._stop_compute_gracefully(self.computes['dest'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for the in-progress '
            'resize to reach finish_resize')

        mdpo_proceed.set()

        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['finished'])
        self.assertNotIn(server['id'], dest_manager._pending_dest_resizes)

        self.wait_for_service_stop(stop_thread, 'dest')

        self._restart_compute('dest')
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self._delete_server(server)

    def test_instance_build_graceful_shutdown(self):
        """Instance build completes when the compute is stopped."""
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        # Pause spawn on src so we can confirm the build is in-flight before
        # triggering graceful shutdown.
        spawn_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            self.computes['src'].manager.driver, 'spawn',
            timeout=self.OPERATION_TIMEOUT))
        spawn_started, spawn_proceed = (
            spawn_intercept.started, spawn_intercept.proceed)

        # Post the server create; it returns immediately (CAST_AS_CALL=False).
        server_body = self._build_server(networks='none', host='src')
        server = self.api.post_server({'server': server_body})

        self.assertTrue(
            spawn_started.wait(timeout=30),
            'Timed out waiting for spawn to start on src')

        # Trigger graceful shutdown while the build is in progress.
        stop_thread = self._stop_compute_gracefully(self.computes['src'])

        # Confirm the manager graceful_shutdown is called and waiting for the
        # operation to complete.
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for graceful_shutdown is called')
        self.assertEqual(
            'BUILD', self.api.get_server(server['id'])['status'])

        # Confirm the driver is waiting on spawn_proceed.
        self.assertGreater(spawn_proceed.waiter_count(), 0,
                           'spawn not blocking')
        # Allow spawn to complete.
        spawn_proceed.set()

        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])

        self.assertTrue(
            stop_thread.is_alive(),
            'graceful shutdown should still be waiting for operation')
        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'src')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted
        self._restart_compute('src')
        self._delete_server(server)

    def test_revert_resize_dest_compute_graceful_shutdown(self):
        """Revert resize completes when the dest compute is stopped."""
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['dest'], operation_complete_event)

        # Cold-migrate the server from src to dest first.
        server = self._create_server(host='src', networks='none')
        self.api.post_server_action(server['id'], {'migrate': None})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('dest', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['finished'])

        # Pause destroy on dest.  revert_resize() calls destroy() to remove
        # the migrated copy before issuing finish_revert_resize to source.
        destroy_intercept = self.useFixture(
            nova_fixtures.InterceptMethodFixture(
                self.computes['dest'].manager.driver, 'destroy',
                timeout=self.OPERATION_TIMEOUT))
        destroy_started, destroy_proceed = (
            destroy_intercept.started, destroy_intercept.proceed)

        # Start the revert asynchronously.
        self.api.post_server_action(server['id'], {'revertResize': None})

        self.assertTrue(
            destroy_started.wait(timeout=30),
            'Timed out waiting for destroy during revert_resize on dest')

        # Trigger graceful shutdown of dest compute.
        stop_thread = self._stop_compute_gracefully(self.computes['dest'])

        # destroy is still blocked, so revert_resize cannot have completed.
        self.assertEqual(
            'REVERT_RESIZE', self.api.get_server(server['id'])['status'])

        # Confirm the driver is waiting on destroy_proceed.
        self.assertGreater(destroy_proceed.waiter_count(), 0,
                           'destroy not blocking')
        # revert_resize is dispatched on the main 'compute' rpcserver topic,
        # so service.stop() blocks in rpcserver.wait() until revert_resize
        # completes.  Unblock destroy so revert_resize can finish and the
        # stop thread can proceed to call graceful_shutdown().
        destroy_proceed.set()

        # graceful_shutdown() is called after rpcserver.wait() returns
        # (i.e. after revert_resize completes on dest).
        self.assertTrue(
            shutdown_waiting.wait(timeout=30),
            'Timed out waiting for graceful_shutdown is called')

        # After the revert, the instance returns to ACTIVE on source.
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('src', server['OS-EXT-SRV-ATTR:host'])
        self._wait_for_migration_status(server, ['reverted'])

        operation_complete_event.set()
        self.wait_for_service_stop(stop_thread, 'dest')

        # compute service is restarted to check if after shutdown, service
        # comes up normally and test server is deleted
        self._restart_compute('dest')
        self._delete_server(server)

    def test_build_instance_track_wait_during_shutdown(self):
        compute = self.computes['src']
        self.flags(manager_shutdown_timeout=30)
        cleanup_intercept = self.useFixture(
            nova_fixtures.InterceptMethodFixture(
                compute.manager, 'cleanup_host',
                timeout=self.OPERATION_TIMEOUT))
        cleanup_called, cleanup_proceed = (
            cleanup_intercept.started, cleanup_intercept.proceed)
        cleanup_proceed.set()

        spawn_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'spawn', timeout=self.OPERATION_TIMEOUT))
        spawn_started, spawn_proceed = (
            spawn_intercept.started, spawn_intercept.proceed)

        server_body = self._build_server(networks='none', host='src')
        server = self.api.post_server({'server': server_body})

        self.assertTrue(
            spawn_started.wait(timeout=30),
            'Timed out waiting for spawn to start on src')

        # Check if build instance task is tracked
        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(1, len(tracked))
        self.assertEqual('build_instance', tracked[0]['name'])

        stop_thread = self._stop_compute_gracefully(compute)

        # cleanup_host() must not run until the tracked build instance
        # finishes.
        self.assertFalse(
            cleanup_called.is_set(),
            'cleanup_host ran before the tracked build instance task finished')
        self.assertTrue(stop_thread.is_alive())
        self.assertGreater(spawn_proceed.waiter_count(), 0,
                           'spawn not blocking')

        # Allow the build instance to finish.
        spawn_proceed.set()

        server = self._wait_for_state_change(server, 'ACTIVE')
        self.wait_for_service_stop(stop_thread, 'src')

        self.assertTrue(cleanup_called.is_set())
        # Check tracked task is removed from tracking dict.
        self.assertEqual({}, compute.manager._in_progress_tasks)

        self._restart_compute('src')
        self._delete_server(server)

    def test_snapshot_instance_track_and_wait_during_shutdown(self):
        compute = self.computes['src']
        self.flags(manager_shutdown_timeout=30)
        cleanup_intercept = self.useFixture(
            nova_fixtures.InterceptMethodFixture(
                compute.manager, 'cleanup_host',
                timeout=self.OPERATION_TIMEOUT))
        cleanup_called, cleanup_proceed = (
            cleanup_intercept.started, cleanup_intercept.proceed)
        cleanup_proceed.set()

        server = self._create_server(host='src', networks='none')

        snap_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'snapshot',
            timeout=self.OPERATION_TIMEOUT))
        snap_started, snap_proceed = (
            snap_intercept.started, snap_intercept.proceed)

        self._snapshot_server(server, 'test-snapshot')

        self.assertTrue(
            snap_started.wait(timeout=30),
            'Timed out waiting for snapshot to start on src')

        # Check if snapshot instance task is tracked
        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(1, len(tracked))
        self.assertEqual('snapshot_instance', tracked[0]['name'])

        stop_thread = self._stop_compute_gracefully(compute)

        self.assertFalse(
            cleanup_called.is_set(),
            'cleanup_host ran before the tracked snapshot finished')
        self.assertTrue(stop_thread.is_alive())
        self.assertGreater(snap_proceed.waiter_count(), 0,
                           'snapshot not blocking')

        snap_proceed.set()

        self._wait_for_state_change(server, 'ACTIVE')
        self.wait_for_service_stop(stop_thread, 'src')

        self.assertTrue(cleanup_called.is_set())
        # Check tracked task is removed from tracking dict.
        self.assertEqual({}, compute.manager._in_progress_tasks)

        self._restart_compute('src')
        self._delete_server(server)

    def test_multiple_build_instance_tracked_and_shutdown_wait_for_all(self):
        compute = self.computes['src']
        self.flags(manager_shutdown_timeout=30)
        cleanup_intercept = self.useFixture(
            nova_fixtures.InterceptMethodFixture(
                compute.manager, 'cleanup_host',
                timeout=self.OPERATION_TIMEOUT))
        cleanup_called, cleanup_proceed = (
            cleanup_intercept.started, cleanup_intercept.proceed)
        cleanup_proceed.set()

        lock = threading.Lock()
        started_events = {}
        proceed_events = {}
        original_spawn = compute.manager.driver.spawn

        def _blocking_spawn(context, instance, *args, **kwargs):
            with lock:
                started = started_events[instance.uuid]
                proceed = proceed_events[instance.uuid]
            started.set()
            proceed.wait(timeout=self.OPERATION_TIMEOUT)
            return original_spawn(context, instance, *args, **kwargs)

        self.useFixture(fixtures.MockPatchObject(
            compute.manager.driver, 'spawn', side_effect=_blocking_spawn))

        server_body = self._build_server(networks='none', host='src')
        servers = []
        for _ in range(2):
            server = self.api.post_server({'server': server_body})
            with lock:
                started_events[server['id']] = threading.Event()
                proceed_events[server['id']] = nova_fixtures.WaitableEvent()
            servers.append(server)

        for server in servers:
            self.assertTrue(
                started_events[server['id']].wait(timeout=30),
                'Timed out waiting for spawn to start for %s' % server['id'])

        # Both build instance tasks should be tracked as in-progress tasks.
        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(2, len(tracked))
        self.assertEqual({'build_instance'}, {t['name'] for t in tracked})
        self.assertEqual(
            {s['id'] for s in servers},
            {t['instance_uuid'] for t in tracked})

        stop_thread = self._stop_compute_gracefully(compute)

        # Event first build instance is finished, shutdown should keep waiting
        # for the second build instance in progress task.
        proceed_events[servers[0]['id']].set()
        self._wait_for_state_change(servers[0], 'ACTIVE')

        self.assertFalse(
            cleanup_called.is_set(),
            'cleanup_host ran before all tracked tasks finished')
        self.assertTrue(
            stop_thread.is_alive(),
            'shutdown returned before all tracked tasks finished')
        self.assertEqual(1, len(compute.manager._in_progress_tasks))
        remaining = list(compute.manager._in_progress_tasks.values())[0]
        self.assertEqual(servers[1]['id'], remaining['instance_uuid'])

        self.assertGreater(
            proceed_events[servers[1]['id']].waiter_count(), 0,
            'second spawn not blocking')
        proceed_events[servers[1]['id']].set()

        self._wait_for_state_change(servers[1], 'ACTIVE')
        self.wait_for_service_stop(stop_thread, 'src')

        self.assertTrue(cleanup_called.is_set())
        self.assertEqual({}, compute.manager._in_progress_tasks)

        self._restart_compute('src')
        for server in servers:
            self._delete_server(server)

    def test_different_concurrent_operations_and_shutdown_wait_for_all(self):
        compute = self.computes['src']
        self.flags(manager_shutdown_timeout=30)
        cleanup_intercept = self.useFixture(
            nova_fixtures.InterceptMethodFixture(
                compute.manager, 'cleanup_host',
                timeout=self.OPERATION_TIMEOUT))
        cleanup_called, cleanup_proceed = (
            cleanup_intercept.started, cleanup_intercept.proceed)
        cleanup_proceed.set()

        snap_server = self._create_server(host='src', networks='none')
        pause_server = self._create_server(host='src', networks='none')
        lm_server = self._create_server(host='src', networks='none')

        snap_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'snapshot',
            timeout=self.OPERATION_TIMEOUT))
        snap_started, snap_proceed = (
            snap_intercept.started, snap_intercept.proceed)
        pause_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'pause', timeout=self.OPERATION_TIMEOUT))
        pause_started, pause_proceed = (
            pause_intercept.started, pause_intercept.proceed)

        lm_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'live_migration',
            side_effect=self._complete_live_migration,
            timeout=self.OPERATION_TIMEOUT))
        lm_started, lm_proceed = lm_intercept.started, lm_intercept.proceed

        self._snapshot_server(snap_server, 'test-snapshot')
        self.api.post_server_action(pause_server['id'], {'pause': None})
        self.api.post_server_action(
            lm_server['id'],
            {'os-migrateLive': {'host': 'dest', 'block_migration': 'auto'}})

        self.assertTrue(
            snap_started.wait(timeout=30),
            'Timed out waiting for snapshot to start on src')
        self.assertTrue(
            pause_started.wait(timeout=30),
            'Timed out waiting for pause to start on src')
        self.assertTrue(
            lm_started.wait(timeout=30),
            'Timed out waiting for live migration to start on src')

        # All three tasks should be tracked concurrently.
        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(3, len(tracked))
        self.assertEqual(
            {'snapshot_instance', 'pause_instance', 'live_migration'},
            {t['name'] for t in tracked})

        stop_thread = self._stop_compute_gracefully(compute)

        self.assertFalse(
            cleanup_called.is_set(),
            'cleanup_host ran before all tracked tasks finished')

        snap_proceed.set()
        self._wait_for_state_change(snap_server, 'ACTIVE')
        self.assertTrue(stop_thread.is_alive())
        self.assertFalse(cleanup_called.is_set())
        self.assertEqual(2, len(compute.manager._in_progress_tasks))

        pause_proceed.set()
        self._wait_for_state_change(pause_server, 'PAUSED')
        self.assertTrue(stop_thread.is_alive())
        self.assertFalse(cleanup_called.is_set())
        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(1, len(tracked))
        self.assertEqual('live_migration', tracked[0]['name'])

        self.assertGreater(lm_proceed.waiter_count(), 0,
                           'live migration not blocking')
        lm_proceed.set()

        lm_server = self._wait_for_state_change(lm_server, 'ACTIVE')
        self.assertEqual('dest', lm_server['OS-EXT-SRV-ATTR:host'])
        self.wait_for_service_stop(stop_thread, 'src')

        self.assertTrue(cleanup_called.is_set())
        self.assertEqual({}, compute.manager._in_progress_tasks)

        self._restart_compute('src')
        self._delete_server(snap_server)
        self._delete_server(pause_server)
        self._delete_server(lm_server)

    def test_rpc_call_are_tracked(self):
        compute = self.computes['src']
        server = self._create_server(host='src', networks='none')

        pause_intercept = self.useFixture(nova_fixtures.InterceptMethodFixture(
            compute.manager.driver, 'pause', timeout=self.OPERATION_TIMEOUT))
        pause_started, pause_proceed = (
            pause_intercept.started, pause_intercept.proceed)

        self.api.post_server_action(server['id'], {'pause': None})

        self.assertTrue(
            pause_started.wait(timeout=30),
            'Timed out waiting for pause to start on src')

        tracked = list(compute.manager._in_progress_tasks.values())
        self.assertEqual(1, len(tracked))
        self.assertEqual('pause_instance', tracked[0]['name'])
        self.assertEqual(server['id'], tracked[0]['instance_uuid'])

        pause_proceed.set()
        self._wait_for_state_change(server, 'PAUSED')

        self.assertEqual({}, compute.manager._in_progress_tasks)
        self._delete_server(server)

    def test_periodic_tasks_skipped_once_shutdown_starts(self):
        compute = self.computes['src']
        manager = compute.manager
        manager._shutdown_in_progress.set()

        mock_poll = self.useFixture(fixtures.MockPatchObject(
            manager, '_poll_rebooting_instances')).mock
        manager.periodic_tasks(context=None)

        mock_poll.assert_not_called()


class TestConductorGracefulShutdown(test.TestCase):
    def setUp(self):
        super().setUp()
        self.flags(manager_shutdown_timeout=5)
        self.conductor_service = self.start_service('conductor')

    def test_graceful_shutdown_completes_instantly_when_no_tasks(self):
        manager = self.conductor_service.manager
        self.assertFalse(manager._shutdown_in_progress.is_set())

        utils.get_cache_images_executor()
        self.addCleanup(utils.destroy_cache_images_executor)

        start = time.monotonic()
        self.conductor_service.stop()
        elapsed = time.monotonic() - start

        self.assertTrue(manager._shutdown_in_progress.is_set())
        # As there is no tasks in-progress, so _wait_for_in_progress_tasks()
        # should return instantly rather than waiting out the configured
        # 5 second timeout.
        self.assertLess(elapsed, 5)


class TestSchedulerGracefulShutdown(test.TestCase):

    def setUp(self):
        super().setUp()
        self.flags(manager_shutdown_timeout=5)
        self.scheduler_service = self.start_service('scheduler')

    def test_graceful_shutdown_completes_instantly_when_no_tasks(self):
        manager = self.scheduler_service.manager
        self.assertFalse(manager._shutdown_in_progress.is_set())

        start = time.monotonic()
        self.scheduler_service.stop()
        elapsed = time.monotonic() - start

        self.assertTrue(manager._shutdown_in_progress.is_set())
        # As there is no tasks in-progress, so _wait_for_in_progress_tasks()
        # should return instantly rather than waiting out the configured
        # 5 second timeout.
        self.assertLess(elapsed, 5)

    def test_periodic_tasks_skipped_once_shutdown_starts(self):
        manager = self.scheduler_service.manager
        manager._shutdown_in_progress.set()

        mock_discover = self.useFixture(fixtures.MockPatchObject(
            manager, '_discover_hosts_in_cells')).mock
        manager.periodic_tasks(context=None)

        mock_discover.assert_not_called()

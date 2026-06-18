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

"""Functional tests for graceful shutdown of the Nova compute service.

These tests verify that in-progress operations complete when the compute
service receives a graceful shutdown (SIGTERM, triggered via service.stop()).

Scenarios:
  1. Live migration – source compute gracefully shut down mid-migration
  2. Live migration – dest compute gracefully shut down mid-migration
  3. Cold migration – source compute gracefully shut down mid-migration
  4. Cold migration – dest compute gracefully shut down mid-migration
  5. Instance build – compute gracefully shut down during spawn
  6. Revert resize – dest compute gracefully shut down during revert

  <We can add more operations testing here if needed>
"""

import threading

import fixtures

from nova.tests.functional import integrated_helpers


class _WaitableEvent(threading.Event):
    """threading.Event subclass that tracks the number of active waiters."""

    def __init__(self):
        super().__init__()
        self._waiters_lock = threading.Lock()
        self._waiters = 0

    def wait(self, timeout=None):
        with self._waiters_lock:
            self._waiters += 1
        try:
            return super().wait(timeout=timeout)
        finally:
            with self._waiters_lock:
                self._waiters -= 1

    def waiter_count(self):
        with self._waiters_lock:
            return self._waiters


class TestGracefulShutdown(integrated_helpers.ProviderUsageBaseTestCase):
    """Functional graceful-shutdown tests using the fake driver."""

    compute_driver = 'fake.FakeLiveMigrateDriver'
    microversion = 'latest'
    CAST_AS_CALL = False

    # Set operation completion timeout and additional 2 sec for manager to
    # timeout the graceful_shutdown() so that test will not hang if anything
    # goes wrong.
    OPERATION_TIMEOUT = 60
    MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT = OPERATION_TIMEOUT + 2

    def setUp(self):
        self.flags(report_interval=1, service_down_time=6)
        super().setUp()
        self.flags(manager_shutdown_timeout=0)
        self._start_compute('src')
        self._start_compute('dest')

    def _setup_graceful_shutdown_mock(self, compute, operation_complete_event):
        # Manager graceful_shutdown() wait for operation_complete_event to
        # be set or MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT.
        shutdown_waiting = threading.Event()

        def coordinated_graceful_shutdown():
            shutdown_waiting.set()
            operation_complete_event.wait(
                timeout=self.MANAGER_GRACEFUL_SHUTDOWN_TIMEOUT)
            compute.manager.cleanup_host()

        self.useFixture(fixtures.MockPatchObject(
            compute.manager, 'graceful_shutdown',
            side_effect=coordinated_graceful_shutdown))
        return shutdown_waiting

    def _block_driver_method(self, compute, method_name):
        """Pause compute's driver method until explicitly released.

        Returns ``(started_event, proceed_event)``.  The caller waits on
        ``started_event`` to confirm the method has been entered, then asserts
        ``proceed_event.waiter_count() > 0`` and sets it to let it finish.
        ``proceed_event`` is a ``_WaitableEvent`` so callers can verify the
        driver is genuinely blocking before releasing it.
        """
        started = threading.Event()
        proceed = _WaitableEvent()
        original = getattr(compute.manager.driver, method_name)

        def _blocking(*args, **kwargs):
            started.set()
            proceed.wait(timeout=self.OPERATION_TIMEOUT)
            return original(*args, **kwargs)

        self.useFixture(fixtures.MockPatchObject(
            compute.manager.driver, method_name, side_effect=_blocking))
        return started, proceed

    def _stop_compute_gracefully(self, compute):
        t = threading.Thread(target=compute.stop)
        t.start()
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
        self._wait_for_service_parameter(
            host, binary, {'state': 'down'}, max_retries=20)

    def _restart_compute(self, hostname):
        self.computes.pop(hostname, None)
        self._start_compute(hostname)
        self._wait_for_service_parameter(
            hostname, 'nova-compute', {'state': 'up'}, max_retries=20)

    def test_live_migration_source_compute_graceful_shutdown(self):
        """Live migration completes when the source compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        started = threading.Event()
        proceed = _WaitableEvent()

        def _live_migration_side_effect(
                context, instance, dest, post_method, recover_method,
                block_migration=False, migrate_data=None):
            started.set()
            proceed.wait(timeout=self.OPERATION_TIMEOUT)
            post_method(context, instance, dest, block_migration, migrate_data)

        self.useFixture(fixtures.MockPatchObject(
            self.computes['src'].manager.driver, 'live_migration',
            side_effect=_live_migration_side_effect))

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
        plm_started, plm_proceed = self._block_driver_method(
            self.computes['dest'], 'post_live_migration_at_destination')

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

    def test_cold_migration_source_compute_graceful_shutdown(self):
        """Cold migration completes when the source compute is shut down."""
        server = self._create_server(host='src', networks='none')
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        # Pause the disk-and-power-off phase on source.
        mdpo_started, mdpo_proceed = self._block_driver_method(
            self.computes['src'], 'migrate_disk_and_power_off')

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
        fm_started, fm_proceed = self._block_driver_method(
            self.computes['dest'], 'finish_migration')

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

    def test_instance_build_graceful_shutdown(self):
        """Instance build completes when the compute is stopped."""
        operation_complete_event = threading.Event()
        shutdown_waiting = self._setup_graceful_shutdown_mock(
            self.computes['src'], operation_complete_event)

        # Pause spawn on src so we can confirm the build is in-flight before
        # triggering graceful shutdown.
        spawn_started, spawn_proceed = self._block_driver_method(
            self.computes['src'], 'spawn')

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
        destroy_started, destroy_proceed = self._block_driver_method(
            self.computes['dest'], 'destroy')

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

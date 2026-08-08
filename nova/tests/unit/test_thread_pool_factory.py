#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import threading
import time
from unittest import mock

import fixtures
import futurist
from oslo_context import context as common_context
from oslo_context import fixture as context_fixture

from nova import context
from nova import test
from nova import thread_pool_factory
from nova import utils


class SpawnTestCase(test.NoDBTestCase):
    def setUp(self):
        super(SpawnTestCase, self).setUp()
        self.useFixture(context_fixture.ClearRequestContext())

    def test_spawn_no_context(self):
        self.assertIsNone(common_context.get_current())

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual('test', args[0])

        def fake(arg):
            pass
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        with mock.patch.object(executor, "submit", _fake_spawn):
            thread_pool_factory.spawn(fake, 'test')
        self.assertIsNone(common_context.get_current())

    def test_spawn_context(self):
        self.assertIsNone(common_context.get_current())
        ctxt = context.RequestContext('user', 'project')

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual(ctxt, args[0])
            self.assertEqual('test', kwargs['kwarg1'])

        def fake(context, kwarg1=None):
            pass

        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        with mock.patch.object(executor, "submit", _fake_spawn):
            thread_pool_factory.spawn(fake, ctxt, kwarg1='test')
        self.assertEqual(ctxt, common_context.get_current())

    def test_spawn_context_different_from_passed(self):
        self.assertIsNone(common_context.get_current())
        ctxt = context.RequestContext('user', 'project')
        ctxt_passed = context.RequestContext('user', 'project',
                overwrite=False)
        self.assertEqual(ctxt, common_context.get_current())

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual(ctxt_passed, args[0])
            self.assertEqual('test', kwargs['kwarg1'])

        def fake(context, kwarg1=None):
            pass

        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        with mock.patch.object(executor, "submit", _fake_spawn):
            thread_pool_factory.spawn(fake, ctxt_passed, kwarg1='test')
        self.assertEqual(ctxt, common_context.get_current())


class ScatterGatherExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.SCATTER_GATHER)
        # NOTE(gibi): The executor is name both in normal run and in the test
        # env. During testing we use a test-case-specific name, outside
        # of test we use process name specific name instead. The test case
        # specific name is added to help troubleshooting leaked executors
        # between test case.
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.ScatterGatherExecutor.*"
            "test_executor_is_named.cell_worker")

    def test_executor_type_eventlet(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")

        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.SCATTER_GATHER)

        self.assertEqual('GreenThreadPoolExecutor', type(executor).__name__)

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    def test_executor_type_and_size_threading(self):
        self.flags(cell_worker_thread_pool_size=13)
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.SCATTER_GATHER)

        self.assertEqual('ThreadPoolExecutor', type(executor).__name__)
        self.assertEqual(13, executor._max_workers)


class DefaultExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        # NOTE(gibi): The executor is name both in normal run and in the test
        # env. During testing we use a test-case-specific name, outside
        # of test we use process name specific name instead. The test case
        # specific name is added to help troubleshooting leaked executors
        # between test case.
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.DefaultExecutor.*"
            "test_executor_is_named.default")

    def test_executor_type_and_size_eventlet(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")

        self.flags(default_green_pool_size=113)
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        self.assertEqual('GreenThreadPoolExecutor', type(executor).__name__)
        self.assertEqual(113, executor._max_workers)

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    def test_executor_type_and_size_threading(self):
        self.flags(default_thread_pool_size=13)
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        self.assertEqual('ThreadPoolExecutor', type(executor).__name__)
        self.assertEqual(13, executor._max_workers)


class LongTaskExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.LONG_TASK)
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.LongTaskExecutor.*"
            "test_executor_is_named.long_task")

    def test_pool_size_eventlet_sums_builds_and_snapshots(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")

        self.flags(max_concurrent_builds=10)
        self.flags(max_concurrent_snapshots=4)

        with mock.patch.object(thread_pool_factory.LOG, 'warning') as \
                mock_warning:
            size = thread_pool_factory.ExecutorsPoolSize._long_task_pool_size()

        # In eventlet mode, the pool size is addition of both.
        self.assertEqual(14, size)
        mock_warning.assert_not_called()

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_pool_size_threading_same_limits_no_warning(self, mock_warning):
        self.flags(max_concurrent_builds=7)
        self.flags(max_concurrent_snapshots=7)

        size = thread_pool_factory.ExecutorsPoolSize._long_task_pool_size()

        self.assertEqual(7, size)
        mock_warning.assert_not_called()

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_pool_size_threading_different_limits_warns(self, mock_warning):
        self.flags(max_concurrent_builds=10)
        self.flags(max_concurrent_snapshots=4)

        size = thread_pool_factory.ExecutorsPoolSize._long_task_pool_size()

        # In threading mode, the pool size is max of the two limits.
        self.assertEqual(10, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "In native threading mode the number of concurrent "
            "builds, and snapshots should be limited to the "
            "same number.", mock_warning.call_args[0][0])
        self.assertEqual((10, 4, 10), mock_warning.call_args[0][1:])


class MaxConcurrentBuildsTestCase(test.NoDBTestCase):

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_unlimited_threading_fallback_warns(self, mock_warning):
        self.flags(max_concurrent_builds=0)
        size = thread_pool_factory.get_max_concurrent_builds()

        self.assertEqual(10, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel instance builds so", mock_warning.call_args[0][0])

    def test_unlimited_eventlet_fallback_warns(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")
        self.flags(max_concurrent_builds=0)

        with mock.patch.object(thread_pool_factory.LOG, 'warning') as \
                mock_warning:
            size = thread_pool_factory.get_max_concurrent_builds()

        self.assertEqual(1000, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel instance builds so", mock_warning.call_args[0][0])


class MaxConcurrentSnapshotsTestCase(test.NoDBTestCase):

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_unlimited_threading_fallback_warns(self, mock_warning):
        self.flags(max_concurrent_snapshots=0)
        size = thread_pool_factory.get_max_concurrent_snapshots()

        self.assertEqual(5, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel instance snapshots so", mock_warning.call_args[0][0])

    def test_unlimited_eventlet_fallback_warns(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")
        self.flags(max_concurrent_snapshots=0)

        with mock.patch.object(thread_pool_factory.LOG, 'warning') as \
                mock_warning:
            size = thread_pool_factory.get_max_concurrent_snapshots()

        self.assertEqual(1000, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel instance snapshots so", mock_warning.call_args[0][0])


class CacheImagesExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.CACHE_IMAGES)
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.CacheImagesExecutor.*"
            "test_executor_is_named.cache_images")

    def test_executor_type_and_size(self):
        self.flags(precache_concurrency=9, group='image_cache')
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.CACHE_IMAGES)

        self.assertEqual(9, executor._max_workers)


class SyncPowerExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.SYNC_POWER)
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.SyncPowerExecutor.*"
            "test_executor_is_named.sync_power_state")

    def test_executor_type_and_size(self):
        self.flags(sync_power_state_pool_size=9)
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.SYNC_POWER)

        self.assertEqual(9, executor._max_workers)


class LiveMigrationExecutorTestCase(test.NoDBTestCase):
    def test_executor_is_named(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.LIVE_MIGRATION)
        self.assertRegex(executor.name,
            "nova.tests.unit.test_thread_pool_factory.LiveMigrationExecutor.*"
            "test_executor_is_named.live_migration")

    def test_executor_type_and_size(self):
        self.flags(max_concurrent_live_migrations=9)

        with mock.patch.object(thread_pool_factory.LOG, 'warning') as \
                mock_warning:
            size = thread_pool_factory.get_max_concurrent_live_migrations()

        self.assertEqual(9, size)
        mock_warning.assert_not_called()

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_pool_size_unlimited_threading_fallback_warns(self, mock_warning):
        self.flags(max_concurrent_live_migrations=0)

        size = thread_pool_factory.get_max_concurrent_live_migrations()

        self.assertEqual(5, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel live migration so", mock_warning.call_args[0][0])

    def test_pool_size_unlimited_eventlet_fallback_warns(self):
        if utils.concurrency_mode_threading():
            self.skipTest("This test can only be run in eventlet mode.")

        self.flags(max_concurrent_live_migrations=0)

        with mock.patch.object(thread_pool_factory.LOG, 'warning') as \
                mock_warning:
            size = thread_pool_factory.get_max_concurrent_live_migrations()

        self.assertEqual(1000, size)
        mock_warning.assert_called_once()
        self.assertIn(
            "Nova compute deprecated the support of unlimited "
            "parallel live migration so", mock_warning.call_args[0][0])


class GetExecutorTestCase(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.MockPatchObject(
            thread_pool_factory.FACTORY, '_shutdown', False))

    def test_get_executor_is_tracked(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        self.addCleanup(executor.shutdown, wait=False)
        self.assertIn(
            executor, thread_pool_factory.FACTORY._all_executors.values())

    def test_get_executor_after_shutdown_raises(self):
        thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        thread_pool_factory.shutdown_all_executors()

        exc = self.assertRaises(
            RuntimeError,
            thread_pool_factory.get_executor,
            thread_pool_factory.ExecutorType.DEFAULT)
        self.assertEqual(
            "Cannot create the default thread pool executor because "
            "shutdown has been started.", str(exc))

    def test_concurrent_first_get_creates_only_one_executor(self):
        # This is to test if one thread is creating the executor then
        # other thread wait and get the same executor even both are racing
        # for get executor.
        executor_type = thread_pool_factory.ExecutorType.DEFAULT
        factory = thread_pool_factory.FACTORY

        creating = threading.Event()
        proceed = threading.Event()
        real_new_executor = factory._new_executor

        def mock_new_executor(*args, **kwargs):
            creating.set()
            proceed.wait()
            return real_new_executor(*args, **kwargs)

        results = []

        def _get_executor():
            results.append(thread_pool_factory.get_executor(executor_type))

        with mock.patch.object(
                factory, '_new_executor',
                side_effect=mock_new_executor) as mock_executor:
            t1 = threading.Thread(target=_get_executor)
            t1.start()
            # Wait until t1 is inside the lock, creating the executor, but
            # has not stored it in _all_executors.
            creating.wait()

            # Start another thread to get_executors while t1 is in process of
            # crearting one.
            t2 = threading.Thread(target=_get_executor)
            t2.start()
            # Give t2 time to enter in get_executors and waiting for the
            # lock that t1 currently holds.
            time.sleep(0.5)

            # Let t1 finish creating the executor and update _all_executors.
            proceed.set()

            t1.join()
            t2.join()

        self.addCleanup(results[0].shutdown, wait=False)
        mock_executor.assert_called_once()
        self.assertEqual(2, len(results))
        # both results should have the same executor, means t2 did not create
        # the new one instead get the one t1 created.
        self.assertIs(results[0], results[1])


class ShutdownAllExecutorsTestCase(test.NoDBTestCase):

    def tearDown(self):
        super().tearDown()
        # NOTE(gmaan): thread_pool_factory.FACTORY is a process-wide singleton,
        # so calling shutdown_all_executors() in the tests below permanently
        # marks it as shutdown. Reset the _shutdown flag so other tests can
        # still create executors.
        thread_pool_factory.FACTORY._shutdown = False

    def test_shutdown_all_executors(self):
        executor1 = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        executor2 = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.LONG_TASK)
        self.assertIn(
            executor1, thread_pool_factory.FACTORY._all_executors.values())
        self.assertIn(
            executor2, thread_pool_factory.FACTORY._all_executors.values())

        thread_pool_factory.shutdown_all_executors()

        self.assertFalse(executor1.alive)
        self.assertFalse(executor2.alive)
        self.assertEqual({}, thread_pool_factory.FACTORY._all_executors)

    def test_shutdown_all_executors_shuts_down_with_wait(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        self.addCleanup(executor.shutdown, wait=False)

        with mock.patch.object(executor, 'shutdown') as mock_shutdown:
            thread_pool_factory.shutdown_all_executors()

        mock_shutdown.assert_called_once_with(wait=True)

    def test_shutdown_all_executors_clears_registry(self):
        thread_pool_factory.get_executor(
                thread_pool_factory.ExecutorType.DEFAULT)
        thread_pool_factory.get_executor(
                thread_pool_factory.ExecutorType.SCATTER_GATHER)
        thread_pool_factory.get_executor(
                thread_pool_factory.ExecutorType.CACHE_IMAGES)
        thread_pool_factory.get_executor(
                thread_pool_factory.ExecutorType.LONG_TASK)

        self.assertEqual(4, len(thread_pool_factory.FACTORY._all_executors))

        thread_pool_factory.shutdown_all_executors()

        self.assertEqual({}, thread_pool_factory.FACTORY._all_executors)


class ResetAllExecutorsTestCase(test.NoDBTestCase):

    def setUp(self):
        # NOTE: super().setUp() below mocks
        # nova.thread_pool_factory.reset_all_executors. Capture the real
        # function here first so these tests can call it directly.
        self._real_reset_all_executors = (
            thread_pool_factory.reset_all_executors)
        super().setUp()

    def test_reset_all_executors(self):
        executor1 = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        executor2 = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.LONG_TASK)

        self._real_reset_all_executors()

        self.assertFalse(executor1.alive)
        self.assertFalse(executor2.alive)
        self.assertEqual({}, thread_pool_factory.FACTORY._all_executors)

    def test_reset_all_executors_shutdown_with_wait(self):
        executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        with mock.patch.object(executor, 'shutdown') as mock_shutdown:
            self._real_reset_all_executors()

        mock_shutdown.assert_called_once_with(wait=True)

    def test_reset_all_executors_does_not_mark_factory_shutdown(self):
        thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        self._real_reset_all_executors()

        self.assertFalse(thread_pool_factory.FACTORY._shutdown)

        # A new executor must still be creatable afterwards, unlike after
        # a real shutdown_all().
        new_executor = thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)
        self.addCleanup(new_executor.shutdown, wait=False)
        self.assertIn(
            new_executor, thread_pool_factory.FACTORY._all_executors.values())


class SpawnOnTestCase(test.NoDBTestCase):
    def test_spawn_on_submits_work(self):
        task = mock.MagicMock()

        future = thread_pool_factory.spawn_on(
            thread_pool_factory.ExecutorType.SCATTER_GATHER,
            task, 13, foo='bar')
        future.result()

        task.assert_called_once_with(13, foo='bar')

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'warning')
    def test_spawn_on_warns_on_full_executor(self, mock_warning):
        # Ensure we have executor for a single task only at a time
        self.flags(cell_worker_thread_pool_size=1)

        work = threading.Event()
        started = threading.Event()

        # let the blocked tasks finish after the test case so that the leaked
        # thread check is not triggered during cleanup
        self.addCleanup(work.set)

        def task():
            started.set()
            work.wait()

        # Start two tasks that will wait, the first will execute the second
        # will wait in the queue
        scatter_gather = thread_pool_factory.ExecutorType.SCATTER_GATHER
        thread_pool_factory.spawn_on(scatter_gather, task)
        thread_pool_factory.spawn_on(scatter_gather, task)
        # wait for the first task to consume the single executor thread
        started.wait()
        # start one more task to trigger the fullness check.
        thread_pool_factory.spawn_on(scatter_gather, task)

        executor = thread_pool_factory.get_executor(scatter_gather)

        # We expect that spawn_on will warn due to the second task being is
        # waiting in the queue, and no idle worker thread exists.
        mock_warning.assert_called_once_with(
            "The %s pool does not have free threads so the task %s will be "
            "queued. If this happens repeatedly then the size of the pool is "
            "too small for the load or there are stuck threads filling the "
            "pool.", executor.name, task)

    def test_spawn_on_initializes_profiler(self):
        trace_info = {
            "hmac_key": "key",
            "base_id": "base-id",
            "parent_id": "parent-id",
        }
        task_done = threading.Event()

        def task():
            task_done.set()

        with mock.patch.object(
                thread_pool_factory, '_serialize_profile_info',
                return_value=trace_info), \
                mock.patch.object(
                    thread_pool_factory.profiler, 'init') as mock_init:
            future = thread_pool_factory.spawn_on(
                thread_pool_factory.ExecutorType.DEFAULT, task)
            future.result()

        self.assertTrue(task_done.is_set())
        mock_init.assert_called_once_with(**trace_info)


class SerializeProfileInfoTestCase(test.NoDBTestCase):

    def test_profiler_returns_trace_info(self):
        prof = mock.Mock()
        prof.hmac_key = 'key'
        prof.get_base_id.return_value = 'base-id'
        prof.get_id.return_value = 'parent-id'

        with mock.patch.object(
                thread_pool_factory.profiler, 'get', return_value=prof):
            trace_info = thread_pool_factory._serialize_profile_info()

        self.assertEqual(
            {
                "hmac_key": 'key',
                "base_id": 'base-id',
                "parent_id": 'parent-id',
            },
            trace_info)


class ExecutorStatsTestCase(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.work = threading.Event()

    def _task_finishes(self):
        return

    def _task_fails(self):
        raise ValueError()

    def _task_running(self):
        self.work.wait()

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=False))
    @mock.patch.object(thread_pool_factory.LOG, 'debug')
    def test_stats_logged_eventlet(self, mock_debug):
        env = os.environ.get('OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower()
        if env in ('1', 'true', 'yes'):
            self.skipTest(
                "In native threading mode this case is covered by "
                "test_stats_logged_threading")

        # ensure that each task submission triggers stats printing
        self.flags(thread_pool_statistic_period=0)

        thread_pool_factory.spawn(self._task_finishes).result()
        thread_pool_factory.spawn(self._task_fails).exception()
        running = thread_pool_factory.spawn(self._task_running)

        # avoid having a hanging thread leaking from the test case
        def cleanup():
            self.work.set()
            running.result()

        self.addCleanup(cleanup)

        # The stats are printed *before* the work is submitted so we need an
        # extra task submitted to get the stats from the above task.
        thread_pool_factory.spawn(self._task_finishes).result()

        args = mock_debug.mock_calls[3][1]
        self.assertEqual(
            ('State of %s GreenThreadPoolExecutor when submitting a new task: '
             'workers: %d, max_workers: %d, work queued length: %d, stats: %s',
             'default', 1, 1000, 0),
            args[0:5])
        stats = args[5]
        self.assertEqual(1, stats.failures)
        self.assertEqual(2, stats.executed)
        self.assertEqual(0, stats.cancelled)

    @mock.patch.object(
        utils, 'concurrency_mode_threading', new=mock.Mock(return_value=True))
    @mock.patch.object(thread_pool_factory.LOG, 'debug')
    def test_stats_logged_threading(self, mock_debug):
        if not utils.concurrency_mode_threading():
            self.skipTest(
                "In eventlet mode this case is covered by "
                "test_stats_logged_eventlet")

        # ensure that each task submission triggers stats printing
        self.flags(thread_pool_statistic_period=0)
        # make the tasks sequential to help simulating queued task
        self.flags(default_thread_pool_size=1)

        thread_pool_factory.spawn(self._task_finishes).result()
        thread_pool_factory.spawn(self._task_fails).exception()
        running = thread_pool_factory.spawn(self._task_running)

        # avoid having a hanging thread leaking from the test case
        def cleanup():
            self.work.set()
            running.result()

        self.addCleanup(cleanup)

        # this will be queued as the only worker thread is held up by the
        # running task
        thread_pool_factory.spawn(self._task_finishes)
        # this is also queued so we can cancel it to dequeue it
        thread_pool_factory.spawn(self._task_finishes).cancel()
        # The stats are printed *before* the work is submitted so we need an
        # extra task submitted to get the stats from the above task.
        thread_pool_factory.spawn(self._task_finishes)

        args = mock_debug.mock_calls[5][1]
        self.assertEqual(
            ('State of %s ThreadPoolExecutor when submitting a new task: '
             'max_workers: %d, workers: %d, idle workers: %d, queued work: %d,'
             ' stats: %s',
             'default',
             1, 1, 1, 3),
            args[0:6])
        stats = args[6]
        self.assertEqual(1, stats.failures)
        self.assertEqual(2, stats.executed)
        self.assertEqual(1, stats.cancelled)

    @mock.patch.object(thread_pool_factory.LOG, 'debug')
    def test_stats_skipped_if_too_frequent(self, mock_debug):
        self.flags(thread_pool_statistic_period=10)
        thread_pool_factory.spawn(self._task_finishes).result()
        mock_debug.assert_called()
        mock_debug.reset_mock()

        thread_pool_factory.spawn(self._task_finishes).result()
        mock_debug.assert_not_called()

    @mock.patch.object(thread_pool_factory.LOG, 'debug')
    def test_stats_skipped_disabled(self, mock_info):
        self.flags(thread_pool_statistic_period=-1)

        thread_pool_factory.spawn(self._task_finishes).result()
        mock_info.assert_not_called()

    @mock.patch.object(thread_pool_factory.LOG, 'debug')
    def test_stats_not_logged_by_direct_get_executor(self, mock_debug):
        # get_executor() itself does not submit any task, so unlike
        # spawn()/spawn_on() it must not log stats or warn about a full
        # executor by default.
        self.flags(thread_pool_statistic_period=0)

        thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT)

        mock_debug.assert_not_called()


class StaticallyDelayingCancellableTaskExecutorWrapperTest(test.NoDBTestCase):
    def test_submit_one(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.01, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown)

        task_done = threading.Event()

        def task(num, foo):
            self.assertEqual(12, num)
            self.assertEqual("bar", foo)
            task_done.set()
            return foo + str(num)

        future = executor.submit_with_delay(task, 12, foo="bar")

        result = future.result()
        self.assertTrue(task_done.is_set())
        self.assertEqual("bar12", result)

    def test_submit_one_exception_result(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.01, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown)

        task_done = threading.Event()
        exc_to_raise = ValueError()

        def task(num, foo):
            self.assertEqual(12, num)
            self.assertEqual("bar", foo)
            task_done.set()
            raise exc_to_raise

        future = executor.submit_with_delay(task, 12, foo="bar")
        exc = future.exception()

        self.assertTrue(task_done.is_set())
        self.assertEqual(exc_to_raise, exc)

    def test_submit_two_non_overlapping(self):

        def task1():
            return 42

        def task2():
            return 13

        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.01, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        future1 = executor.submit_with_delay(task1)
        self.assertEqual(42, future1.result())

        future2 = executor.submit_with_delay(task2)
        self.assertEqual(13, future2.result())

        self.assertTrue(executor._queue.empty())

    def test_submit_second_while_delaying_first(self):
        task1_started = threading.Event()

        def task1():
            task1_started.set()
            return 42

        task2_started = threading.Event()

        def task2():
            task2_started.set()
            return 13

        # Create a "long" delay so the task will be actively managed by
        # the wrapper while we submit the second task
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        task1_start = time.monotonic()
        future1 = executor.submit_with_delay(task1)
        # wait a bit so the wrapper is picking it up and waiting for its
        # deadline
        time.sleep(1)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(task1_started.is_set())

        # now submit the second task, it will be queued
        task2_start = time.monotonic()
        future2 = executor.submit_with_delay(task2)
        self.assertFalse(executor._queue.empty())
        self.assertFalse(task1_started.is_set())

        # eventually both tasks finishes
        self.assertEqual(42, future1.result())
        task1_end = time.monotonic()
        self.assertEqual(13, future2.result())
        task2_end = time.monotonic()

        # and both tasks took about delay seconds individually, but the two
        # tasks together took less than 2x delay seconds as they were
        # overlapped.
        task1_runtime = task1_end - task1_start
        self.assertLess(task1_runtime, 2.5)
        self.assertGreater(task1_runtime, 2.0)
        task2_runtime = task2_end - task2_start
        self.assertLess(task2_runtime, 2.5)
        self.assertGreater(task2_runtime, 2.0)
        total_runtime = task2_end - task1_start
        self.assertLess(total_runtime, 4)

    def test_submit_multiple(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.1, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        def task(i):
            return 2 * i

        futures = []
        for i in range(20):
            futures.append(executor.submit_with_delay(task, i))

        for i, f in enumerate(futures):
            self.assertEqual(2 * i, f.result())

        executor.shutdown(wait=True)

    def test_submit_multiple_executor_rejects_first_executes_second(self):
        def task1():
            return 42

        def task2():
            return 13

        check_and_reject = mock.Mock(
            side_effect=[futurist.RejectedSubmission(), None])

        if utils.concurrency_mode_threading():
            ex = futurist.ThreadPoolExecutor(
                max_workers=1, check_and_reject=check_and_reject)
        else:
            ex = futurist.GreenThreadPoolExecutor(
                max_workers=1, check_and_reject=check_and_reject)

        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.1, ex))
        self.addCleanup(executor.shutdown, wait=True)

        future1 = executor.submit_with_delay(task1)
        future2 = executor.submit_with_delay(task2)

        self.assertEqual(
            futurist.RejectedSubmission, type(future1.exception()))
        self.assertEqual(13, future2.result())

    def test_cancel_during_delay(self):
        task1_started = threading.Event()

        def task1():
            task1_started.set()
            return 42

        def task2():
            return 13

        # Create a "long" delay so the task will be actively delayed by
        # the wrapper when we cancel it
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        future1 = executor.submit_with_delay(task1)
        # wait a bit to let the task being picked up
        time.sleep(1)
        # it is not in the queue, so it is picked up
        self.assertTrue(executor._queue.empty())
        # but not executing yet so it is being delayed
        self.assertFalse(task1_started.is_set())

        # cancel the task
        future1.cancel()

        # Submit and wait for the execution of the second task to prove
        # that the executor had time to finish waiting for the deadline of
        # the first task, detected the cancellation and skipped the task,
        # then executed the second task.
        future2 = executor.submit_with_delay(task2)
        self.assertEqual(13, future2.result())

        # task1 is still not executed
        self.assertFalse(task1_started.is_set())
        self.assertTrue(future1.cancelled())
        # no tasks remaining in the executor queue
        self.assertTrue(executor._queue.empty())

    def test_cancel_while_in_queue(self):
        task1_started = threading.Event()

        def task1():
            task1_started.set()
            return 42

        task2_started = threading.Event()

        def task2():
            task2_started.set()
            return 13

        # Create a "long" delay so one task will be actively delayed while
        # we submit a second task then cancel the second task.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        future1 = executor.submit_with_delay(task1)
        # Wait a bit to let the task being picked up.
        time.sleep(1)
        # It is not in the queue, so it is picked up,
        self.assertTrue(executor._queue.empty())
        # but not executing yet, so it is being delayed
        self.assertFalse(task1_started.is_set())

        # Submit a second task that will be queued.
        future2 = executor.submit_with_delay(task2)
        self.assertFalse(executor._queue.empty())
        self.assertFalse(task2_started.is_set())

        # Cancel the second task while it is in the queue.
        future2.cancel()

        # The first task should finish normally
        self.assertEqual(42, future1.result())

        # But the second task should never be executed.
        # To prove that we shutdown both the wrapper and the real executor
        # then check the second task again.
        executor.shutdown(wait=True)
        thread_pool_factory.get_executor(
            thread_pool_factory.ExecutorType.DEFAULT).shutdown(wait=True)
        self.assertFalse(task2_started.is_set())
        self.assertTrue(future2.cancelled())

    def test_instantaneous_shutdown(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.1, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        executor.shutdown(wait=False)
        self.assertTrue(executor._shutdown)

    def test_shutdown_wait(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.1, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        executor.shutdown(wait=True)
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)
        # Shutting down the wrapper does not affect the real executor
        self.assertTrue(executor._executor.alive)

    def test_submit_after_shutdown_rejected(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.1, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        executor.shutdown()
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

        exc = self.assertRaises(
            RuntimeError, executor.submit_with_delay, lambda: None)
        self.assertEqual(
            "Cannot schedule new tasks after being shutdown", str(exc))

    def test_submit_while_shutting_down(self):
        task_started = threading.Event()

        def task():
            task_started.set()

        # Create a "long" delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        executor.submit_with_delay(task)
        executor.shutdown(wait=False)

        # the task is actively managed, delayed, by our wrapper while we are
        # shutting the executor down, we should not be able to add new tasks
        # even if the shutdown is not finished yet
        self.assertFalse(task_started.is_set())
        exc = self.assertRaises(
            RuntimeError, executor.submit_with_delay, lambda: None)
        self.assertEqual(
            "Cannot schedule new tasks after being shutdown", str(exc))

    def test_shutdown_after_task_finished(self):
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                0.01, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown)

        def task():
            return

        future = executor.submit_with_delay(task)
        future.result()

        executor.shutdown()

        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

    def test_no_wait_shutdown_task_finishes_normally(self):
        task_started = threading.Event()

        def task():
            task_started.set()
            return 42

        # Create a "long" delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))
        self.addCleanup(executor.shutdown, wait=True)

        future = executor.submit_with_delay(task)
        # Task is not executing it is being delayed
        self.assertFalse(task_started.is_set())

        # We expect that shutdown returns even though there are tasks being
        # actively managed, delayed, by the executor as we called it with
        # wait=False
        executor.shutdown(wait=False)

        self.assertTrue(executor._shutdown)
        self.assertFalse(executor._queue.empty())
        self.assertTrue(executor.is_alive)

        # Task is still delayed
        self.assertFalse(task_started.is_set())
        # and it is not cancelled
        self.assertFalse(future.cancelled())
        # and eventually executed
        self.assertEqual(42, future.result())
        # and eventually the executor is terminated. This also covers the case
        # when multiple shutdown call is made to the same executor.
        executor.shutdown(wait=True)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

    def test_no_wait_shutdown_multiple_tasks_finishes_normally(self):
        task1_started = threading.Event()

        def task1():
            task1_started.set()
            return 42

        task2_started = threading.Event()

        def task2():
            task2_started.set()
            return 13

        # Create a "long" delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        future1 = executor.submit_with_delay(task1)
        future2 = executor.submit_with_delay(task2)
        # Tasks are not executing they are being delayed
        self.assertFalse(task1_started.is_set())
        self.assertFalse(task2_started.is_set())

        # wait a bit so the wrapper actually starts waiting for the deadline
        # of task1
        time.sleep(1)
        # Task are still not executing
        self.assertFalse(task1_started.is_set())
        self.assertFalse(task2_started.is_set())
        # task1 is already popped from the queue and the code is waiting for
        # its deadline, while task2 is in the queue waiting
        self.assertEqual(1, executor._queue.qsize())

        # Shut down the executor. We expect that the tasks are still executed
        executor.shutdown(wait=True)

        self.assertEqual(42, future1.result())
        self.assertEqual(13, future2.result())
        # and our wrapper is in a shutdown state
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

    def test_shutdown_wait_task_finishes_normally(self):
        task_started = threading.Event()

        def task():
            task_started.set()
            return 42

        # Create a "long" delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        future = executor.submit_with_delay(task)
        # Task is not executing it is being delayed
        self.assertFalse(task_started.is_set())

        # We expect that shutdown waits for the task to be submitted to the
        # real executor after the delay
        executor.shutdown(wait=True)
        # Task is now submitted to the real executor so it can actually run
        # and produce a result
        result = future.result()
        self.assertTrue(task_started.is_set())
        self.assertEqual(42, result)
        # but our wrapper is in a shutdown state
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

    def test_shutdown_does_not_wait_for_cancelled_task(self):
        task_started = threading.Event()

        def task():
            task_started.set()
            return 42

        # Create a very long delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it and we can
        # check that the wrapper detects cancelled tasks during shutdown and
        # does not wait for the whole deadline.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2000, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        future = executor.submit_with_delay(task)
        # Task is not executing it is being delayed
        self.assertFalse(task_started.is_set())

        # Cancel the task, shutdown the executor. We expect that the cancelled
        # task is not submitted for execution.
        future.cancel()
        executor.shutdown(wait=True)
        self.assertFalse(task_started.is_set())
        self.assertTrue(future.cancelled())
        # and our wrapper is in a shutdown state
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

    def test_shutdown_does_not_wait_for_multiple_cancelled_tasks(self):
        task1_started = threading.Event()

        def task1():
            task1_started.set()
            return 42

        task2_started = threading.Event()

        def task2():
            task2_started.set()
            return 13

        # Create a very long delay so the task will be actively managed by
        # the wrapper while the test calls shutdown on it and we can
        # check that the wrapper detects cancelled tasks during shutdown and
        # does not wait for the whole deadline.
        executor = (
            thread_pool_factory.
            StaticallyDelayingCancellableTaskExecutorWrapper(
                2000, thread_pool_factory.get_executor(
                    thread_pool_factory.ExecutorType.DEFAULT)))

        future1 = executor.submit_with_delay(task1)
        future2 = executor.submit_with_delay(task2)
        # Tasks are not executing they are being delayed
        self.assertFalse(task1_started.is_set())
        self.assertFalse(task2_started.is_set())

        # wait a bit so the wrapper actually starts waiting for the deadline
        # of task1
        time.sleep(1)
        # Task are still not executing
        self.assertFalse(task1_started.is_set())
        self.assertFalse(task2_started.is_set())
        # task1 is already popped from the queue and the code is waiting for
        # its deadline, while task2 is in the queue waiting
        self.assertEqual(1, executor._queue.qsize())

        # Cancel both tasks then shutdown the executor and expect that no
        # task will be executed.
        future1.cancel()
        future2.cancel()
        executor.shutdown(wait=True)

        self.assertFalse(task1_started.is_set())
        self.assertTrue(future1.cancelled())
        self.assertFalse(task2_started.is_set())
        self.assertTrue(future2.cancelled())
        # and our wrapper is in a shutdown state
        self.assertTrue(executor._shutdown)
        self.assertTrue(executor._queue.empty())
        self.assertFalse(executor.is_alive)

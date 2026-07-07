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

import concurrent.futures
import functools
import threading
import time
from unittest import mock

from nova import manager
from nova import test


class SkipGeneralTrackingTestCase(test.NoDBTestCase):

    def test_marks_function(self):
        def fake():
            pass

        decorated = manager.skip_automatic_rpc_tracking(fake)

        self.assertIs(fake, decorated)
        self.assertTrue(decorated._skip_automatic_rpc_tracking)


class ManagerTaskTrackingTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ManagerTaskTrackingTestCase, self).setUp()
        self.manager = manager.Manager(host='fake-host',
                                       service_name='test-service')

    def test_init_state(self):
        self.assertFalse(self.manager._shutdown_in_progress.is_set())
        self.assertEqual({}, self.manager._in_progress_tasks)
        self.assertEqual({}, self.manager._failed_tasks)
        self.assertEqual(0, self.manager._completed_task_count)
        self.assertEqual(0, self.manager._in_progress_task_key_counter)

    def test_set_shutdown_in_progress(self):
        self.assertFalse(self.manager._shutdown_in_progress.is_set())

        self.manager.set_shutdown_in_progress()

        self.assertTrue(self.manager._shutdown_in_progress.is_set())

    @mock.patch.object(manager.Manager, 'run_periodic_tasks')
    def test_periodic_tasks_skipped_when_shutdown_in_progress(
            self, mock_run):
        # Periodic tasks are not run when shutdown is in progress
        self.manager._shutdown_in_progress.set()
        result = self.manager.periodic_tasks(mock.sentinel.context)
        mock_run.assert_not_called()
        self.assertIsNone(result)

        # Periodic tasks runs normally when shutdown is not in progress
        self.manager._shutdown_in_progress.clear()
        self.manager.periodic_tasks(
            mock.sentinel.context, raise_on_error=True)
        mock_run.assert_called_once_with(
            mock.sentinel.context, raise_on_error=True)

    def test_record_task_start_assigns_increasing_keys(self):
        key1 = self.manager._record_task_start(
            'task-a', 'instance-1', 'req-1')
        key2 = self.manager._record_task_start('task-b')

        self.assertEqual(1, key1)
        self.assertEqual(2, key2)
        task = self.manager._in_progress_tasks[key1]
        self.assertEqual('task-a', task['name'])
        self.assertEqual('instance-1', task['instance_uuid'])
        self.assertEqual('req-1', task['request_id'])
        self.assertIn('start_time', task)

    def test_record_task_end_removes_task(self):
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')

        self.manager._record_task_end(key)

        self.assertEqual({}, self.manager._in_progress_tasks)

    def test_record_task_end_unknown_key_is_noop(self):
        self.manager._record_task_end(999)

        self.assertEqual({}, self.manager._in_progress_tasks)
        # Logged so an operator can see an unexpected/duplicate callback.
        self.assertIn(
            'Graceful shutdown: _record_task_end called for unrecorded '
            'or already-ended task key: 999', self.stdlog.logger.output)

    def test_record_task_end_called_twice_logs_warning(self):
        # Calling _record_task_end() again for an already-ended task (e.g.
        # a double callback) should log warning.
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        self.manager._shutdown_in_progress.set()
        warning_msg = (
            'Graceful shutdown: _record_task_end called for unrecorded '
            'or already-ended task key: %s' % key)

        self.manager._record_task_end(key)
        self.assertNotIn(warning_msg, self.stdlog.logger.output)

        self.manager._record_task_end(key)

        self.assertEqual(1, self.stdlog.logger.output.count(warning_msg))
        self.assertEqual(1, self.manager._completed_task_count)

    def test_record_task_end_via_future_done_callback(self):
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        future = concurrent.futures.Future()
        future.add_done_callback(
            functools.partial(self.manager._record_task_end, key))
        self.assertEqual(1, len(self.manager._in_progress_tasks))

        future.set_result(None)

        self.assertEqual({}, self.manager._in_progress_tasks)

    def test_record_task_end_tracks_completed_count_during_shutdown(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')

        self.manager._record_task_end(key)

        self.assertEqual(1, self.manager._completed_task_count)
        self.assertEqual({}, self.manager._failed_tasks)
        self.assertIn(
            'Graceful shutdown: task completed: task-a '
            '(instance: instance-1, request_id: req-1',
            self.stdlog.logger.output)
        self.assertIn(
            'remaining in-progress tasks: 0)', self.stdlog.logger.output)

    def test_record_task_end_not_tracked_when_no_shutdown(self):
        key1 = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        self.manager._record_task_end(key1)

        key2 = self.manager._record_task_start('task-b', 'instance-1', 'req-1')
        self.manager._record_task_end(key2, failed=True)

        self.assertEqual(0, self.manager._completed_task_count)
        self.assertEqual({}, self.manager._failed_tasks)

    def test_record_task_end_explicit_failed(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')

        self.manager._record_task_end(key, failed=True)

        self.assertEqual(0, self.manager._completed_task_count)
        self.assertEqual(1, len(self.manager._failed_tasks))
        self.assertEqual('task-a', self.manager._failed_tasks[key]['name'])
        self.assertIn(
            'Graceful shutdown: task failed: task-a '
            '(instance: instance-1, request_id: req-1',
            self.stdlog.logger.output)

    def test_record_task_end_derives_failed_from_future_exception(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        future = concurrent.futures.Future()
        future.set_exception(test.TestingException())

        self.manager._record_task_end(key, future=future)

        self.assertEqual(0, self.manager._completed_task_count)
        self.assertEqual(1, len(self.manager._failed_tasks))

    def test_record_task_end_derives_failed_from_future_cancelled(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        future = concurrent.futures.Future()
        self.assertTrue(future.cancel())

        self.manager._record_task_end(key, future=future)

        self.assertEqual(0, self.manager._completed_task_count)
        self.assertEqual(1, len(self.manager._failed_tasks))

    def test_record_task_end_future_overrides_failed_kwarg(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        future = concurrent.futures.Future()
        future.set_result(None)

        self.manager._record_task_end(key, future=future, failed=True)

        self.assertEqual(1, self.manager._completed_task_count)
        self.assertEqual({}, self.manager._failed_tasks)

    def test_summarize_failed_tasks(self):
        self.manager._shutdown_in_progress.set()
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        self.manager._record_task_end(key, failed=True)

        summary = self.manager._summarize_failed_tasks()

        self.assertIn('task-a', summary)
        self.assertIn('instance-1', summary)
        self.assertIn('req-1', summary)

    def test_record_task_logs_when_shutdown_in_progress(self):
        # We do not log tasks recording if no shutdown is initiated.
        key1 = self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        self.manager._record_task_end(key1)
        self.assertNotIn(
            'Graceful shutdown: new task started', self.stdlog.logger.output)
        self.assertNotIn(
            'Graceful shutdown: task completed: task-a',
            self.stdlog.logger.output)

        self.manager._shutdown_in_progress.set()
        key2 = self.manager._record_task_start('task-b', 'instance-1', 'req-1')
        self.assertIn(
            'Graceful shutdown: new task started after shutdown '
            'initiated: task-b (instance: instance-1, request_id: req-1',
            self.stdlog.logger.output)
        self.manager._record_task_end(key2)
        self.assertIn(
            'Graceful shutdown: task completed: task-b '
            '(instance: instance-1, request_id: req-1',
            self.stdlog.logger.output)

    def test_summarize_in_progress_tasks(self):
        self.manager._record_task_start('task-a', 'instance-1', 'req-1')

        with self.manager._in_progress_task_cond:
            summary = self.manager._summarize_in_progress_tasks()

        self.assertIn('task-a', summary)
        self.assertIn('instance-1', summary)
        self.assertIn('req-1', summary)

    def test_wait_for_in_progress_tasks_returns_immediately_if_empty(self):
        start = time.monotonic()

        self.manager._wait_for_in_progress_tasks(30)

        self.assertLess(time.monotonic() - start, 5)
        self.assertIn(
            'Graceful shutdown: no in-progress tasks.',
            self.stdlog.logger.output)

    def test_wait_for_in_progress_tasks_waits_for_completion(self):
        key = self.manager._record_task_start('task-a', 'instance-1', 'req-1')

        # Signal when _wait_for_in_progress_tasks() actually starts
        # blocking on the self.manager._in_progress_task_cond.wait for the
        # second time, so we know that it is waiting before the task ends.
        entered_wait = threading.Event()
        orig_wait = self.manager._in_progress_task_cond.wait
        call_count = {'n': 0}

        def _wait(*args, **kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                # Simulate the log_interval elapsing without the task
                # finishing, so the "still waiting" message is also
                # exercised below, then loop back for a real wait.
                return
            entered_wait.set()
            return orig_wait(*args, **kwargs)

        wait_thread = threading.Thread(
            target=self.manager._wait_for_in_progress_tasks, args=(30,))
        with mock.patch.object(
                self.manager._in_progress_task_cond, 'wait',
                side_effect=_wait):
            wait_thread.start()
            self.addCleanup(wait_thread.join)

            self.assertTrue(
                entered_wait.wait(timeout=5),
                'Timed out waiting for _wait_for_in_progress_tasks to '
                'start waiting')
            self.assertTrue(wait_thread.is_alive())
            self.assertIn(key, self.manager._in_progress_tasks)
            self.assertIn(
                'Graceful shutdown initiated with 1 in-progress tasks: '
                'task-a(instance=instance-1, request_id=req-1',
                self.stdlog.logger.output)
            self.assertIn(
                'Graceful shutdown still waiting for 1 in progress tasks: '
                'task-a(instance=instance-1, request_id=req-1',
                self.stdlog.logger.output)

            # This will complete the _wait_for_in_progress_tasks
            self.manager._record_task_end(key)

            # This would time out at 30s if the wait didn't wake up as
            # soon as the task finished.
            wait_thread.join(timeout=5)

        self.assertFalse(wait_thread.is_alive())
        self.assertEqual({}, self.manager._in_progress_tasks)
        self.assertIn(
            'Graceful shutdown: all in-progress tasks finished. '
            'completed tasks: 0, failed tasks: 0', self.stdlog.logger.output)

    def test_wait_for_in_progress_tasks_reports_completed_and_failed(self):
        self.manager._shutdown_in_progress.set()
        key1 = self.manager._record_task_start(
            'task-a', 'instance-1', 'req-1')
        key2 = self.manager._record_task_start(
            'task-b', 'instance-2', 'req-2')

        def _finish_soon():
            time.sleep(0.1)
            self.manager._record_task_end(key1)
            self.manager._record_task_end(key2, failed=True)

        t = threading.Thread(target=_finish_soon)
        t.start()
        self.addCleanup(t.join)

        self.manager._wait_for_in_progress_tasks(30)

        self.assertEqual({}, self.manager._in_progress_tasks)
        self.assertEqual(1, self.manager._completed_task_count)
        self.assertEqual(1, len(self.manager._failed_tasks))

        self.assertIn(
            'Graceful shutdown initiated with 2 in-progress tasks: ',
            self.stdlog.logger.output)
        self.assertIn(
            'Graceful shutdown: task completed: task-a '
            '(instance: instance-1, request_id: req-1',
            self.stdlog.logger.output)
        self.assertIn(
            'remaining in-progress tasks: 1)', self.stdlog.logger.output)
        self.assertIn(
            'Graceful shutdown: task failed: task-b '
            '(instance: instance-2, request_id: req-2',
            self.stdlog.logger.output)
        self.assertIn(
            'remaining in-progress tasks: 0)', self.stdlog.logger.output)
        self.assertIn(
            'Graceful shutdown: all in-progress tasks finished. '
            'completed tasks: 1, failed tasks: 1: task-b(instance=instance-2, '
            'request_id=req-2)', self.stdlog.logger.output)

    def test_wait_for_in_progress_tasks_times_out(self):
        self.manager._record_task_start('task-a', 'instance-1', 'req-1')
        start = time.monotonic()

        self.manager._wait_for_in_progress_tasks(0.2)

        self.assertGreaterEqual(time.monotonic() - start, 0.2)
        self.assertEqual(1, len(self.manager._in_progress_tasks))
        self.assertIn(
            'Graceful shutdown timed out with 1 tasks still in progress: '
            'task-a(instance=instance-1, request_id=req-1',
            self.stdlog.logger.output)

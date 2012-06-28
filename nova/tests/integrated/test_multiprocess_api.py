# Copyright (c) 2012 Intel, LLC
# Copyright (c) 2012 OpenStack, LLC
#
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

"""
Test multiprocess enabled API service.
"""
import os
import signal
import time
import traceback

from nova import flags
from nova.openstack.common.log import logging
from nova import service
from nova.tests.integrated import integrated_helpers

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class MultiprocessWSGITest(integrated_helpers._IntegratedTestBase):
    def _start_api_service(self):
        # Process will be started in _spawn()
        self.osapi = service.WSGIService("osapi_compute")
        self.auth_url = 'http://%s:%s/v2' % (self.osapi.host, self.osapi.port)
        LOG.info('auth_url = %s' % self.auth_url)

    def _get_flags(self):
        self.workers = 2
        f = super(MultiprocessWSGITest, self)._get_flags()
        f['osapi_compute_workers'] = self.workers
        return f

    def _spawn(self):
        pid = os.fork()
        if pid == 0:
            # NOTE(johannes): We can't let the child processes exit back
            # into the unit test framework since then we'll have multiple
            # processes running the same tests (and possibly forking more
            # processes that end up in the same situation). So we need
            # to catch all exceptions and make sure nothing leaks out, in
            # particlar SystemExit, which is raised by sys.exit(). We use
            # os._exit() which doesn't have this problem.
            status = 0
            try:
                launcher = service.ProcessLauncher()
                launcher.launch_server(self.osapi, workers=self.osapi.workers)
                launcher.wait()
            except SystemExit as exc:
                status = exc.code
            except BaseException:
                # We need to be defensive here too
                try:
                    traceback.print_exc()
                except BaseException:
                    print "Couldn't print traceback"
                status = 2

            # Really exit
            os._exit(status)

        self.pid = pid

        # Wait for up to a second for workers to get started
        start = time.time()
        while time.time() - start < 1:
            workers = self._get_workers()
            if len(workers) == self.workers:
                break

            time.sleep(.1)

        self.assertEqual(len(workers), self.workers)
        return workers

    def tearDown(self):
        if self.pid:
            # Make sure all processes are stopped
            os.kill(self.pid, signal.SIGTERM)

            # Make sure we reap our test process
            self._reap_test()

        super(MultiprocessWSGITest, self).tearDown()

    def _reap_test(self):
        pid, status = os.waitpid(self.pid, 0)
        self.pid = None
        return status

    def _get_workers(self):
        f = os.popen('ps ax -o pid,ppid,command')
        # Skip ps header
        f.readline()

        processes = [tuple(int(p) for p in l.strip().split()[:2])
                     for l in f.readlines()]
        return [p for p, pp in processes if pp == self.pid]

    def test_killed_worker_recover(self):
        start_workers = self._spawn()

        # kill one worker and check if new worker can come up
        LOG.info('pid of first child is %s' % start_workers[0])
        os.kill(start_workers[0], signal.SIGTERM)

        # loop and check if new worker is spawned (for 1 second max)
        start = time.time()
        while time.time() - start < 1:
            end_workers = self._get_workers()
            LOG.info('workers: %r' % end_workers)

            if start_workers != end_workers:
                break

            time.sleep(.1)

        # Make sure worker pids don't match
        self.assertNotEqual(start_workers, end_workers)

        # check if api service still works
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')

    def _terminate_with_signal(self, sig):
        self._spawn()

        # check if api service is working
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')

        os.kill(self.pid, sig)

        # loop and check if all processes are killed (for 1 second max)
        start = time.time()
        while time.time() - start < 1:
            workers = self._get_workers()
            LOG.info('workers: %r' % workers)

            if not workers:
                break

            time.sleep(.1)

        self.assertFalse(workers, 'No OS processes left.')

    def test_terminate_sigkill(self):
        self._terminate_with_signal(signal.SIGKILL)
        status = self._reap_test()
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

    def test_terminate_sigterm(self):
        self._terminate_with_signal(signal.SIGTERM)
        status = self._reap_test()
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status), 0)

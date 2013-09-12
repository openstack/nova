# Copyright (c) 2012 Intel, LLC
# Copyright (c) 2012 OpenStack Foundation
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
import errno
import fixtures
import os
import signal
import time
import traceback

from nova.openstack.common import log as logging
from nova import service
from nova.tests.integrated.api import client
from nova.tests.integrated import integrated_helpers

LOG = logging.getLogger(__name__)


class MultiprocessWSGITest(integrated_helpers._IntegratedTestBase):
    _api_version = 'v2'

    def _start_api_service(self):
        # Process will be started in _spawn()
        self.osapi = service.WSGIService("osapi_compute")
        self.auth_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': self.osapi.host, 'port': self.osapi.port,
            'api_version': self._api_version})
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
                launcher = service.process_launcher()
                launcher.launch_service(self.osapi, workers=self.osapi.workers)
                launcher.wait()
            except SystemExit as exc:
                status = exc.code
            except BaseException:
                # We need to be defensive here too
                try:
                    traceback.print_exc()
                except BaseException:
                    LOG.error("Couldn't print traceback")
                status = 2

            # Really exit
            os._exit(status)

        self.pid = pid

        # Wait at most 10 seconds to spawn workers
        cond = lambda: self.workers == len(self._get_workers())
        timeout = 10
        self._wait(cond, timeout)

        workers = self._get_workers()
        self.assertEqual(len(workers), self.workers)
        return workers

    def _wait(self, cond, timeout):
        start = time.time()
        while True:
            if cond():
                break
            if time.time() - start > timeout:
                break
            time.sleep(.1)

    def tearDown(self):
        if self.pid:
            # Make sure all processes are stopped
            os.kill(self.pid, signal.SIGTERM)

            try:
                # Make sure we reap our test process
                self._reap_test()
            except fixtures.TimeoutException:
                # If the child gets stuck or is too slow in existing
                # after receiving the SIGTERM, gracefully handle the
                # timeout exception and try harder to kill it. We need
                # to do this otherwise the child process can hold up
                # the test run
                os.kill(self.pid, signal.SIGKILL)

        super(MultiprocessWSGITest, self).tearDown()

    def _reap_test(self):
        pid, status = os.waitpid(self.pid, 0)
        self.pid = None
        return status

    def _get_workers(self):
        # NOTE(hartsocks): use of ps checks the process table for child pid
        # entries these processes may be ended but not reaped so ps may
        # show processes that are still being cleaned out of the table.
        f = os.popen('ps ax -o pid,ppid,command')
        # Skip ps header
        f.readline()

        processes = [tuple(int(p) for p in l.strip().split()[:2])
                     for l in f.readlines()]
        return [p for p, pp in processes if pp == self.pid]

    def wait_on_process_until_end(self, worker_pid):
        # NOTE: the testing framework itself has a
        # built in test timeout function so a test
        # stuck in an infinite loop will eventually
        # be killed by the test framework.
        LOG.info('waiting on process %r to exit' % worker_pid)

        while True:
            # poll the process until it isn't there to poll
            try:
                os.kill(worker_pid, 0)
                time.sleep(0.1)
            except OSError as err:
                # by watching specifically for errno.ESRCH
                # we guarantee this loop continues until
                # the process table has cleared the pid.
                # Child process table entries hang around
                # for several cycles in case a parent process
                # needs to check their exit state.
                if err.errno == errno.ESRCH:
                    break
        LOG.info('process %r has exited' % worker_pid)

    def test_killed_worker_recover(self):
        start_workers = self._spawn()

        worker_pid = start_workers[0]
        # kill one worker and check if new worker can come up
        LOG.info('pid of first child is %s' % worker_pid)

        # signal child
        os.kill(worker_pid, signal.SIGTERM)

        self.wait_on_process_until_end(worker_pid)

        # Make sure worker pids don't match
        end_workers = self._get_workers()
        LOG.info('workers: %r' % end_workers)
        self.assertNotEqual(start_workers, end_workers)

        # check if api service still works
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')

    def _terminate_with_signal(self, sig):
        self._spawn()

        # check if api service is working
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')

        worker_pids = self._get_workers()

        LOG.info("sent launcher_process pid: %r signal: %r" % (self.pid, sig))
        os.kill(self.pid, sig)

        # did you know the test framework has a timeout of its own?
        # if a test takes too long, the test will be killed.
        for pid in worker_pids:
            self.wait_on_process_until_end(pid)

        workers = self._get_workers()
        self.assertFalse(workers, 'OS processes left %r' % workers)

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


class MultiprocessWSGITestV3(client.TestOpenStackClientV3Mixin,
                             MultiprocessWSGITest):
    _api_version = 'v3'

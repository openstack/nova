# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
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

"""Generic Node base class for all workers that run on hosts."""

import errno
import os
import random
import signal
import sys
import time

import eventlet
import logging as std_logging
from oslo.config import cfg

from nova.openstack.common import eventlet_backdoor
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import threadgroup


rpc = importutils.try_import('nova.openstack.common.rpc')
CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class Launcher(object):
    """Launch one or more services and wait for them to complete."""

    def __init__(self):
        """Initialize the service launcher.

        :returns: None

        """
        self._services = threadgroup.ThreadGroup()
        self.backdoor_port = eventlet_backdoor.initialize_if_enabled()

    @staticmethod
    def run_service(service):
        """Start and wait for a service to finish.

        :param service: service to run and wait for.
        :returns: None

        """
        service.start()
        service.wait()

    def launch_service(self, service):
        """Load and start the given service.

        :param service: The service you would like to start.
        :returns: None

        """
        service.backdoor_port = self.backdoor_port
        self._services.add_thread(self.run_service, service)

    def stop(self):
        """Stop all services which are currently running.

        :returns: None

        """
        self._services.stop()

    def wait(self):
        """Waits until all services have been stopped, and then returns.

        :returns: None

        """
        self._services.wait()


class SignalExit(SystemExit):
    def __init__(self, signo, exccode=1):
        super(SignalExit, self).__init__(exccode)
        self.signo = signo


class ServiceLauncher(Launcher):
    def _handle_signal(self, signo, frame):
        # Allow the process to be killed again and die from natural causes
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        raise SignalExit(signo)

    def wait(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        LOG.debug(_('Full set of CONF:'))
        CONF.log_opt_values(LOG, std_logging.DEBUG)

        status = None
        try:
            super(ServiceLauncher, self).wait()
        except SignalExit as exc:
            signame = {signal.SIGTERM: 'SIGTERM',
                       signal.SIGINT: 'SIGINT'}[exc.signo]
            LOG.info(_('Caught %s, exiting'), signame)
            status = exc.code
        except SystemExit as exc:
            status = exc.code
        finally:
            if rpc:
                rpc.cleanup()
            self.stop()
        return status


class ServiceWrapper(object):
    def __init__(self, service, workers):
        self.service = service
        self.workers = workers
        self.children = set()
        self.forktimes = []


class ProcessLauncher(object):
    def __init__(self):
        self.children = {}
        self.sigcaught = None
        self.running = True
        rfd, self.writepipe = os.pipe()
        self.readpipe = eventlet.greenio.GreenPipe(rfd, 'r')

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signo, frame):
        self.sigcaught = signo
        self.running = False

        # Allow the process to be killed again and die from natural causes
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    def _pipe_watcher(self):
        # This will block until the write end is closed when the parent
        # dies unexpectedly
        self.readpipe.read()

        LOG.info(_('Parent process has died unexpectedly, exiting'))

        sys.exit(1)

    def _child_process(self, service):
        # Setup child signal handlers differently
        def _sigterm(*args):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            raise SignalExit(signal.SIGTERM)

        signal.signal(signal.SIGTERM, _sigterm)
        # Block SIGINT and let the parent send us a SIGTERM
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        eventlet.hubs.use_hub()

        # Close write to ensure only parent has it open
        os.close(self.writepipe)
        # Create greenthread to watch for parent to close pipe
        eventlet.spawn_n(self._pipe_watcher)

        # Reseed random number generator
        random.seed()

        launcher = Launcher()
        launcher.run_service(service)

    def _start_child(self, wrap):
        if len(wrap.forktimes) > wrap.workers:
            # Limit ourselves to one process a second (over the period of
            # number of workers * 1 second). This will allow workers to
            # start up quickly but ensure we don't fork off children that
            # die instantly too quickly.
            if time.time() - wrap.forktimes[0] < wrap.workers:
                LOG.info(_('Forking too fast, sleeping'))
                time.sleep(1)

            wrap.forktimes.pop(0)

        wrap.forktimes.append(time.time())

        pid = os.fork()
        if pid == 0:
            # NOTE(johannes): All exceptions are caught to ensure this
            # doesn't fallback into the loop spawning children. It would
            # be bad for a child to spawn more children.
            status = 0
            try:
                self._child_process(wrap.service)
            except SignalExit as exc:
                signame = {signal.SIGTERM: 'SIGTERM',
                           signal.SIGINT: 'SIGINT'}[exc.signo]
                LOG.info(_('Caught %s, exiting'), signame)
                status = exc.code
            except SystemExit as exc:
                status = exc.code
            except BaseException:
                LOG.exception(_('Unhandled exception'))
                status = 2
            finally:
                wrap.service.stop()

            os._exit(status)

        LOG.info(_('Started child %d'), pid)

        wrap.children.add(pid)
        self.children[pid] = wrap

        return pid

    def launch_service(self, service, workers=1):
        wrap = ServiceWrapper(service, workers)

        LOG.info(_('Starting %d workers'), wrap.workers)
        while self.running and len(wrap.children) < wrap.workers:
            self._start_child(wrap)

    def _wait_child(self):
        try:
            # Don't block if no child processes have exited
            pid, status = os.waitpid(0, os.WNOHANG)
            if not pid:
                return None
        except OSError as exc:
            if exc.errno not in (errno.EINTR, errno.ECHILD):
                raise
            return None

        if os.WIFSIGNALED(status):
            sig = os.WTERMSIG(status)
            LOG.info(_('Child %(pid)d killed by signal %(sig)d'),
                     dict(pid=pid, sig=sig))
        else:
            code = os.WEXITSTATUS(status)
            LOG.info(_('Child %(pid)s exited with status %(code)d'),
                     dict(pid=pid, code=code))

        if pid not in self.children:
            LOG.warning(_('pid %d not in child list'), pid)
            return None

        wrap = self.children.pop(pid)
        wrap.children.remove(pid)
        return wrap

    def wait(self):
        """Loop waiting on children to die and respawning as necessary"""

        LOG.debug(_('Full set of CONF:'))
        CONF.log_opt_values(LOG, std_logging.DEBUG)

        while self.running:
            wrap = self._wait_child()
            if not wrap:
                # Yield to other threads if no children have exited
                # Sleep for a short time to avoid excessive CPU usage
                # (see bug #1095346)
                eventlet.greenthread.sleep(.01)
                continue

            while self.running and len(wrap.children) < wrap.workers:
                self._start_child(wrap)

        if self.sigcaught:
            signame = {signal.SIGTERM: 'SIGTERM',
                       signal.SIGINT: 'SIGINT'}[self.sigcaught]
            LOG.info(_('Caught %s, stopping children'), signame)

        for pid in self.children:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    raise

        # Wait for children to die
        if self.children:
            LOG.info(_('Waiting on %d children to exit'), len(self.children))
            while self.children:
                self._wait_child()


class Service(object):
    """Service object for binaries running on hosts."""

    def __init__(self, threads=1000):
        self.tg = threadgroup.ThreadGroup(threads)

    def start(self):
        pass

    def stop(self):
        self.tg.stop()

    def wait(self):
        self.tg.wait()


def launch(service, workers=None):
    if workers:
        launcher = ProcessLauncher()
        launcher.launch_service(service, workers=workers)
    else:
        launcher = ServiceLauncher()
        launcher.launch_service(service)
    return launcher

# -*- coding: utf-8 -*-

# daemon/runner.py
# Part of python-daemon, an implementation of PEP 3143.
#
# Copyright © 2009–2010 Ben Finney <ben+python@benfinney.id.au>
# Copyright © 2007–2008 Robert Niederreiter, Jens Klein
# Copyright © 2003 Clark Evans
# Copyright © 2002 Noah Spurrier
# Copyright © 2001 Jürgen Hermann
#
# This is free software: you may copy, modify, and/or distribute this work
# under the terms of the Python Software Foundation License, version 2 or
# later as published by the Python Software Foundation.
# No warranty expressed or implied. See the file LICENSE.PSF-2 for details.

""" Daemon runner library.
    """

import sys
import os
import signal
import errno

import pidlockfile

from daemon import DaemonContext


class DaemonRunnerError(Exception):
    """ Abstract base class for errors from DaemonRunner. """

class DaemonRunnerInvalidActionError(ValueError, DaemonRunnerError):
    """ Raised when specified action for DaemonRunner is invalid. """

class DaemonRunnerStartFailureError(RuntimeError, DaemonRunnerError):
    """ Raised when failure starting DaemonRunner. """

class DaemonRunnerStopFailureError(RuntimeError, DaemonRunnerError):
    """ Raised when failure stopping DaemonRunner. """


class DaemonRunner(object):
    """ Controller for a callable running in a separate background process.

        The first command-line argument is the action to take:

        * 'start': Become a daemon and call `app.run()`.
        * 'stop': Exit the daemon process specified in the PID file.
        * 'restart': Stop, then start.

        """

    start_message = "started with pid %(pid)d"

    def __init__(self, app):
        """ Set up the parameters of a new runner.

            The `app` argument must have the following attributes:

            * `stdin_path`, `stdout_path`, `stderr_path`: Filesystem
              paths to open and replace the existing `sys.stdin`,
              `sys.stdout`, `sys.stderr`.

            * `pidfile_path`: Absolute filesystem path to a file that
              will be used as the PID file for the daemon. If
              ``None``, no PID file will be used.

            * `pidfile_timeout`: Used as the default acquisition
              timeout value supplied to the runner's PID lock file.

            * `run`: Callable that will be invoked when the daemon is
              started.
            
            """
        self.parse_args()
        self.app = app
        self.daemon_context = DaemonContext()
        self.daemon_context.stdin = open(app.stdin_path, 'r')
        self.daemon_context.stdout = open(app.stdout_path, 'w+')
        self.daemon_context.stderr = open(
            app.stderr_path, 'w+', buffering=0)

        self.pidfile = None
        if app.pidfile_path is not None:
            self.pidfile = make_pidlockfile(
                app.pidfile_path, app.pidfile_timeout)
        self.daemon_context.pidfile = self.pidfile

    def _usage_exit(self, argv):
        """ Emit a usage message, then exit.
            """
        progname = os.path.basename(argv[0])
        usage_exit_code = 2
        action_usage = "|".join(self.action_funcs.keys())
        message = "usage: %(progname)s %(action_usage)s" % vars()
        emit_message(message)
        sys.exit(usage_exit_code)

    def parse_args(self, argv=None):
        """ Parse command-line arguments.
            """
        if argv is None:
            argv = sys.argv

        min_args = 2
        if len(argv) < min_args:
            self._usage_exit(argv)

        self.action = argv[1]
        if self.action not in self.action_funcs:
            self._usage_exit(argv)

    def _start(self):
        """ Open the daemon context and run the application.
            """
        if is_pidfile_stale(self.pidfile):
            self.pidfile.break_lock()

        try:
            self.daemon_context.open()
        except pidlockfile.AlreadyLocked:
            pidfile_path = self.pidfile.path
            raise DaemonRunnerStartFailureError(
                "PID file %(pidfile_path)r already locked" % vars())

        pid = os.getpid()
        message = self.start_message % vars()
        emit_message(message)

        self.app.run()

    def _terminate_daemon_process(self):
        """ Terminate the daemon process specified in the current PID file.
            """
        pid = self.pidfile.read_pid()
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError, exc:
            raise DaemonRunnerStopFailureError(
                "Failed to terminate %(pid)d: %(exc)s" % vars())

    def _stop(self):
        """ Exit the daemon process specified in the current PID file.
            """
        if not self.pidfile.is_locked():
            pidfile_path = self.pidfile.path
            raise DaemonRunnerStopFailureError(
                "PID file %(pidfile_path)r not locked" % vars())

        if is_pidfile_stale(self.pidfile):
            self.pidfile.break_lock()
        else:
            self._terminate_daemon_process()

    def _restart(self):
        """ Stop, then start.
            """
        self._stop()
        self._start()

    action_funcs = {
        'start': _start,
        'stop': _stop,
        'restart': _restart,
        }

    def _get_action_func(self):
        """ Return the function for the specified action.

            Raises ``DaemonRunnerInvalidActionError`` if the action is
            unknown.

            """
        try:
            func = self.action_funcs[self.action]
        except KeyError:
            raise DaemonRunnerInvalidActionError(
                "Unknown action: %(action)r" % vars(self))
        return func

    def do_action(self):
        """ Perform the requested action.
            """
        func = self._get_action_func()
        func(self)


def emit_message(message, stream=None):
    """ Emit a message to the specified stream (default `sys.stderr`). """
    if stream is None:
        stream = sys.stderr
    stream.write("%(message)s\n" % vars())
    stream.flush()


def make_pidlockfile(path, acquire_timeout):
    """ Make a PIDLockFile instance with the given filesystem path. """
    if not isinstance(path, basestring):
        error = ValueError("Not a filesystem path: %(path)r" % vars())
        raise error
    if not os.path.isabs(path):
        error = ValueError("Not an absolute path: %(path)r" % vars())
        raise error
    lockfile = pidlockfile.TimeoutPIDLockFile(path, acquire_timeout)

    return lockfile


def is_pidfile_stale(pidfile):
    """ Determine whether a PID file is stale.

        Return ``True`` (“stale”) if the contents of the PID file are
        valid but do not match the PID of a currently-running process;
        otherwise return ``False``.

        """
    result = False

    pidfile_pid = pidfile.read_pid()
    if pidfile_pid is not None:
        try:
            os.kill(pidfile_pid, signal.SIG_DFL)
        except OSError, exc:
            if exc.errno == errno.ESRCH:
                # The specified PID does not exist
                result = True

    return result

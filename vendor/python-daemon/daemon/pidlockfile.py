# -*- coding: utf-8 -*-

# daemon/pidlockfile.py
# Part of python-daemon, an implementation of PEP 3143.
#
# Copyright © 2008–2010 Ben Finney <ben+python@benfinney.id.au>
#
# This is free software: you may copy, modify, and/or distribute this work
# under the terms of the Python Software Foundation License, version 2 or
# later as published by the Python Software Foundation.
# No warranty expressed or implied. See the file LICENSE.PSF-2 for details.


""" Lockfile behaviour implemented via Unix PID files.
    """

import os
import errno

from lockfile import (
    FileLock,
    AlreadyLocked, LockFailed,
    NotLocked, NotMyLock,
    )


class PIDFileError(Exception):
    """ Abstract base class for errors specific to PID files. """

class PIDFileParseError(ValueError, PIDFileError):
    """ Raised when parsing contents of PID file fails. """


class PIDLockFile(FileLock, object):
    """ Lockfile implemented as a Unix PID file.

        The PID file is named by the attribute `path`. When locked,
        the file will be created with a single line of text,
        containing the process ID (PID) of the process that acquired
        the lock.

        The lock is acquired and maintained as per `LinkFileLock`.

        """

    def read_pid(self):
        """ Get the PID from the lock file.
            """
        result = read_pid_from_pidfile(self.path)
        return result

    def acquire(self, *args, **kwargs):
        """ Acquire the lock.

            Locks the PID file then creates the PID file for this
            lock. The `timeout` parameter is used as for the
            `LinkFileLock` class.

            """
        super(PIDLockFile, self).acquire(*args, **kwargs)
        try:
            write_pid_to_pidfile(self.path)
        except OSError, exc:
            error = LockFailed("%(exc)s" % vars())
            raise error

    def release(self):
        """ Release the lock.

            Removes the PID file then releases the lock, or raises an
            error if the current process does not hold the lock.

            """
        if self.i_am_locking():
            remove_existing_pidfile(self.path)
        super(PIDLockFile, self).release()

    def break_lock(self):
        """ Break an existing lock.

            If the lock is held, breaks the lock and removes the PID
            file.

            """
        super(PIDLockFile, self).break_lock()
        remove_existing_pidfile(self.path)


class TimeoutPIDLockFile(PIDLockFile):
    """ Lockfile with default timeout, implemented as a Unix PID file.

        This uses the ``PIDLockFile`` implementation, with the
        following changes:

        * The `acquire_timeout` parameter to the initialiser will be
          used as the default `timeout` parameter for the `acquire`
          method.

        """

    def __init__(self, path, acquire_timeout=None, *args, **kwargs):
        """ Set up the parameters of a DaemonRunnerLock. """
        self.acquire_timeout = acquire_timeout
        super(TimeoutPIDLockFile, self).__init__(path, *args, **kwargs)

    def acquire(self, timeout=None, *args, **kwargs):
        """ Acquire the lock. """
        if timeout is None:
            timeout = self.acquire_timeout
        super(TimeoutPIDLockFile, self).acquire(timeout, *args, **kwargs)


def read_pid_from_pidfile(pidfile_path):
    """ Read the PID recorded in the named PID file.

        Read and return the numeric PID recorded as text in the named
        PID file. If the PID file does not exist, return ``None``. If
        the content is not a valid PID, raise ``PIDFileParseError``.

        """
    pid = None
    pidfile = None
    try:
        pidfile = open(pidfile_path, 'r')
    except IOError, exc:
        if exc.errno == errno.ENOENT:
            pass
        else:
            raise

    if pidfile:
        # According to the FHS 2.3 section on PID files in ‘/var/run’:
        #
        #   The file must consist of the process identifier in
        #   ASCII-encoded decimal, followed by a newline character. …
        #
        #   Programs that read PID files should be somewhat flexible
        #   in what they accept; i.e., they should ignore extra
        #   whitespace, leading zeroes, absence of the trailing
        #   newline, or additional lines in the PID file.

        line = pidfile.readline().strip()
        try:
            pid = int(line)
        except ValueError:
            raise PIDFileParseError(
                "PID file %(pidfile_path)r contents invalid" % vars())
        pidfile.close()

    return pid


def write_pid_to_pidfile(pidfile_path):
    """ Write the PID in the named PID file.

        Get the numeric process ID (“PID”) of the current process
        and write it to the named file as a line of text.

        """
    open_flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    open_mode = (
        ((os.R_OK | os.W_OK) << 6) |
        ((os.R_OK) << 3) |
        ((os.R_OK)))
    pidfile_fd = os.open(pidfile_path, open_flags, open_mode)
    pidfile = os.fdopen(pidfile_fd, 'w')

    # According to the FHS 2.3 section on PID files in ‘/var/run’:
    #
    #   The file must consist of the process identifier in
    #   ASCII-encoded decimal, followed by a newline character. For
    #   example, if crond was process number 25, /var/run/crond.pid
    #   would contain three characters: two, five, and newline.

    pid = os.getpid()
    line = "%(pid)d\n" % vars()
    pidfile.write(line)
    pidfile.close()


def remove_existing_pidfile(pidfile_path):
    """ Remove the named PID file if it exists.

        Remove the named PID file. Ignore the condition if the file
        does not exist, since that only means we are already in the
        desired state.

        """
    try:
        os.remove(pidfile_path)
    except OSError, exc:
        if exc.errno == errno.ENOENT:
            pass
        else:
            raise

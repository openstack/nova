# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation.
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


import errno
import functools
import os
import shutil
import tempfile
import time
import weakref

from eventlet import semaphore
from oslo.config import cfg

from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import local
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


util_opts = [
    cfg.BoolOpt('disable_process_locking', default=False,
                help='Whether to disable inter-process locks'),
    cfg.StrOpt('lock_path',
               help=('Directory to use for lock files. Default to a '
                     'temp directory'))
]


CONF = cfg.CONF
CONF.register_opts(util_opts)


def set_defaults(lock_path):
    cfg.set_defaults(util_opts, lock_path=lock_path)


class _InterProcessLock(object):
    """Lock implementation which allows multiple locks, working around
    issues like bugs.debian.org/cgi-bin/bugreport.cgi?bug=632857 and does
    not require any cleanup. Since the lock is always held on a file
    descriptor rather than outside of the process, the lock gets dropped
    automatically if the process crashes, even if __exit__ is not executed.

    There are no guarantees regarding usage by multiple green threads in a
    single process here. This lock works only between processes. Exclusive
    access between local threads should be achieved using the semaphores
    in the @synchronized decorator.

    Note these locks are released when the descriptor is closed, so it's not
    safe to close the file descriptor while another green thread holds the
    lock. Just opening and closing the lock file can break synchronisation,
    so lock files must be accessed only using this abstraction.
    """

    def __init__(self, name):
        self.lockfile = None
        self.fname = name

    def __enter__(self):
        self.lockfile = open(self.fname, 'w')

        while True:
            try:
                # Using non-blocking locks since green threads are not
                # patched to deal with blocking locking calls.
                # Also upon reading the MSDN docs for locking(), it seems
                # to have a laughable 10 attempts "blocking" mechanism.
                self.trylock()
                return self
            except IOError as e:
                if e.errno in (errno.EACCES, errno.EAGAIN):
                    # external locks synchronise things like iptables
                    # updates - give it some time to prevent busy spinning
                    time.sleep(0.01)
                else:
                    raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.unlock()
            self.lockfile.close()
        except IOError:
            LOG.exception(_("Could not release the acquired lock `%s`"),
                          self.fname)

    def trylock(self):
        raise NotImplementedError()

    def unlock(self):
        raise NotImplementedError()


class _WindowsLock(_InterProcessLock):
    def trylock(self):
        msvcrt.locking(self.lockfile.fileno(), msvcrt.LK_NBLCK, 1)

    def unlock(self):
        msvcrt.locking(self.lockfile.fileno(), msvcrt.LK_UNLCK, 1)


class _PosixLock(_InterProcessLock):
    def trylock(self):
        fcntl.lockf(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(self):
        fcntl.lockf(self.lockfile, fcntl.LOCK_UN)


if os.name == 'nt':
    import msvcrt
    InterProcessLock = _WindowsLock
else:
    import fcntl
    InterProcessLock = _PosixLock

_semaphores = weakref.WeakValueDictionary()


def synchronized(name, lock_file_prefix, external=False, lock_path=None):
    """Synchronization decorator.

    Decorating a method like so::

        @synchronized('mylock')
        def foo(self, *args):
           ...

    ensures that only one thread will execute the foo method at a time.

    Different methods can share the same lock::

        @synchronized('mylock')
        def foo(self, *args):
           ...

        @synchronized('mylock')
        def bar(self, *args):
           ...

    This way only one of either foo or bar can be executing at a time.

    The lock_file_prefix argument is used to provide lock files on disk with a
    meaningful prefix. The prefix should end with a hyphen ('-') if specified.

    The external keyword argument denotes whether this lock should work across
    multiple processes. This means that if two different workers both run a
    a method decorated with @synchronized('mylock', external=True), only one
    of them will execute at a time.

    The lock_path keyword argument is used to specify a special location for
    external lock files to live. If nothing is set, then CONF.lock_path is
    used as a default.
    """

    def wrap(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            # NOTE(soren): If we ever go natively threaded, this will be racy.
            #              See http://stackoverflow.com/questions/5390569/dyn
            #              amically-allocating-and-destroying-mutexes
            sem = _semaphores.get(name, semaphore.Semaphore())
            if name not in _semaphores:
                # this check is not racy - we're already holding ref locally
                # so GC won't remove the item and there was no IO switch
                # (only valid in greenthreads)
                _semaphores[name] = sem

            with sem:
                LOG.debug(_('Got semaphore "%(lock)s" for method '
                            '"%(method)s"...'), {'lock': name,
                                                 'method': f.__name__})

                # NOTE(mikal): I know this looks odd
                if not hasattr(local.strong_store, 'locks_held'):
                    local.strong_store.locks_held = []
                local.strong_store.locks_held.append(name)

                try:
                    if external and not CONF.disable_process_locking:
                        LOG.debug(_('Attempting to grab file lock "%(lock)s" '
                                    'for method "%(method)s"...'),
                                  {'lock': name, 'method': f.__name__})
                        cleanup_dir = False

                        # We need a copy of lock_path because it is non-local
                        local_lock_path = lock_path
                        if not local_lock_path:
                            local_lock_path = CONF.lock_path

                        if not local_lock_path:
                            cleanup_dir = True
                            local_lock_path = tempfile.mkdtemp()

                        if not os.path.exists(local_lock_path):
                            fileutils.ensure_tree(local_lock_path)

                        # NOTE(mikal): the lock name cannot contain directory
                        # separators
                        safe_name = name.replace(os.sep, '_')
                        lock_file_name = '%s%s' % (lock_file_prefix, safe_name)
                        lock_file_path = os.path.join(local_lock_path,
                                                      lock_file_name)

                        try:
                            lock = InterProcessLock(lock_file_path)
                            with lock:
                                LOG.debug(_('Got file lock "%(lock)s" at '
                                            '%(path)s for method '
                                            '"%(method)s"...'),
                                          {'lock': name,
                                           'path': lock_file_path,
                                           'method': f.__name__})
                                retval = f(*args, **kwargs)
                        finally:
                            LOG.debug(_('Released file lock "%(lock)s" at '
                                        '%(path)s for method "%(method)s"...'),
                                      {'lock': name,
                                       'path': lock_file_path,
                                       'method': f.__name__})
                            # NOTE(vish): This removes the tempdir if we needed
                            #             to create one. This is used to
                            #             cleanup the locks left behind by unit
                            #             tests.
                            if cleanup_dir:
                                shutil.rmtree(local_lock_path)
                    else:
                        retval = f(*args, **kwargs)

                finally:
                    local.strong_store.locks_held.remove(name)

            return retval
        return inner
    return wrap


def synchronized_with_prefix(lock_file_prefix):
    """Partial object generator for the synchronization decorator.

    Redefine @synchronized in each project like so::

        (in nova/utils.py)
        from nova.openstack.common import lockutils

        synchronized = lockutils.synchronized_with_prefix('nova-')


        (in nova/foo.py)
        from nova import utils

        @utils.synchronized('mylock')
        def bar(self, *args):
           ...

    The lock_file_prefix argument is used to provide lock files on disk with a
    meaningful prefix. The prefix should end with a hyphen ('-') if specified.
    """

    return functools.partial(synchronized, lock_file_prefix=lock_file_prefix)

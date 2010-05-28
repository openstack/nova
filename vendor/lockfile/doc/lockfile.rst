
:mod:`lockfile` --- Platform-independent file locking
=====================================================

.. module:: lockfile
   :synopsis: Platform-independent file locking
.. moduleauthor:: Skip Montanaro <skip@pobox.com>
.. sectionauthor:: Skip Montanaro <skip@pobox.com>


.. note::

   This package is pre-release software.  Between versions 0.8 and 0.9 it
   was changed from a module to a package.  It is quite possible that the
   API and implementation will change again in important ways as people test
   it and provide feedback and bug fixes.  In particular, if the mkdir-based
   locking scheme is sufficient for both Windows and Unix platforms, the
   link-based scheme may be deleted so that only a single locking scheme is
   used, providing cross-platform lockfile cooperation.

.. note::

   The implementation uses the :keyword:`with` statement, both in the
   tests and in the main code, so will only work out-of-the-box with Python
   2.5 or later.  However, the use of the :keyword:`with` statement is
   minimal, so if you apply the patch in the included 2.4.diff file you can
   use it with Python 2.4.  It's possible that it will work in Python 2.3
   with that patch applied as well, though the doctest code relies on APIs
   new in 2.4, so will have to be rewritten somewhat to allow testing on
   2.3.  As they say, patches welcome. ``;-)``

The :mod:`lockfile` package exports a :class:`LockFile` class which provides
a simple API for locking files.  Unlike the Windows :func:`msvcrt.locking`
function, the Unix :func:`fcntl.flock`, :func:`fcntl.lockf` and the
deprecated :mod:`posixfile` module, the API is identical across both Unix
(including Linux and Mac) and Windows platforms.  The lock mechanism relies
on the atomic nature of the :func:`link` (on Unix) and :func:`mkdir` (On
Windows) system calls.  It also contains several lock-method-specific
modules: :mod:`lockfile.linklockfile`, :mod:`lockfile.mkdirlockfile`, and
:mod:`lockfile.sqlitelockfile`, each one exporting a single class.  For
backwards compatibility with versions before 0.9 the :class:`LinkFileLock`,
:class:`MkdirFileLock` and :class:`SQLiteFileLock` objects are exposed as
attributes of the top-level lockfile package, though this use was deprecated
starting with version 0.9 and will be removed in version 1.0.

.. note::

   The current implementation uses :func:`os.link` on Unix, but since that
   function is unavailable on Windows it uses :func:`os.mkdir` there.  At
   this point it's not clear that using the :func:`os.mkdir` method would be
   insufficient on Unix systems.  If it proves to be adequate on Unix then
   the implementation could be simplified and truly cross-platform locking
   would be possible.

.. note::

   The current implementation doesn't provide for shared vs. exclusive
   locks.  It should be possible for multiple reader processes to hold the
   lock at the same time.

The module defines the following exceptions:

.. exception:: Error

   This is the base class for all exceptions raised by the :class:`LockFile`
   class.

.. exception:: LockError

   This is the base class for all exceptions raised when attempting to lock
   a file.

.. exception:: UnlockError

   This is the base class for all exceptions raised when attempting to
   unlock a file.

.. exception:: LockTimeout

   This exception is raised if the :func:`LockFile.acquire` method is
   called with a timeout which expires before an existing lock is released.

.. exception:: AlreadyLocked

   This exception is raised if the :func:`LockFile.acquire` detects a
   file is already locked when in non-blocking mode.

.. exception:: LockFailed

   This exception is raised if the :func:`LockFile.acquire` detects some
   other condition (such as a non-writable directory) which prevents it from
   creating its lock file.

.. exception:: NotLocked

   This exception is raised if the file is not locked when
   :func:`LockFile.release` is called.

.. exception:: NotMyLock

   This exception is raised if the file is locked by another thread or
   process when :func:`LockFile.release` is called.

The following classes are provided:

.. class:: linklockfile.LinkLockFile(path, threaded=True)

   This class uses the :func:`link(2)` system call as the basic lock
   mechanism.  *path* is an object in the file system to be locked.  It need
   not exist, but its directory must exist and be writable at the time the
   :func:`acquire` and :func:`release` methods are called.  *threaded* is
   optional, but when set to :const:`True` locks will be distinguished
   between threads in the same process.

.. class:: mkdirlockfile.MkdirLockFile(path, threaded=True)

   This class uses the :func:`mkdir(2)` system call as the basic lock
   mechanism.  The parameters have the same meaning as for the
   :class:`LinkLockFile` class.

.. class:: sqlitelockfile.SQLiteLockFile(path, threaded=True)

   This class uses the :mod:`sqlite3` module to implement the lock
   mechanism.  The parameters have the same meaning as for the
   :class:`LinkLockFile` class.

.. class:: LockBase(path, threaded=True)

   This is the base class for all concrete implementations and is available
   at the lockfile package level so programmers can implement other locking
   schemes.

By default, the :const:`LockFile` object refers to the
:class:`mkdirlockfile.MkdirLockFile` class on Windows.  On all other
platforms it refers to the :class:`linklockfile.LinkLockFile` class.

When locking a file the :class:`linklockfile.LinkLockFile` class creates a
uniquely named hard link to an empty lock file.  That hard link contains the
hostname, process id, and if locks between threads are distinguished, the
thread identifier.  For example, if you want to lock access to a file named
"README", the lock file is named "README.lock".  With per-thread locks
enabled the hard link is named HOSTNAME-THREADID-PID.  With only per-process
locks enabled the hard link is named HOSTNAME--PID.

When using the :class:`mkdirlockfile.MkdirLockFile` class the lock file is a
directory.  Referring to the example above, README.lock will be a directory
and HOSTNAME-THREADID-PID will be an empty file within that directory.

.. seealso::

   Module :mod:`msvcrt`
      Provides the :func:`locking` function, the standard Windows way of
      locking (parts of) a file.

   Module :mod:`posixfile`
      The deprecated (since Python 1.5) way of locking files on Posix systems.

   Module :mod:`fcntl`
      Provides the current best way to lock files on Unix systems
      (:func:`lockf` and :func:`flock`).

LockFile Objects
----------------

:class:`LockFile` objects support the :term:`context manager` protocol used
by the statement:`with` statement.  The timeout option is not supported when
used in this fashion.  While support for timeouts could be implemented,
there is no support for handling the eventual :exc:`Timeout` exceptions
raised by the :func:`__enter__` method, so you would have to protect the
:keyword:`with` statement with a :keyword:`try` statement.  The resulting
construct would not be any simpler than just using a :keyword:`try`
statement in the first place.

:class:`LockFile` has the following user-visible methods:

.. method:: LockFile.acquire(timeout=None)

   Lock the file associated with the :class:`LockFile` object.  If the
   *timeout* is omitted or :const:`None` the caller will block until the
   file is unlocked by the object currently holding the lock.  If the
   *timeout* is zero or a negative number the :exc:`AlreadyLocked` exception
   will be raised if the file is currently locked by another process or
   thread.  If the *timeout* is positive, the caller will block for that
   many seconds waiting for the lock to be released.  If the lock is not
   released within that period the :exc:`LockTimeout` exception will be
   raised.

.. method:: LockFile.release()

   Unlock the file associated with the :class:`LockFile` object.  If the
   file is not currently locked, the :exc:`NotLocked` exception is raised.
   If the file is locked by another thread or process the :exc:`NotMyLock`
   exception is raised.

.. method:: is_locked()

   Return the status of the lock on the current file.  If any process or
   thread (including the current one) is locking the file, :const:`True` is
   returned, otherwise :const:`False` is returned.

.. method:: break_lock()

   If the file is currently locked, break it.

.. method:: i_am_locking()

   Returns true if the caller holds the lock.

Examples
--------

This example is the "hello world" for the :mod:`lockfile` package::

    from lockfile import LockFile
    lock = LockFile("/some/file/or/other")
    with lock:
        print lock.path, 'is locked.'

To use this with Python 2.4, you can execute::

    frm lockfile import LockFile
    lock = LockFile("/some/file/or/other")
    lock.acquire()
    print lock.path, 'is locked.'
    lock.release()

If you don't want to wait forever, you might try::	

    from lockfile import LockFile
    lock = LockFile("/some/file/or/other")
    while not lock.i_am_locking():
	try:
	    lock.acquire(timeout=60)    # wait up to 60 seconds
	except LockTimeout:
	    lock.break_lock()
	    lock.acquire()
    print "I locked", lock.path
    lock.release()

Other Libraries
---------------

The idea of implementing advisory locking with a standard API is not new
with :mod:`lockfile`.  There are a number of other libraries available:

* locknix - http://pypi.python.org/pypi/locknix - Unix only
* mx.MiscLockFile - from Marc André Lemburg, part of the mx.Base
  distribution - cross-platform.
* Twisted - http://twistedmatrix.com/trac/browser/trunk/twisted/python/lockfile.py
* zc.lockfile - http://pypi.python.org/pypi/zc.lockfile


Contacting the Author
---------------------

If you encounter any problems with ``lockfile``, would like help or want to
submit a patch, contact me directly: Skip Montanaro (skip@pobox.com).

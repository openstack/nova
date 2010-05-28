import os
import threading
import shutil

import lockfile

class ComplianceTest(object):
    def __init__(self):
        self.saved_class = lockfile.LockFile

    def _testfile(self):
        """Return platform-appropriate file.  Helper for tests."""
        import tempfile
        return os.path.join(tempfile.gettempdir(), 'trash-%s' % os.getpid())

    def setup(self):
        lockfile.LockFile = self.class_to_test

    def teardown(self):
        tf = self._testfile()
        if os.path.isdir(tf):
            shutil.rmtree(tf)
        elif os.path.isfile(tf):
            os.unlink(tf)
        lockfile.LockFile = self.saved_class

    def _test_acquire_helper(self, tbool):
        # As simple as it gets.
        lock = lockfile.LockFile(self._testfile(), threaded=tbool)
        lock.acquire()
        assert lock.is_locked()
        lock.release()
        assert not lock.is_locked()

    def test_acquire_basic_threaded(self):
        self._test_acquire_helper(True)

    def test_acquire_basic_unthreaded(self):
        self._test_acquire_helper(False)

    def _test_acquire_no_timeout_helper(self, tbool):
        # No timeout test
        e1, e2 = threading.Event(), threading.Event()
        t = _in_thread(self._lock_wait_unlock, e1, e2)
        e1.wait()         # wait for thread t to acquire lock
        lock2 = lockfile.LockFile(self._testfile(), threaded=tbool)
        assert lock2.is_locked()
        assert not lock2.i_am_locking()

        try:
            lock2.acquire(timeout=-1)
        except lockfile.AlreadyLocked:
            pass
        else:
            lock2.release()
            raise AssertionError("did not raise AlreadyLocked in"
                                 " thread %s" %
                                 threading.current_thread().get_name())

        e2.set()          # tell thread t to release lock
        t.join()

    def test_acquire_no_timeout_threaded(self):
        self._test_acquire_no_timeout_helper(True)

    def test_acquire_no_timeout_unthreaded(self):
        self._test_acquire_no_timeout_helper(False)

    def _test_acquire_timeout_helper(self, tbool):
        # Timeout test
        e1, e2 = threading.Event(), threading.Event()
        t = _in_thread(self._lock_wait_unlock, e1, e2)
        e1.wait()                # wait for thread t to acquire lock
        lock2 = lockfile.LockFile(self._testfile(), threaded=tbool)
        assert lock2.is_locked()
        try:
            lock2.acquire(timeout=0.1)
        except lockfile.LockTimeout:
            pass
        else:
            lock2.release()
            raise AssertionError("did not raise LockTimeout in thread %s" %
                                 threading.current_thread().get_name())

        e2.set()
        t.join()

    def test_acquire_timeout_threaded(self):
        self._test_acquire_timeout_helper(True)

    def test_acquire_timeout_unthreaded(self):
        self._test_acquire_timeout_helper(False)

    def _test_release_basic_helper(self, tbool):
        lock = lockfile.LockFile(self._testfile(), threaded=tbool)
        lock.acquire()
        assert lock.is_locked()
        lock.release()
        assert not lock.is_locked()
        assert not lock.i_am_locking()
        try:
            lock.release()
        except lockfile.NotLocked:
            pass
        except lockfile.NotMyLock:
            raise AssertionError('unexpected exception: %s' %
                                 lockfile.NotMyLock)
        else:
            raise AssertionError('erroneously unlocked file')

    def test_release_basic_threaded(self):
        self._test_release_basic_helper(True)

    def test_release_basic_unthreaded(self):
        self._test_release_basic_helper(False)

    def _test_release_from_thread_helper(self, tbool):
        e1, e2 = threading.Event(), threading.Event()
        t = _in_thread(self._lock_wait_unlock, e1, e2)
        e1.wait()
        lock2 = lockfile.LockFile(self._testfile(), threaded=tbool)
        assert lock2.is_locked()
        assert not lock2.i_am_locking()
        try:
            lock2.release()
        except lockfile.NotMyLock:
            pass
        else:
            raise AssertionError('erroneously unlocked a file locked'
                                 ' by another thread.')
        e2.set()
        t.join()

    def test_release_from_thread_threaded(self):
        self._test_release_from_thread_helper(True)

    def test_release_from_thread_unthreaded(self):
        self._test_release_from_thread_helper(False)

    def _test_is_locked_helper(self, tbool):
        lock = lockfile.LockFile(self._testfile(), threaded=tbool)
        lock.acquire()
        assert lock.is_locked()
        lock.release()
        assert not lock.is_locked()

    def test_is_locked_threaded(self):
        self._test_is_locked_helper(True)

    def test_is_locked_unthreaded(self):
        self._test_is_locked_helper(False)

    def test_i_am_locking(self):
        lock1 = lockfile.LockFile(self._testfile(), threaded=False)
        lock1.acquire()
        try:
            assert lock1.is_locked()
            lock2 = lockfile.LockFile(self._testfile())
            try:
                assert lock1.i_am_locking()
                assert not lock2.i_am_locking()
                try:
                    lock2.acquire(timeout=2)
                except lockfile.LockTimeout:
                    lock2.break_lock()
                    assert not lock2.is_locked()
                    assert not lock1.is_locked()
                    lock2.acquire()
                else:
                    raise AssertionError('expected LockTimeout...')
                assert not lock1.i_am_locking()
                assert lock2.i_am_locking()
            finally:
                if lock2.i_am_locking():
                    lock2.release()
        finally:
            if lock1.i_am_locking():
                lock1.release()

    def _test_break_lock_helper(self, tbool):
        lock = lockfile.LockFile(self._testfile(), threaded=tbool)
        lock.acquire()
        assert lock.is_locked()
        lock2 = lockfile.LockFile(self._testfile(), threaded=tbool)
        assert lock2.is_locked()
        lock2.break_lock()
        assert not lock2.is_locked()
        try:
            lock.release()
        except lockfile.NotLocked:
            pass
        else:
            raise AssertionError('break lock failed')

    def test_break_lock_threaded(self):
        self._test_break_lock_helper(True)

    def test_break_lock_unthreaded(self):
        self._test_break_lock_helper(False)

    def _lock_wait_unlock(self, event1, event2):
        """Lock from another thread.  Helper for tests."""
        l = lockfile.LockFile(self._testfile())
        l.acquire()
        try:
            event1.set()  # we're in,
            event2.wait() # wait for boss's permission to leave
        finally:
            l.release()

    def test_enter(self):
        lock = lockfile.LockFile(self._testfile())
        lock.acquire()
        try:
            assert lock.is_locked(), "Not locked after acquire!"
        finally:
            lock.release()
        assert not lock.is_locked(), "still locked after release!"

def _in_thread(func, *args, **kwargs):
    """Execute func(*args, **kwargs) after dt seconds. Helper for tests."""
    def _f():
        func(*args, **kwargs)
    t = threading.Thread(target=_f, name='/*/*')
    t.setDaemon(True)
    t.start()
    return t


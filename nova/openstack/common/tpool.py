# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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

"""Locking routines that work with eventlet's tpool.

evenetlet's lock implementations are buggy when using tpool and can
cause a deadlock.  This implements locking objects as spin locks that
yield to other threads when they cannot be acquired.
"""

import itertools
import threading
import time

from eventlet import semaphore


class TpoolSafeLock(object):
    def __init__(self):
        self.lock_counter = itertools.count()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self,  t, v, tb):
        self.release()

    def acquire(self, blocking=True):
        while self.lock_counter.next() != 0:
            if not blocking:
                return False
            # Allow another thread to run
            time.sleep(0)
        return True

    def release(self):
        self.lock_counter = itertools.count()


class TpoolSafeSemaphore(object):
    def __init__(self, value=1):
        self.mutex = TpoolSafeLock()
        self.counter = value
        self.num_blocking = 0

    def acquire(self, blocking=True):
        self.mutex.acquire()
        if self.counter > 0:
            self.counter -= 1
            self.mutex.release()
            return True
        if not blocking:
            self.mutex.release()
            return False
        self.num_blocking += 1
        self.mutex.release()
        time.sleep(0)
        self.mutex.acquire()
        while self.counter == 0:
            self.mutex.release()
            time.sleep(0)
            self.mutex.acquire()
        self.num_blocking -= 1
        self.counter -= 1
        self.mutex.release()

    def locked(self):
        return self.counter == 0

    @property
    def balance(self):
        self.mutex.acquire()
        result = self.counter - self.num_blocking
        self.mutex.release()
        return result

    def release(self):
        self.mutex.acquire()
        self.counter += 1
        self.mutex.release()

    def bounded(self):
        return False


def patch():
    threading.Lock = TpoolSafeLock
    semaphore.Semaphore = TpoolSafeSemaphore

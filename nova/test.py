# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Base classes for our unit tests.

Allows overriding of flags for use of fakes, and some black magic for
inline callbacks.

"""

import functools
import os
import shutil
import uuid
import unittest

import mox
import stubout
from eventlet import greenthread

from nova import fakerabbit
from nova import flags
from nova import rpc
from nova import utils
from nova import service
from nova import wsgi
from nova.virt import fake


FLAGS = flags.FLAGS
flags.DEFINE_string('sqlite_clean_db', 'clean.sqlite',
                    'File name of clean sqlite db')
flags.DEFINE_bool('fake_tests', True,
                  'should we use everything for testing')


def skip_if_fake(func):
    """Decorator that skips a test if running in fake mode."""
    def _skipper(*args, **kw):
        """Wrapped skipper function."""
        if FLAGS.fake_tests:
            raise unittest.SkipTest('Test cannot be run in fake mode')
        else:
            return func(*args, **kw)
    return _skipper


class TestCase(unittest.TestCase):
    """Test case base class for all unit tests."""

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = utils.utcnow()
        shutil.copyfile(os.path.join(FLAGS.state_path, FLAGS.sqlite_clean_db),
                        os.path.join(FLAGS.state_path, FLAGS.sqlite_db))

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flag_overrides = {}
        self.injected = []
        self._services = []
        self._monkey_patch_attach()
        self._monkey_patch_wsgi()
        self._original_flags = FLAGS.FlagValuesDict()
        rpc.ConnectionPool = rpc.Pool(max_size=FLAGS.rpc_conn_pool_size)

    def tearDown(self):
        """Runs after each test method to tear down test environment."""
        try:
            self.mox.UnsetStubs()
            self.stubs.UnsetAll()
            self.stubs.SmartUnsetAll()
            self.mox.VerifyAll()
            super(TestCase, self).tearDown()
        finally:
            # Clean out fake_rabbit's queue if we used it
            if FLAGS.fake_rabbit:
                fakerabbit.reset_all()

            if FLAGS.connection_type == 'fake':
                if hasattr(fake.FakeConnection, '_instance'):
                    del fake.FakeConnection._instance

            # Reset any overriden flags
            self.reset_flags()

            # Reset our monkey-patches
            rpc.Consumer.attach_to_eventlet = self.original_attach
            wsgi.Server.start = self.original_start

            # Stop any timers
            for x in self.injected:
                try:
                    x.stop()
                except AssertionError:
                    pass

            # Kill any services
            for x in self._services:
                try:
                    x.kill()
                except Exception:
                    pass

    def flags(self, **kw):
        """Override flag variables for a test."""
        for k, v in kw.iteritems():
            if k in self.flag_overrides:
                self.reset_flags()
                raise Exception(
                        'trying to override already overriden flag: %s' % k)
            self.flag_overrides[k] = getattr(FLAGS, k)
            setattr(FLAGS, k, v)

    def reset_flags(self):
        """Resets all flag variables for the test.

        Runs after each test.

        """
        FLAGS.Reset()
        for k, v in self._original_flags.iteritems():
            setattr(FLAGS, k, v)

    def start_service(self, name, host=None, **kwargs):
        host = host and host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        svc = service.Service.create(**kwargs)
        svc.start()
        self._services.append(svc)
        return svc

    def _monkey_patch_attach(self):
        self.original_attach = rpc.Consumer.attach_to_eventlet

        def _wrapped(inner_self):
            rv = self.original_attach(inner_self)
            self.injected.append(rv)
            return rv

        _wrapped.func_name = self.original_attach.func_name
        rpc.Consumer.attach_to_eventlet = _wrapped

    def _monkey_patch_wsgi(self):
        """Allow us to kill servers spawned by wsgi.Server."""
        self.original_start = wsgi.Server.start

        @functools.wraps(self.original_start)
        def _wrapped_start(inner_self, *args, **kwargs):
            original_spawn_n = inner_self.pool.spawn_n

            @functools.wraps(original_spawn_n)
            def _wrapped_spawn_n(*args, **kwargs):
                rv = greenthread.spawn(*args, **kwargs)
                self._services.append(rv)

            inner_self.pool.spawn_n = _wrapped_spawn_n
            self.original_start(inner_self, *args, **kwargs)
            inner_self.pool.spawn_n = original_spawn_n

        _wrapped_start.func_name = self.original_start.func_name
        wsgi.Server.start = _wrapped_start

    # Useful assertions
    def assertDictMatch(self, d1, d2):
        """Assert two dicts are equivalent.

        This is a 'deep' match in the sense that it handles nested
        dictionaries appropriately.

        NOTE:

            If you don't care (or don't know) a given value, you can specify
            the string DONTCARE as the value. This will cause that dict-item
            to be skipped.

        """
        def raise_assertion(msg):
            d1str = str(d1)
            d2str = str(d2)
            base_msg = ('Dictionaries do not match. %(msg)s d1: %(d1str)s '
                        'd2: %(d2str)s' % locals())
            raise AssertionError(base_msg)

        d1keys = set(d1.keys())
        d2keys = set(d2.keys())
        if d1keys != d2keys:
            d1only = d1keys - d2keys
            d2only = d2keys - d1keys
            raise_assertion('Keys in d1 and not d2: %(d1only)s. '
                            'Keys in d2 and not d1: %(d2only)s' % locals())

        for key in d1keys:
            d1value = d1[key]
            d2value = d2[key]
            if hasattr(d1value, 'keys') and hasattr(d2value, 'keys'):
                self.assertDictMatch(d1value, d2value)
            elif 'DONTCARE' in (d1value, d2value):
                continue
            elif d1value != d2value:
                raise_assertion("d1['%(key)s']=%(d1value)s != "
                                "d2['%(key)s']=%(d2value)s" % locals())

    def assertDictListMatch(self, L1, L2):
        """Assert a list of dicts are equivalent."""
        def raise_assertion(msg):
            L1str = str(L1)
            L2str = str(L2)
            base_msg = ('List of dictionaries do not match: %(msg)s '
                        'L1: %(L1str)s L2: %(L2str)s' % locals())
            raise AssertionError(base_msg)

        L1count = len(L1)
        L2count = len(L2)
        if L1count != L2count:
            raise_assertion('Length mismatch: len(L1)=%(L1count)d != '
                            'len(L2)=%(L2count)d' % locals())

        for d1, d2 in zip(L1, L2):
            self.assertDictMatch(d1, d2)

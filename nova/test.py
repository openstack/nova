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

"""
Base classes for our unit tests.
Allows overriding of flags for use of fakes,
and some black magic for inline callbacks.
"""

import sys
import time

import mox
import stubout
from tornado import ioloop
from twisted.internet import defer
from twisted.trial import unittest

from nova import fakerabbit
from nova import flags


FLAGS = flags.FLAGS
flags.DEFINE_bool('fake_tests', True,
                  'should we use everything for testing')

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base

engine = create_engine('sqlite:///:memory:', echo=True)
Base = declarative_base()
Base.metadata.create_all(engine)

def skip_if_fake(func):
    """Decorator that skips a test if running in fake mode"""
    def _skipper(*args, **kw):
        """Wrapped skipper function"""
        if FLAGS.fake_tests:
            raise unittest.SkipTest('Test cannot be run in fake mode')
        else:
            return func(*args, **kw)
    return _skipper


class TrialTestCase(unittest.TestCase):
    """Test case base class for all unit tests"""
    def setUp(self): # pylint: disable-msg=C0103
        """Run before each test method to initialize test environment"""
        super(TrialTestCase, self).setUp()

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flag_overrides = {}

    def tearDown(self): # pylint: disable-msg=C0103
        """Runs after each test method to finalize/tear down test environment"""
        super(TrialTestCase, self).tearDown()
        self.reset_flags()
        self.mox.UnsetStubs()
        self.stubs.UnsetAll()
        self.stubs.SmartUnsetAll()
        self.mox.VerifyAll()

        if FLAGS.fake_rabbit:
            fakerabbit.reset_all()

    def flags(self, **kw):
        """Override flag variables for a test"""
        for k, v in kw.iteritems():
            if k in self.flag_overrides:
                self.reset_flags()
                raise Exception(
                        'trying to override already overriden flag: %s' % k)
            self.flag_overrides[k] = getattr(FLAGS, k)
            setattr(FLAGS, k, v)

    def reset_flags(self):
        """Resets all flag variables for the test.  Runs after each test"""
        for k, v in self.flag_overrides.iteritems():
            setattr(FLAGS, k, v)


class BaseTestCase(TrialTestCase):
    # TODO(jaypipes): Can this be moved into the TrialTestCase class?
    """Base test case class for all unit tests."""
    def setUp(self): # pylint: disable-msg=C0103
        """Run before each test method to initialize test environment"""
        super(BaseTestCase, self).setUp()
        # TODO(termie): we could possibly keep a more global registry of
        #               the injected listeners... this is fine for now though
        self.injected = []
        self.ioloop = ioloop.IOLoop.instance()

        self._waiting = None
        self._done_waiting = False
        self._timed_out = False

    def tearDown(self):# pylint: disable-msg=C0103
        """Runs after each test method to finalize/tear down test environment"""
        super(BaseTestCase, self).tearDown()
        for x in self.injected:
            x.stop()
        if FLAGS.fake_rabbit:
            fakerabbit.reset_all()

    def _wait_for_test(self, timeout=60):
        """ Push the ioloop along to wait for our test to complete. """
        self._waiting = self.ioloop.add_timeout(time.time() + timeout,
                                                self._timeout)
        def _wait():
            """Wrapped wait function. Called on timeout."""
            if self._timed_out:
                self.fail('test timed out')
                self._done()
            if self._done_waiting:
                self.ioloop.stop()
                return
            # we can use add_callback here but this uses less cpu when testing
            self.ioloop.add_timeout(time.time() + 0.01, _wait)

        self.ioloop.add_callback(_wait)
        self.ioloop.start()

    def _done(self):
        """Callback used for cleaning up deferred test methods."""
        if self._waiting:
            try:
                self.ioloop.remove_timeout(self._waiting)
            except Exception: # pylint: disable-msg=W0703
                # TODO(jaypipes): This produces a pylint warning.  Should
                # we really be catching Exception and then passing here?
                pass
            self._waiting = None
        self._done_waiting = True

    def _maybe_inline_callbacks(self, func):
        """ If we're doing async calls in our tests, wait on them.

        This is probably the most complicated hunk of code we have so far.

        First up, if the function is normal (not async) we just act normal
        and return.

        Async tests will use the "Inline Callbacks" pattern, which means
        you yield Deferreds at every "waiting" step of your code instead
        of making epic callback chains.

        Example (callback chain, ugly):

        d = self.compute.terminate_instance(instance_id) # a Deferred instance
        def _describe(_):
            d_desc = self.compute.describe_instances() # another Deferred instance
            return d_desc
        def _checkDescribe(rv):
            self.assertEqual(rv, [])
        d.addCallback(_describe)
        d.addCallback(_checkDescribe)
        d.addCallback(lambda x: self._done())
        self._wait_for_test()

        Example (inline callbacks! yay!):

        yield self.compute.terminate_instance(instance_id)
        rv = yield self.compute.describe_instances()
        self.assertEqual(rv, [])

        If the test fits the Inline Callbacks pattern we will automatically
        handle calling wait and done.
        """
        # TODO(termie): this can be a wrapper function instead and
        #               and we can make a metaclass so that we don't
        #               have to copy all that "run" code below.
        g = func()
        if not hasattr(g, 'send'):
            self._done()
            return defer.succeed(g)

        inlined = defer.inlineCallbacks(func)
        d = inlined()
        return d

    def _catch_exceptions(self, result, failure):
        """Catches all exceptions and handles keyboard interrupts."""
        exc = (failure.type, failure.value, failure.getTracebackObject())
        if isinstance(failure.value, self.failureException):
            result.addFailure(self, exc)
        elif isinstance(failure.value, KeyboardInterrupt):
            raise
        else:
            result.addError(self, exc)

        self._done()

    def _timeout(self):
        """Helper method which trips the timeouts"""
        self._waiting = False
        self._timed_out = True

    def run(self, result=None):
        """Runs the test case"""

        result.startTest(self)
        test_method = getattr(self, self._testMethodName)
        try:
            try:
                self.setUp()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, sys.exc_info())
                return

            ok = False
            try:
                d = self._maybe_inline_callbacks(test_method)
                d.addErrback(lambda x: self._catch_exceptions(result, x))
                d.addBoth(lambda x: self._done() and x)
                self._wait_for_test()
                ok = True
            except self.failureException:
                result.addFailure(self, sys.exc_info())
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, sys.exc_info())

            try:
                self.tearDown()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, sys.exc_info())
                ok = False
            if ok:
                result.addSuccess(self)
        finally:
            result.stopTest(self)

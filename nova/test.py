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

import logging
import time
import unittest

from nova import vendor
import mox
from tornado import ioloop
from twisted.internet import defer
from twisted.python import failure
from twisted.trial import unittest as trial_unittest
import stubout

from nova import fakerabbit
from nova import flags


FLAGS = flags.FLAGS
flags.DEFINE_bool('fake_tests', True,
                  'should we use everything for testing')


def skip_if_fake(f):
    def _skipper(*args, **kw):
        if FLAGS.fake_tests:
            raise trial_unittest.SkipTest('Test cannot be run in fake mode')
        else:
            return f(*args, **kw)

    _skipper.func_name = f.func_name
    return _skipper


class TrialTestCase(trial_unittest.TestCase):

    def setUp(self):
        super(TrialTestCase, self).setUp()

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flag_overrides = {}

    def tearDown(self):
        super(TrialTestCase, self).tearDown()
        self.reset_flags()
        self.mox.UnsetStubs()
        self.stubs.UnsetAll()
        self.stubs.SmartUnsetAll()
        self.mox.VerifyAll()

        if FLAGS.fake_rabbit:
            fakerabbit.reset_all()

    def flags(self, **kw):
        for k, v in kw.iteritems():
            if k in self.flag_overrides:
                self.reset_flags()
                raise Exception(
                        'trying to override already overriden flag: %s' % k)
            self.flag_overrides[k] = getattr(FLAGS, k)
            setattr(FLAGS, k, v)

    def reset_flags(self):
        for k, v in self.flag_overrides.iteritems():
            setattr(FLAGS, k, v)



class BaseTestCase(TrialTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        # TODO(termie): we could possibly keep a more global registry of
        #               the injected listeners... this is fine for now though
        self.injected = []
        self.ioloop = ioloop.IOLoop.instance()

        self._waiting = None
        self._doneWaiting = False
        self._timedOut = False
        self.set_up()

    def set_up(self):
        pass

    def tear_down(self):
        pass

    def tearDown(self):
        super(BaseTestCase, self).tearDown()
        for x in self.injected:
            x.stop()
        if FLAGS.fake_rabbit:
            fakerabbit.reset_all()
        self.tear_down()

    def _waitForTest(self, timeout=60):
        """ Push the ioloop along to wait for our test to complete. """
        self._waiting = self.ioloop.add_timeout(time.time() + timeout,
                                                self._timeout)
        def _wait():
            if self._timedOut:
                self.fail('test timed out')
                self._done()
            if self._doneWaiting:
                self.ioloop.stop()
                return
            # we can use add_callback here but this uses less cpu when testing
            self.ioloop.add_timeout(time.time() + 0.01, _wait)

        self.ioloop.add_callback(_wait)
        self.ioloop.start()

    def _done(self):
        if self._waiting:
            try:
                self.ioloop.remove_timeout(self._waiting)
            except Exception:
                pass
            self._waiting = None
        self._doneWaiting = True

    def _maybeInlineCallbacks(self, f):
        """ If we're doing async calls in our tests, wait on them.

        This is probably the most complicated hunk of code we have so far.

        First up, if the function is normal (not async) we just act normal
        and return.

        Async tests will use the "Inline Callbacks" pattern, which means
        you yield Deferreds at every "waiting" step of your code instead
        of making epic callback chains.

        Example (callback chain, ugly):

        d = self.node.terminate_instance(instance_id) # a Deferred instance
        def _describe(_):
            d_desc = self.node.describe_instances() # another Deferred instance
            return d_desc
        def _checkDescribe(rv):
            self.assertEqual(rv, [])
        d.addCallback(_describe)
        d.addCallback(_checkDescribe)
        d.addCallback(lambda x: self._done())
        self._waitForTest()

        Example (inline callbacks! yay!):

        yield self.node.terminate_instance(instance_id)
        rv = yield self.node.describe_instances()
        self.assertEqual(rv, [])

        If the test fits the Inline Callbacks pattern we will automatically
        handle calling wait and done.
        """
        # TODO(termie): this can be a wrapper function instead and
        #               and we can make a metaclass so that we don't
        #               have to copy all that "run" code below.
        g = f()
        if not hasattr(g, 'send'):
            self._done()
            return defer.succeed(g)

        inlined = defer.inlineCallbacks(f)
        d = inlined()
        return d

    def _catchExceptions(self, result, failure):
        exc = (failure.type, failure.value, failure.getTracebackObject())
        if isinstance(failure.value, self.failureException):
            result.addFailure(self, exc)
        elif isinstance(failure.value, KeyboardInterrupt):
            raise
        else:
            result.addError(self, exc)

        self._done()

    def _timeout(self):
        self._waiting = False
        self._timedOut = True

    def run(self, result=None):
        if result is None: result = self.defaultTestResult()

        result.startTest(self)
        testMethod = getattr(self, self._testMethodName)
        try:
            try:
                self.setUp()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())
                return

            ok = False
            try:
                d = self._maybeInlineCallbacks(testMethod)
                d.addErrback(lambda x: self._catchExceptions(result, x))
                d.addBoth(lambda x: self._done() and x)
                self._waitForTest()
                ok = True
            except self.failureException:
                result.addFailure(self, self._exc_info())
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())

            try:
                self.tearDown()
            except KeyboardInterrupt:
                raise
            except:
                result.addError(self, self._exc_info())
                ok = False
            if ok: result.addSuccess(self)
        finally:
            result.stopTest(self)

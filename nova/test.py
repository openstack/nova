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

import datetime
import sys
import time
import unittest

import mox
import stubout
from twisted.internet import defer
from twisted.trial import unittest as trial_unittest

from nova import context
from nova import db
from nova import fakerabbit
from nova import flags
from nova import rpc
from nova.network import manager as network_manager


FLAGS = flags.FLAGS
flags.DEFINE_bool('fake_tests', True,
                  'should we use everything for testing')


def skip_if_fake(func):
    """Decorator that skips a test if running in fake mode"""
    def _skipper(*args, **kw):
        """Wrapped skipper function"""
        if FLAGS.fake_tests:
            raise unittest.SkipTest('Test cannot be run in fake mode')
        else:
            return func(*args, **kw)
    return _skipper

class TestCase(unittest.TestCase):
    """Test case base class for all unit tests"""
    def setUp(self):
        """Run before each test method to initialize test environment"""
        super(TestCase, self).setUp()
        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = datetime.datetime.utcnow()
        ctxt = context.get_admin_context()
        if db.network_count(ctxt) != 5:
            network_manager.VlanManager().create_networks(ctxt,
                                                          FLAGS.fixed_range,
                                                          5, 16,
                                                          FLAGS.vlan_start,
                                                          FLAGS.vpn_start)

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flag_overrides = {}
        self.injected = []
        self._monkey_patch_attach()
        self._original_flags = FLAGS.FlagValuesDict()

    def tearDown(self):
        """Runs after each test method to finalize/tear down test
        environment."""
        try:
            self.mox.UnsetStubs()
            self.stubs.UnsetAll()
            self.stubs.SmartUnsetAll()
            self.mox.VerifyAll()
            # NOTE(vish): Clean up any ips associated during the test.
            ctxt = context.get_admin_context()
            db.fixed_ip_disassociate_all_by_timeout(ctxt, FLAGS.host,
                                                    self.start)
            db.network_disassociate_all(ctxt)
            rpc.Consumer.attach_to_eventlet = self.originalAttach
            for x in self.injected:
                try:
                    x.stop()
                except AssertionError:
                    pass

            if FLAGS.fake_rabbit:
                fakerabbit.reset_all()

            db.security_group_destroy_all(ctxt)
            super(TestCase, self).tearDown()
        finally:
            self.reset_flags()

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
        FLAGS.Reset()
        for k, v in self._original_flags.iteritems():
            setattr(FLAGS, k, v)

    def _monkey_patch_attach(self):
        self.originalAttach = rpc.Consumer.attach_to_eventlet

        def _wrapped(innerSelf):
            rv = self.originalAttach(innerSelf)
            self.injected.append(rv)
            return rv

        _wrapped.func_name = self.originalAttach.func_name
        rpc.Consumer.attach_to_eventlet = _wrapped


class TrialTestCase(trial_unittest.TestCase):
    """Test case base class for all unit tests"""
    def setUp(self):
        """Run before each test method to initialize test environment"""
        super(TrialTestCase, self).setUp()
        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = datetime.datetime.utcnow()
        ctxt = context.get_admin_context()
        if db.network_count(ctxt) != 5:
            network_manager.VlanManager().create_networks(ctxt,
                                                          FLAGS.fixed_range,
                                                          5, 16,
                                                          FLAGS.vlan_start,
                                                          FLAGS.vpn_start)

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.flag_overrides = {}
        self.injected = []
        self._original_flags = FLAGS.FlagValuesDict()

    def tearDown(self):
        """Runs after each test method to finalize/tear down test
        environment."""
        try:
            self.mox.UnsetStubs()
            self.stubs.UnsetAll()
            self.stubs.SmartUnsetAll()
            self.mox.VerifyAll()
            # NOTE(vish): Clean up any ips associated during the test.
            ctxt = context.get_admin_context()
            db.fixed_ip_disassociate_all_by_timeout(ctxt, FLAGS.host,
                                                    self.start)
            db.network_disassociate_all(ctxt)
            for x in self.injected:
                try:
                    x.stop()
                except AssertionError:
                    pass

            if FLAGS.fake_rabbit:
                fakerabbit.reset_all()

            db.security_group_destroy_all(ctxt)
            super(TrialTestCase, self).tearDown()
        finally:
            self.reset_flags()

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
        FLAGS.Reset()
        for k, v in self._original_flags.iteritems():
            setattr(FLAGS, k, v)

    def run(self, result=None):
        test_method = getattr(self, self._testMethodName)
        setattr(self,
                self._testMethodName,
                self._maybeInlineCallbacks(test_method, result))
        rv = super(TrialTestCase, self).run(result)
        setattr(self, self._testMethodName, test_method)
        return rv

    def _maybeInlineCallbacks(self, func, result):
        def _wrapped():
            g = func()
            if isinstance(g, defer.Deferred):
                return g
            if not hasattr(g, 'send'):
                return defer.succeed(g)

            inlined = defer.inlineCallbacks(func)
            d = inlined()
            return d
        _wrapped.func_name = func.func_name
        return _wrapped

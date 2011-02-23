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
import os
import shutil
import uuid
import unittest

import mox
import stubout

from nova import context
from nova import db
from nova import fakerabbit
from nova import flags
from nova import rpc
from nova import service


FLAGS = flags.FLAGS
flags.DEFINE_string('sqlite_clean_db', 'clean.sqlite',
                    'File name of clean sqlite db')
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
        self._original_flags = FLAGS.FlagValuesDict()

    def tearDown(self):
        """Runs after each test method to finalize/tear down test
        environment."""
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

            # Reset any overriden flags
            self.reset_flags()

            # Reset our monkey-patches
            rpc.Consumer.attach_to_eventlet = self.originalAttach

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

    def start_service(self, name, host=None, **kwargs):
        host = host and host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        svc = service.Service.create(**kwargs)
        svc.start()
        self._services.append(svc)
        return svc

    def _monkey_patch_attach(self):
        self.originalAttach = rpc.Consumer.attach_to_eventlet

        def _wrapped(innerSelf):
            rv = self.originalAttach(innerSelf)
            self.injected.append(rv)
            return rv

        _wrapped.func_name = self.originalAttach.func_name
        rpc.Consumer.attach_to_eventlet = _wrapped

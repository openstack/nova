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

import sys
import uuid

from fixtures import EnvironmentVariable
import mox
import stubout
import testtools

from nova import config
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import service
from nova import tests
from nova.tests import fake_flags


test_opts = [
    cfg.StrOpt('sqlite_clean_db',
               default='clean.sqlite',
               help='File name of clean sqlite db'),
    cfg.BoolOpt('fake_tests',
                default=True,
                help='should we use everything for testing'),
    ]

CONF = config.CONF
CONF.register_opts(test_opts)

LOG = logging.getLogger(__name__)


class TestingException(Exception):
    pass


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests."""

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()

        fake_flags.set_defaults(CONF)
        config.parse_args([], default_config_files=[])

        # NOTE(vish): We need a better method for creating fixtures for tests
        #             now that we have some required db setup for the system
        #             to work properly.
        self.start = timeutils.utcnow()
        tests.reset_db()

        # emulate some of the mox stuff, we can't use the metaclass
        # because it screws with our generators
        self.mox = mox.Mox()
        self.stubs = stubout.StubOutForTesting()
        self.injected = []
        self._services = []
        self._modules = {}
        self.useFixture(EnvironmentVariable('http_proxy'))

    def tearDown(self):
        """Runs after each test method to tear down test environment."""
        try:
            self.mox.UnsetStubs()
            self.stubs.UnsetAll()
            self.stubs.SmartUnsetAll()
            self.mox.VerifyAll()
            super(TestCase, self).tearDown()
        finally:
            # Reset any overridden flags
            CONF.reset()

            # Unstub modules
            for name, mod in self._modules.iteritems():
                if mod is not None:
                    sys.modules[name] = mod
                else:
                    sys.modules.pop(name)
            self._modules = {}

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

            # Delete attributes that don't start with _ so they don't pin
            # memory around unnecessarily for the duration of the test
            # suite
            for key in [k for k in self.__dict__.keys() if k[0] != '_']:
                del self.__dict__[key]

    def stub_module(self, name, mod):
        if name not in self._modules:
            self._modules[name] = sys.modules.get(name)
        sys.modules[name] = mod

    def flags(self, **kw):
        """Override flag variables for a test."""
        group = kw.pop('group', None)
        for k, v in kw.iteritems():
            CONF.set_override(k, v, group)

    def start_service(self, name, host=None, **kwargs):
        host = host and host or uuid.uuid4().hex
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        svc = service.Service.create(**kwargs)
        svc.start()
        self._services.append(svc)
        return svc

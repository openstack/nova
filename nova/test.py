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
import contextlib

import datetime
import eventlet
eventlet.monkey_patch(os=False)

import copy
import inspect
import mock
import os

import fixtures
from oslo_cache import core as cache
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error as log_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslotest import moxstubout
import six
import testtools

from nova import context
from nova import db
from nova.network import manager as network_manager
from nova.network.security_group import openstack_driver
from nova.objects import base as objects_base
from nova.objects import flavor as flavor_obj
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import conf_fixture
from nova.tests.unit import policy_fixture
from nova import utils


CONF = cfg.CONF

logging.register_options(CONF)
CONF.set_override('use_stderr', False)
logging.setup(CONF, 'nova')
cache.configure(CONF)

_TRUE_VALUES = ('True', 'true', '1', 'yes')

if six.PY2:
    nested = contextlib.nested
else:
    @contextlib.contextmanager
    def nested(*contexts):
        with contextlib.ExitStack() as stack:
            yield [stack.enter_context(c) for c in contexts]


class SampleNetworks(fixtures.Fixture):

    """Create sample networks in the database."""

    def __init__(self, host=None):
        self.host = host

    def setUp(self):
        super(SampleNetworks, self).setUp()
        ctxt = context.get_admin_context()
        network = network_manager.VlanManager(host=self.host)
        bridge_interface = CONF.flat_interface or CONF.vlan_interface
        network.create_networks(ctxt,
                                label='test',
                                cidr='10.0.0.0/8',
                                multi_host=CONF.multi_host,
                                num_networks=CONF.num_networks,
                                network_size=CONF.network_size,
                                cidr_v6=CONF.fixed_range_v6,
                                gateway=CONF.gateway,
                                gateway_v6=CONF.gateway_v6,
                                bridge=CONF.flat_network_bridge,
                                bridge_interface=bridge_interface,
                                vpn_start=CONF.vpn_start,
                                vlan_start=CONF.vlan_start,
                                dns1=CONF.flat_network_dns)
        for net in db.network_get_all(ctxt):
            network.set_network_host(ctxt, net)


class TestingException(Exception):
    pass


class skipIf(object):
    def __init__(self, condition, reason):
        self.condition = condition
        self.reason = reason

    def __call__(self, func_or_cls):
        condition = self.condition
        reason = self.reason
        if inspect.isfunction(func_or_cls):
            @six.wraps(func_or_cls)
            def wrapped(*args, **kwargs):
                if condition:
                    raise testtools.TestCase.skipException(reason)
                return func_or_cls(*args, **kwargs)

            return wrapped
        elif inspect.isclass(func_or_cls):
            orig_func = getattr(func_or_cls, 'setUp')

            @six.wraps(orig_func)
            def new_func(self, *args, **kwargs):
                if condition:
                    raise testtools.TestCase.skipException(reason)
                orig_func(self, *args, **kwargs)

            func_or_cls.setUp = new_func
            return func_or_cls
        else:
            raise TypeError('skipUnless can be used only with functions or '
                            'classes')


def _patch_mock_to_raise_for_invalid_assert_calls():
    def raise_for_invalid_assert_calls(wrapped):
        def wrapper(_self, name):
            valid_asserts = [
                'assert_called_with',
                'assert_called_once_with',
                'assert_has_calls',
                'assert_any_calls']

            if name.startswith('assert') and name not in valid_asserts:
                raise AttributeError('%s is not a valid mock assert method'
                                     % name)

            return wrapped(_self, name)
        return wrapper
    mock.Mock.__getattr__ = raise_for_invalid_assert_calls(
        mock.Mock.__getattr__)

# NOTE(gibi): needs to be called only once at import time
# to patch the mock lib
_patch_mock_to_raise_for_invalid_assert_calls()


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests.

    Due to the slowness of DB access, please consider deriving from
    `NoDBTestCase` first.
    """
    USES_DB = True
    USES_DB_SELF = False
    REQUIRES_LOCKING = False

    TIMEOUT_SCALING_FACTOR = 1

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCase, self).setUp()
        self.useFixture(nova_fixtures.Timeout(
            os.environ.get('OS_TEST_TIMEOUT', 0),
            self.TIMEOUT_SCALING_FACTOR))

        self.useFixture(fixtures.NestedTempfile())
        self.useFixture(fixtures.TempHomeDir())
        self.useFixture(log_fixture.get_logging_handle_error_fixture())

        self.useFixture(nova_fixtures.OutputStreamCapture())

        self.useFixture(nova_fixtures.StandardLogging())

        # NOTE(sdague): because of the way we were using the lock
        # wrapper we eneded up with a lot of tests that started
        # relying on global external locking being set up for them. We
        # consider all of these to be *bugs*. Tests should not require
        # global external locking, or if they do, they should
        # explicitly set it up themselves.
        #
        # The following REQUIRES_LOCKING class parameter is provided
        # as a bridge to get us there. No new tests should be added
        # that require it, and existing classes and tests should be
        # fixed to not need it.
        if self.REQUIRES_LOCKING:
            lock_path = self.useFixture(fixtures.TempDir()).path
            self.fixture = self.useFixture(
                config_fixture.Config(lockutils.CONF))
            self.fixture.config(lock_path=lock_path,
                                group='oslo_concurrency')

        self.useFixture(conf_fixture.ConfFixture(CONF))
        self.useFixture(nova_fixtures.RPCFixture('nova.test'))

        if self.USES_DB:
            self.useFixture(nova_fixtures.Database())
            self.useFixture(nova_fixtures.Database(database='api'))
            # NOTE(danms): Flavors are encoded in our original migration
            # which means we have no real option other than to migrate them
            # onlineish every time we build a new database (for now).
            ctxt = context.get_admin_context()
            flavor_obj.migrate_flavors(ctxt, 100, hard_delete=True)
        elif not self.USES_DB_SELF:
            self.useFixture(nova_fixtures.DatabasePoisonFixture())

        # NOTE(blk-u): WarningsFixture must be after the Database fixture
        # because sqlalchemy-migrate messes with the warnings filters.
        self.useFixture(nova_fixtures.WarningsFixture())

        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry.
        objects_base.NovaObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.NovaObjectRegistry._registry._obj_classes)
        self.addCleanup(self._restore_obj_registry)

        self.useFixture(nova_fixtures.StableObjectJsonFixture())

        # NOTE(mnaser): All calls to utils.is_neutron() are cached in
        # nova.utils._IS_NEUTRON.  We set it to None to avoid any
        # caching of that value.
        utils._IS_NEUTRON = None

        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs
        self.addCleanup(self._clear_attrs)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

        self.useFixture(nova_fixtures.PoisonFunctions())

        openstack_driver.DRIVER_CACHE = {}

        self.useFixture(nova_fixtures.ForbidNewLegacyNotificationFixture())

    def _restore_obj_registry(self):
        objects_base.NovaObjectRegistry._registry._obj_classes = \
                self._base_test_obj_backup

    def _clear_attrs(self):
        # Delete attributes that don't start with _ so they don't pin
        # memory around unnecessarily for the duration of the test
        # suite
        for key in [k for k in self.__dict__.keys() if k[0] != '_']:
            # NOTE(gmann): Skip attribute 'id' because if tests are being
            # generated using testscenarios then, 'id' attribute is being
            # added during cloning the tests. And later that 'id' attribute
            # is being used by test suite to generate the results for each
            # newly generated tests by testscenarios.
            if key != 'id':
                del self.__dict__[key]

    def stub_out(self, old, new):
        """Replace a function for the duration of the test.

        Use the monkey patch fixture to replace a function for the
        duration of a test. Useful when you want to provide fake
        methods instead of mocks during testing.

        This should be used instead of self.stubs.Set (which is based
        on mox) going forward.
        """
        self.useFixture(fixtures.MonkeyPatch(old, new))

    def flags(self, **kw):
        """Override flag variables for a test."""
        group = kw.pop('group', None)
        for k, v in six.iteritems(kw):
            CONF.set_override(k, v, group)

    def start_service(self, name, host=None, **kwargs):
        svc = self.useFixture(
            nova_fixtures.ServiceFixture(name, host, **kwargs))
        return svc.service

    def assertJsonEqual(self, expected, observed):
        """Asserts that 2 complex data structures are json equivalent.

        We use data structures which serialize down to json throughout
        the code, and often times we just need to know that these are
        json equivalent. This means that list order is not important,
        and should be sorted.

        Because this is a recursive set of assertions, when failure
        happens we want to expose both the local failure and the
        global view of the 2 data structures being compared. So a
        MismatchError which includes the inner failure as the
        mismatch, and the passed in expected / observed as matchee /
        matcher.

        """
        if isinstance(expected, six.string_types):
            expected = jsonutils.loads(expected)
        if isinstance(observed, six.string_types):
            observed = jsonutils.loads(observed)

        def sort_key(x):
            if isinstance(x, (set, list)) or isinstance(x, datetime.datetime):
                return str(x)
            if isinstance(x, dict):
                items = ((sort_key(key), sort_key(value))
                         for key, value in x.items())
                return sorted(items)
            return x

        def inner(expected, observed):
            if isinstance(expected, dict) and isinstance(observed, dict):
                self.assertEqual(len(expected), len(observed))
                expected_keys = sorted(expected)
                observed_keys = sorted(observed)
                self.assertEqual(expected_keys, observed_keys)

                for key in list(six.iterkeys(expected)):
                    inner(expected[key], observed[key])
            elif (isinstance(expected, (list, tuple, set)) and
                      isinstance(observed, (list, tuple, set))):
                self.assertEqual(len(expected), len(observed))

                expected_values_iter = iter(sorted(expected, key=sort_key))
                observed_values_iter = iter(sorted(observed, key=sort_key))

                for i in range(len(expected)):
                    inner(next(expected_values_iter),
                          next(observed_values_iter))
            else:
                self.assertEqual(expected, observed)

        try:
            inner(expected, observed)
        except testtools.matchers.MismatchError as e:
            inner_mismatch = e.mismatch
            # inverting the observed / expected because testtools
            # error messages assume expected is second. Possibly makes
            # reading the error messages less confusing.
            raise testtools.matchers.MismatchError(observed, expected,
                                          inner_mismatch, verbose=True)

    def assertPublicAPISignatures(self, baseinst, inst):
        def get_public_apis(inst):
            methods = {}

            def findmethods(object):
                return inspect.ismethod(object) or inspect.isfunction(object)

            for (name, value) in inspect.getmembers(inst, findmethods):
                if name.startswith("_"):
                    continue
                methods[name] = value
            return methods

        baseclass = baseinst.__class__.__name__
        basemethods = get_public_apis(baseinst)
        implmethods = get_public_apis(inst)

        extranames = []
        for name in sorted(implmethods.keys()):
            if name not in basemethods:
                extranames.append(name)

        self.assertEqual([], extranames,
                         "public APIs not listed in base class %s" %
                         baseclass)

        for name in sorted(implmethods.keys()):
            baseargs = inspect.getargspec(basemethods[name])
            implargs = inspect.getargspec(implmethods[name])

            self.assertEqual(baseargs, implargs,
                             "%s args don't match base class %s" %
                             (name, baseclass))


class APICoverage(object):

    cover_api = None

    def test_api_methods(self):
        self.assertTrue(self.cover_api is not None)
        api_methods = [x for x in dir(self.cover_api)
                       if not x.startswith('_')]
        test_methods = [x[5:] for x in dir(self)
                        if x.startswith('test_')]
        self.assertThat(
            test_methods,
            testtools.matchers.ContainsAll(api_methods))


class TimeOverride(fixtures.Fixture):
    """Fixture to start and remove time override."""

    def setUp(self):
        super(TimeOverride, self).setUp()
        timeutils.set_time_override()
        self.addCleanup(timeutils.clear_time_override)


class NoDBTestCase(TestCase):
    """`NoDBTestCase` differs from TestCase in that DB access is not supported.
    This makes tests run significantly faster. If possible, all new tests
    should derive from this class.
    """
    USES_DB = False


class BaseHookTestCase(NoDBTestCase):
    def assert_has_hook(self, expected_name, func):
        self.assertTrue(hasattr(func, '__hook_name__'))
        self.assertEqual(expected_name, func.__hook_name__)


class MatchType(object):
    """Matches any instance of a specified type

    The MatchType class is a helper for use with the
    mock.assert_called_with() method that lets you
    assert that a particular parameter has a specific
    data type. It enables strict check than the built
    in mock.ANY helper, and is the equivalent of the
    mox.IsA() function from the legacy mox library

    Example usage could be:

      mock_some_method.assert_called_once_with(
            "hello",
            MatchType(objects.Instance),
            mock.ANY,
            "world",
            MatchType(objects.KeyPair))
    """
    def __init__(self, wanttype):
        self.wanttype = wanttype

    def __eq__(self, other):
        return type(other) == self.wanttype

    def __ne__(self, other):
        return type(other) != self.wanttype

    def __repr__(self):
        return "<MatchType:" + str(self.wanttype) + ">"

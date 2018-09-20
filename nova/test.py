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

import eventlet  # noqa
eventlet.monkey_patch(os=False)

import abc
import contextlib
import copy
import datetime
import inspect
import itertools
import os
import pprint
import sys

import fixtures
import mock
from oslo_cache import core as cache
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_log.fixture import logging_error as log_fixture
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_versionedobjects import fixture as ovo_fixture
from oslotest import moxstubout
import six
import testtools

from nova import context
from nova import db
from nova import exception
from nova.network import manager as network_manager
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import base as objects_base
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import conf_fixture
from nova.tests.unit import policy_fixture
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.virt import images


CONF = cfg.CONF

logging.register_options(CONF)
CONF.set_override('use_stderr', False)
logging.setup(CONF, 'nova')
cache.configure(CONF)

_TRUE_VALUES = ('True', 'true', '1', 'yes')
CELL1_NAME = 'cell1'


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


class NovaExceptionReraiseFormatError(object):
    real_log_exception = exception.NovaException._log_exception

    @classmethod
    def patch(cls):
        exception.NovaException._log_exception = cls._wrap_log_exception

    @staticmethod
    def _wrap_log_exception(self):
        exc_info = sys.exc_info()
        NovaExceptionReraiseFormatError.real_log_exception(self)
        six.reraise(*exc_info)


# NOTE(melwitt) This needs to be done at import time in order to also catch
# NovaException format errors that are in mock decorators. In these cases, the
# errors will be raised during test listing, before tests actually run.
NovaExceptionReraiseFormatError.patch()


class TestCase(testtools.TestCase):
    """Test case base class for all unit tests.

    Due to the slowness of DB access, please consider deriving from
    `NoDBTestCase` first.
    """
    # USES_DB is set to False for tests that inherit from NoDBTestCase.
    USES_DB = True
    # USES_DB_SELF is set to True in tests that specifically want to use the
    # database but need to configure it themselves, for example to setup the
    # API DB but not the cell DB. In those cases the test will override
    # USES_DB_SELF = True but inherit from the NoDBTestCase class so it does
    # not get the default fixture setup when using a database (which is the
    # API and cell DBs, and adding the default flavors).
    USES_DB_SELF = False
    REQUIRES_LOCKING = False

    # Setting to True makes the test use the RPCFixture.
    STUB_RPC = True

    # The number of non-cell0 cells to create. This is only used in the
    # base class when USES_DB is True.
    NUMBER_OF_CELLS = 1

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

        self.output = nova_fixtures.OutputStreamCapture()
        self.useFixture(self.output)

        self.stdlog = nova_fixtures.StandardLogging()
        self.useFixture(self.stdlog)

        # NOTE(sdague): because of the way we were using the lock
        # wrapper we ended up with a lot of tests that started
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

        if self.STUB_RPC:
            self.useFixture(nova_fixtures.RPCFixture('nova.test'))

        # we cannot set this in the ConfFixture as oslo only registers the
        # notification opts at the first instantiation of a Notifier that
        # happens only in the RPCFixture
        CONF.set_default('driver', ['test'],
                         group='oslo_messaging_notifications')

        # NOTE(danms): Make sure to reset us back to non-remote objects
        # for each test to avoid interactions. Also, backup the object
        # registry.
        objects_base.NovaObject.indirection_api = None
        self._base_test_obj_backup = copy.copy(
            objects_base.NovaObjectRegistry._registry._obj_classes)
        self.addCleanup(self._restore_obj_registry)
        objects.Service.clear_min_version_cache()

        # NOTE(danms): Reset the cached list of cells
        from nova.compute import api
        api.CELLS = []
        context.CELL_CACHE = {}
        context.CELLS = []

        self.cell_mappings = {}
        self.host_mappings = {}
        # NOTE(danms): If the test claims to want to set up the database
        # itself, then it is responsible for all the mapping stuff too.
        if self.USES_DB:
            # NOTE(danms): Full database setup involves a cell0, cell1,
            # and the relevant mappings.
            self.useFixture(nova_fixtures.Database(database='api'))
            self._setup_cells()
            self.useFixture(nova_fixtures.DefaultFlavorsFixture())
        elif not self.USES_DB_SELF:
            # NOTE(danms): If not using the database, we mock out the
            # mapping stuff and effectively collapse everything to a
            # single cell.
            self.useFixture(nova_fixtures.SingleCellSimple())
            self.useFixture(nova_fixtures.DatabasePoisonFixture())

        # NOTE(blk-u): WarningsFixture must be after the Database fixture
        # because sqlalchemy-migrate messes with the warnings filters.
        self.useFixture(nova_fixtures.WarningsFixture())

        self.useFixture(ovo_fixture.StableObjectJsonFixture())

        # NOTE(mnaser): All calls to utils.is_neutron() are cached in
        # nova.utils._IS_NEUTRON.  We set it to None to avoid any
        # caching of that value.
        utils._IS_NEUTRON = None

        # Reset the traits sync and rc cache flags
        objects.resource_provider._TRAITS_SYNCED = False
        objects.resource_provider._RC_CACHE = None
        # Reset the global QEMU version flag.
        images.QEMU_VERSION = None

        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs
        self.addCleanup(self._clear_attrs)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

        self.useFixture(nova_fixtures.PoisonFunctions())

        openstack_driver.DRIVER_CACHE = {}

        self.useFixture(nova_fixtures.ForbidNewLegacyNotificationFixture())

        # NOTE(mikal): make sure we don't load a privsep helper accidentally
        self.useFixture(nova_fixtures.PrivsepNoHelperFixture())

        # FIXME(danms): Disable this for all tests by default to avoid breaking
        # any that depend on default/previous ordering
        self.flags(build_failure_weight_multiplier=0.0,
                   group='filter_scheduler')

    def _setup_cells(self):
        """Setup a normal cellsv2 environment.

        This sets up the CellDatabase fixture with two cells, one cell0
        and one normal cell. CellMappings are created for both so that
        cells-aware code can find those two databases.
        """
        celldbs = nova_fixtures.CellDatabases()

        ctxt = context.get_context()
        fake_transport = 'fake://nowhere/'

        c0 = objects.CellMapping(
            context=ctxt,
            uuid=objects.CellMapping.CELL0_UUID,
            name='cell0',
            transport_url=fake_transport,
            database_connection=objects.CellMapping.CELL0_UUID)
        c0.create()
        self.cell_mappings[c0.name] = c0
        celldbs.add_cell_database(objects.CellMapping.CELL0_UUID)

        for x in range(self.NUMBER_OF_CELLS):
            name = 'cell%i' % (x + 1)
            uuid = getattr(uuids, name)
            cell = objects.CellMapping(
                context=ctxt,
                uuid=uuid,
                name=name,
                transport_url=fake_transport,
                database_connection=uuid)
            cell.create()
            self.cell_mappings[name] = cell
            # cell1 is the default cell
            celldbs.add_cell_database(uuid, default=(x == 0))

        self.useFixture(celldbs)

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
        for k, v in kw.items():
            CONF.set_override(k, v, group)

    def start_service(self, name, host=None, **kwargs):
        cell = None
        if name == 'compute' and self.USES_DB:
            # NOTE(danms): We need to create the HostMapping first, because
            # otherwise we'll fail to update the scheduler while running
            # the compute node startup routines below.
            ctxt = context.get_context()
            cell = self.cell_mappings[kwargs.pop('cell', CELL1_NAME)]
            hm = objects.HostMapping(context=ctxt,
                                     host=host or name,
                                     cell_mapping=cell)
            hm.create()
            self.host_mappings[hm.host] = hm
            if host is not None:
                # Make sure that CONF.host is relevant to the right hostname
                self.useFixture(nova_fixtures.ConfPatcher(host=host))
        svc = self.useFixture(
            nova_fixtures.ServiceFixture(name, host, cell=cell, **kwargs))

        return svc.service

    def restart_compute_service(self, compute):
        """Restart a compute service in a realistic way.

        :param:compute: the nova-compute service to be restarted
        """

        # NOTE(gibi): The service interface cannot be used to simulate a real
        # service restart as the manager object will not be recreated after a
        # service.stop() and service.start() therefore the manager state will
        # survive. For example the resource tracker will not be recreated after
        # a stop start. The service.kill() call cannot help as it deletes
        # the service from the DB which is unrealistic and causes that some
        # operation that refers to the killed host (e.g. evacuate) fails.
        # So this helper method tries to simulate a better compute service
        # restart by cleaning up some of the internal state of the compute
        # manager.
        compute.stop()
        compute.manager._resource_tracker = None
        compute.start()

    def assertJsonEqual(self, expected, observed, message=''):
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

        def inner(expected, observed, path='root'):
            if isinstance(expected, dict) and isinstance(observed, dict):
                self.assertEqual(
                    len(expected), len(observed),
                    ('path: %s. Different dict key sets\n'
                     'expected=%s\n'
                     'observed=%s\n'
                     'difference=%s') %
                    (path,
                     sorted(expected.keys()),
                     sorted(observed.keys()),
                     list(set(expected.keys()).symmetric_difference(
                         set(observed.keys())))))
                expected_keys = sorted(expected)
                observed_keys = sorted(observed)
                self.assertEqual(
                    expected_keys, observed_keys,
                    'path: %s. Dict keys are not equal' % path)
                for key in list(six.iterkeys(expected)):
                    inner(expected[key], observed[key], path + '.%s' % key)
            elif (isinstance(expected, (list, tuple, set)) and
                      isinstance(observed, (list, tuple, set))):
                self.assertEqual(
                    len(expected), len(observed),
                    ('path: %s. Different list items\n'
                     'expected=%s\n'
                     'observed=%s\n'
                     'difference=%s') %
                    (path,
                     sorted(expected, key=sort_key),
                     sorted(observed, key=sort_key),
                     [a for a in itertools.chain(expected, observed) if
                      (a not in expected) or (a not in observed)]))

                expected_values_iter = iter(sorted(expected, key=sort_key))
                observed_values_iter = iter(sorted(observed, key=sort_key))

                for i in range(len(expected)):
                    inner(next(expected_values_iter),
                          next(observed_values_iter), path + '[%s]' % i)
            else:
                self.assertEqual(expected, observed, 'path: %s' % path)

        try:
            inner(expected, observed)
        except testtools.matchers.MismatchError as e:
            difference = e.mismatch.describe()
            if message:
                message = 'message: %s\n' % message
            msg = "\nexpected:\n%s\nactual:\n%s\ndifference:\n%s\n%s" % (
                pprint.pformat(expected),
                pprint.pformat(observed),
                difference,
                message)
            error = AssertionError(msg)
            error.expected = expected
            error.observed = observed
            error.difference = difference
            raise error

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
        self.assertIsNotNone(self.cover_api)
        api_methods = [x for x in dir(self.cover_api)
                       if not x.startswith('_')]
        test_methods = [x[5:] for x in dir(self)
                        if x.startswith('test_')]
        self.assertThat(
            test_methods,
            testtools.matchers.ContainsAll(api_methods))


@six.add_metaclass(abc.ABCMeta)
class SubclassSignatureTestCase(testtools.TestCase):
    """Ensure all overriden methods of all subclasses of the class
    under test exactly match the signature of the base class.

    A subclass of SubclassSignatureTestCase should define a method
    _get_base_class which:

    * Returns a base class whose subclasses will all be checked
    * Ensures that all subclasses to be tested have been imported

    SubclassSignatureTestCase defines a single test, test_signatures,
    which does a recursive, depth-first check of all subclasses, ensuring
    that their method signatures are identical to those of the base class.
    """
    @abc.abstractmethod
    def _get_base_class(self):
        raise NotImplementedError()

    def setUp(self):
        self.base = self._get_base_class()

        super(SubclassSignatureTestCase, self).setUp()

    @staticmethod
    def _get_argspecs(cls):
        """Return a dict of method_name->argspec for every method of cls."""
        argspecs = {}

        # getmembers returns all members, including members inherited from
        # the base class. It's redundant for us to test these, but as
        # they'll always pass it's not worth the complexity to filter them out.
        for (name, method) in inspect.getmembers(cls, inspect.ismethod):
            # Subclass __init__ methods can usually be legitimately different
            if name == '__init__':
                continue

            while hasattr(method, '__wrapped__'):
                # This is a wrapped function. The signature we're going to
                # see here is that of the wrapper, which is almost certainly
                # going to involve varargs and kwargs, and therefore is
                # unlikely to be what we want. If the wrapper manupulates the
                # arguments taken by the wrapped function, the wrapped function
                # isn't what we want either. In that case we're just stumped:
                # if it ever comes up, add more knobs here to work round it (or
                # stop using a dynamic language).
                #
                # Here we assume the wrapper doesn't manipulate the arguments
                # to the wrapped function and inspect the wrapped function
                # instead.
                method = getattr(method, '__wrapped__')

            argspecs[name] = inspect.getargspec(method)

        return argspecs

    @staticmethod
    def _clsname(cls):
        """Return the fully qualified name of cls."""
        return "%s.%s" % (cls.__module__, cls.__name__)

    def _test_signatures_recurse(self, base, base_argspecs):
        for sub in base.__subclasses__():
            sub_argspecs = self._get_argspecs(sub)

            # Check that each subclass method matches the signature of the
            # base class
            for (method, sub_argspec) in sub_argspecs.items():
                # Methods which don't override methods in the base class
                # are good.
                if method in base_argspecs:
                    self.assertEqual(base_argspecs[method], sub_argspec,
                                     'Signature of %(sub)s.%(method)s '
                                     'differs from superclass %(base)s' %
                                     {'base': self._clsname(base),
                                      'sub': self._clsname(sub),
                                      'method': method})

            # Recursively check this subclass
            self._test_signatures_recurse(sub, sub_argspecs)

    def test_signatures(self):
        self._test_signatures_recurse(self.base, self._get_argspecs(self.base))


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


class MatchObjPrims(object):
    """Matches objects with equal primitives."""
    def __init__(self, want_obj):
        self.want_obj = want_obj

    def __eq__(self, other):
        return objects_base.obj_equal_prims(other, self.want_obj)

    def __ne__(self, other):
        return not other == self.want_obj

    def __repr__(self):
        return '<MatchObjPrims:' + str(self.want_obj) + '>'


class ContainKeyValue(object):
    """Checks whether a key/value pair is in a dict parameter.

    The ContainKeyValue class is a helper for use with the
    mock.assert_*() method that lets you assert that a particular
    dict contain a key/value pair. It enables strict check than
    the built in mock.ANY helper, and is the equivalent of the
    mox.ContainsKeyValue() function from the legacy mox library

    Example usage could be:

      mock_some_method.assert_called_once_with(
            "hello",
            ContainKeyValue('foo', bar),
            mock.ANY,
            "world",
            ContainKeyValue('hello', world))
    """
    def __init__(self, wantkey, wantvalue):
        self.wantkey = wantkey
        self.wantvalue = wantvalue

    def __eq__(self, other):
        try:
            return other[self.wantkey] == self.wantvalue
        except (KeyError, TypeError):
            return False

    def __ne__(self, other):
        try:
            return other[self.wantkey] != self.wantvalue
        except (KeyError, TypeError):
            return True

    def __repr__(self):
        return "<ContainKeyValue: key " + str(self.wantkey) + \
               " and value " + str(self.wantvalue) + ">"

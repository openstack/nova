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

import nova.monkey_patch  # noqa

import abc
import copy
import datetime
import inspect
import itertools
import os
import os.path
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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import fixture as ovo_fixture
from oslotest import mock_fixture
from oslotest import moxstubout
import six
from six.moves import builtins
import testtools

from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova.db import api as db
from nova import exception
from nova.network import manager as network_manager
from nova.network.security_group import openstack_driver
from nova import objects
from nova.objects import base as objects_base
from nova import quota
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import conf_fixture
from nova.tests.unit import matchers
from nova.tests.unit import policy_fixture
from nova import utils
from nova.virt import images

if six.PY2:
    import contextlib2 as contextlib
else:
    import contextlib

CONF = cfg.CONF

logging.register_options(CONF)
CONF.set_override('use_stderr', False)
logging.setup(CONF, 'nova')
cache.configure(CONF)

_TRUE_VALUES = ('True', 'true', '1', 'yes')
CELL1_NAME = 'cell1'


# For compatibility with the large number of tests which use test.nested
nested = utils.nested_contexts


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


# NOTE(claudiub): this needs to be called before any mock.patch calls are
# being done, and especially before any other test classes load. This fixes
# the mock.patch autospec issue:
# https://github.com/testing-cabal/mock/issues/396
mock_fixture.patch_mock_module()


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

        self.useFixture(nova_fixtures.OpenStackSDKFixture())

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

        # Reset the global QEMU version flag.
        images.QEMU_VERSION = None

        # Reset the compute RPC API globals (mostly the _ROUTER).
        compute_rpcapi.reset_globals()

        mox_fixture = self.useFixture(moxstubout.MoxStubout())
        self.mox = mox_fixture.mox
        self.stubs = mox_fixture.stubs
        self.addCleanup(self._clear_attrs)
        self.useFixture(fixtures.EnvironmentVariable('http_proxy'))
        self.policy = self.useFixture(policy_fixture.PolicyFixture())

        self.useFixture(nova_fixtures.PoisonFunctions())

        openstack_driver.DRIVER_CACHE = None

        self.useFixture(nova_fixtures.ForbidNewLegacyNotificationFixture())

        # NOTE(mikal): make sure we don't load a privsep helper accidentally
        self.useFixture(nova_fixtures.PrivsepNoHelperFixture())
        self.useFixture(mock_fixture.MockAutospecFixture())

        # FIXME(danms): Disable this for all tests by default to avoid breaking
        # any that depend on default/previous ordering
        self.flags(build_failure_weight_multiplier=0.0,
                   group='filter_scheduler')

        # NOTE(melwitt): Reset the cached set of projects
        quota.UID_QFD_POPULATED_CACHE_BY_PROJECT = set()
        quota.UID_QFD_POPULATED_CACHE_ALL = False

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

    @staticmethod
    def patch_exists(patched_path, result):
        """Provide a static method version of patch_exists(), which if you
        haven't already imported nova.test can be slightly easier to
        use as a context manager within a test method via:

            def test_something(self):
                with self.patch_exists(path, True):
                    ...
        """
        return patch_exists(patched_path, result)

    @staticmethod
    def patch_open(patched_path, read_data):
        """Provide a static method version of patch_open() which is easier to
        use as a context manager within a test method via:

            def test_something(self):
                with self.patch_open(path, "fake contents of file"):
                    ...
        """
        return patch_open(patched_path, read_data)

    def flags(self, **kw):
        """Override flag variables for a test."""
        group = kw.pop('group', None)
        for k, v in kw.items():
            CONF.set_override(k, v, group)

    def start_service(self, name, host=None, **kwargs):
        cell = None
        # if the host is None then the CONF.host remains defaulted to
        # 'fake-mini' (originally done in ConfFixture)
        if host is not None:
            # Make sure that CONF.host is relevant to the right hostname
            self.useFixture(nova_fixtures.ConfPatcher(host=host))

        if name == 'compute' and self.USES_DB:
            # NOTE(danms): We need to create the HostMapping first, because
            # otherwise we'll fail to update the scheduler while running
            # the compute node startup routines below.
            ctxt = context.get_context()
            cell_name = kwargs.pop('cell', CELL1_NAME) or CELL1_NAME
            cell = self.cell_mappings[cell_name]
            if (host or name) not in self.host_mappings:
                # NOTE(gibi): If the HostMapping does not exists then this is
                # the first start of the service so we create the mapping.
                hm = objects.HostMapping(context=ctxt,
                                         host=host or name,
                                         cell_mapping=cell)
                hm.create()
                self.host_mappings[hm.host] = hm
        svc = self.useFixture(
            nova_fixtures.ServiceFixture(name, host, cell=cell, **kwargs))

        return svc.service

    def restart_compute_service(self, compute, keep_hypervisor_state=True):
        """Stops the service and starts a new one to have realistic restart

        :param:compute: the nova-compute service to be restarted
        :param:keep_hypervisor_state: If true then already defined instances
                                      will survive the compute service restart.
                                      If false then the new service will see
                                      an empty hypervisor
        :returns: a new compute service instance serving the same host and
                  and node
        """

        # NOTE(gibi): The service interface cannot be used to simulate a real
        # service restart as the manager object will not be recreated after a
        # service.stop() and service.start() therefore the manager state will
        # survive. For example the resource tracker will not be recreated after
        # a stop start. The service.kill() call cannot help as it deletes
        # the service from the DB which is unrealistic and causes that some
        # operation that refers to the killed host (e.g. evacuate) fails.
        # So this helper method will stop the original service and then starts
        # a brand new compute service for the same host and node. This way
        # a new ComputeManager instance will be created and initialized during
        # the service startup.
        compute.stop()

        # this service was running previously so we have to make sure that
        # we restart it in the same cell
        cell_name = self.host_mappings[compute.host].cell_mapping.name

        if keep_hypervisor_state:
            # NOTE(gibi): FakeDriver does not provide a meaningful way to
            # define some servers that exists already on the hypervisor when
            # the driver is (re)created during the service startup. This means
            # that we cannot simulate that the definition of a server
            # survives a nova-compute service restart on the hypervisor.
            # Instead here we save the FakeDriver instance that knows about
            # the defined servers and inject that driver into the new Manager
            # class during the startup of the compute service.
            old_driver = compute.manager.driver
            with mock.patch(
                    'nova.virt.driver.load_compute_driver') as load_driver:
                load_driver.return_value = old_driver
                new_compute = self.start_service(
                    'compute', host=compute.host, cell=cell_name)
        else:
            new_compute = self.start_service(
                'compute', host=compute.host, cell=cell_name)

        return new_compute

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

    def assertXmlEqual(self, expected, observed, **options):
        self.assertThat(observed, matchers.XMLMatches(expected, **options))

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
            baseargs = utils.getargspec(basemethods[name])
            implargs = utils.getargspec(implmethods[name])

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
    """Ensure all overridden methods of all subclasses of the class
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

            argspecs[name] = utils.getargspec(method)

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


@contextlib.contextmanager
def patch_exists(patched_path, result):
    """Selectively patch os.path.exists() so that if it's called with
    patched_path, return result.  Calls with any other path are passed
    through to the real os.path.exists() function.

    Either import and use as a decorator / context manager, or use the
    nova.TestCase.patch_exists() static method as a context manager.

    Currently it is *not* recommended to use this if any of the
    following apply:

    - You want to patch via decorator *and* make assertions about how the
      mock is called (since using it in the decorator form will not make
      the mock available to your code).

    - You want the result of the patched exists() call to be determined
      programmatically (e.g. by matching substrings of patched_path).

    - You expect exists() to be called multiple times on the same path
      and return different values each time.

    Additionally within unit tests which only test a very limited code
    path, it may be possible to ensure that the code path only invokes
    exists() once, in which case it's slightly overkill to do
    selective patching based on the path.  In this case something like
    like this may be more appropriate:

        @mock.patch('os.path.exists', return_value=True)
        def test_my_code(self, mock_exists):
            ...
            mock_exists.assert_called_once_with(path)
    """
    real_exists = os.path.exists

    def fake_exists(path):
        if path == patched_path:
            return result
        return real_exists(path)

    with mock.patch.object(os.path, "exists") as mock_exists:
        mock_exists.side_effect = fake_exists
        yield mock_exists


@contextlib.contextmanager
def patch_open(patched_path, read_data):
    """Selectively patch open() so that if it's called with patched_path,
    return a mock which makes it look like the file contains
    read_data.  Calls with any other path are passed through to the
    real open() function.

    Either import and use as a decorator, or use the
    nova.TestCase.patch_open() static method as a context manager.

    Currently it is *not* recommended to use this if any of the
    following apply:

    - The code under test will attempt to write to patched_path.

    - You want to patch via decorator *and* make assertions about how the
      mock is called (since using it in the decorator form will not make
      the mock available to your code).

    - You want the faked file contents to be determined
      programmatically (e.g. by matching substrings of patched_path).

    - You expect open() to be called multiple times on the same path
      and return different file contents each time.

    Additionally within unit tests which only test a very limited code
    path, it may be possible to ensure that the code path only invokes
    open() once, in which case it's slightly overkill to do
    selective patching based on the path.  In this case something like
    like this may be more appropriate:

        @mock.patch(six.moves.builtins, 'open')
        def test_my_code(self, mock_open):
            ...
            mock_open.assert_called_once_with(path)
    """
    real_open = builtins.open
    m = mock.mock_open(read_data=read_data)

    def selective_fake_open(path, *args, **kwargs):
        if path == patched_path:
            return m(patched_path)
        return real_open(path, *args, **kwargs)

    with mock.patch.object(builtins, 'open') as mock_open:
        mock_open.side_effect = selective_fake_open
        yield m

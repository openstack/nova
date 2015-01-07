#    Copyright 2011 Justin Santa Barbara
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

import datetime
import functools
import hashlib
import importlib
import os
import os.path
import StringIO
import tempfile

import mock
from mox3 import mox
import netaddr
from oslo.config import cfg
from oslo.utils import timeutils
from oslo_concurrency import processutils

import nova
from nova import exception
from nova import test
from nova import utils

CONF = cfg.CONF


class GetMyIP4AddressTestCase(test.NoDBTestCase):
    def test_get_my_ipv4_address_with_no_ipv4(self):
        response = """172.16.0.0/16 via 172.16.251.13 dev tun1
172.16.251.1 via 172.16.251.13 dev tun1
172.16.251.13 dev tun1  proto kernel  scope link  src 172.16.251.14
172.24.0.0/16 via 172.16.251.13 dev tun1
192.168.122.0/24 dev virbr0  proto kernel  scope link  src 192.168.122.1"""

        def fake_execute(*args, **kwargs):
            return response, None

        self.stubs.Set(utils, 'execute', fake_execute)
        address = utils.get_my_ipv4_address()
        self.assertEqual(address, '127.0.0.1')

    def test_get_my_ipv4_address_bad_process(self):
        def fake_execute(*args, **kwargs):
            raise processutils.ProcessExecutionError()

        self.stubs.Set(utils, 'execute', fake_execute)
        address = utils.get_my_ipv4_address()
        self.assertEqual(address, '127.0.0.1')

    def test_get_my_ipv4_address_with_single_interface(self):
        response_route = """default via 192.168.1.1 dev wlan0  proto static
192.168.1.0/24 dev wlan0  proto kernel  scope link  src 192.168.1.137  metric 9
"""
        response_addr = """
1: lo    inet 127.0.0.1/8 scope host lo
3: wlan0    inet 192.168.1.137/24 brd 192.168.1.255 scope global wlan0
"""

        def fake_execute(*args, **kwargs):
            if 'route' in args:
                return response_route, None
            return response_addr, None

        self.stubs.Set(utils, 'execute', fake_execute)
        address = utils.get_my_ipv4_address()
        self.assertEqual(address, '192.168.1.137')

    def test_get_my_ipv4_address_with_multi_ipv4_on_single_interface(self):
        response_route = """
172.18.56.0/24 dev customer  proto kernel  scope link  src 172.18.56.22
169.254.0.0/16 dev customer  scope link  metric 1031
default via 172.18.56.1 dev customer
"""
        response_addr = (""
"31: customer    inet 172.18.56.22/24 brd 172.18.56.255 scope global"
" customer\n"
"31: customer    inet 172.18.56.32/24 brd 172.18.56.255 scope global "
"secondary customer")

        def fake_execute(*args, **kwargs):
            if 'route' in args:
                return response_route, None
            return response_addr, None

        self.stubs.Set(utils, 'execute', fake_execute)
        address = utils.get_my_ipv4_address()
        self.assertEqual(address, '172.18.56.22')

    def test_get_my_ipv4_address_with_multiple_interfaces(self):
        response_route = """
169.1.9.0/24 dev eth1  proto kernel  scope link  src 169.1.9.10
172.17.248.0/21 dev eth0  proto kernel  scope link  src 172.17.255.9
169.254.0.0/16 dev eth0  scope link  metric 1002
169.254.0.0/16 dev eth1  scope link  metric 1003
default via 172.17.248.1 dev eth0  proto static
"""
        response_addr = """
1: lo    inet 127.0.0.1/8 scope host lo
2: eth0    inet 172.17.255.9/21 brd 172.17.255.255 scope global eth0
3: eth1    inet 169.1.9.10/24 scope global eth1
"""

        def fake_execute(*args, **kwargs):
            if 'route' in args:
                return response_route, None
            return response_addr, None

        self.stubs.Set(utils, 'execute', fake_execute)
        address = utils.get_my_ipv4_address()
        self.assertEqual(address, '172.17.255.9')


class GenericUtilsTestCase(test.NoDBTestCase):
    def test_parse_server_string(self):
        result = utils.parse_server_string('::1')
        self.assertEqual(('::1', ''), result)
        result = utils.parse_server_string('[::1]:8773')
        self.assertEqual(('::1', '8773'), result)
        result = utils.parse_server_string('2001:db8::192.168.1.1')
        self.assertEqual(('2001:db8::192.168.1.1', ''), result)
        result = utils.parse_server_string('[2001:db8::192.168.1.1]:8773')
        self.assertEqual(('2001:db8::192.168.1.1', '8773'), result)
        result = utils.parse_server_string('192.168.1.1')
        self.assertEqual(('192.168.1.1', ''), result)
        result = utils.parse_server_string('192.168.1.2:8773')
        self.assertEqual(('192.168.1.2', '8773'), result)
        result = utils.parse_server_string('192.168.1.3')
        self.assertEqual(('192.168.1.3', ''), result)
        result = utils.parse_server_string('www.example.com:8443')
        self.assertEqual(('www.example.com', '8443'), result)
        result = utils.parse_server_string('www.example.com')
        self.assertEqual(('www.example.com', ''), result)
        # error case
        result = utils.parse_server_string('www.exa:mple.com:8443')
        self.assertEqual(('', ''), result)
        result = utils.parse_server_string('')
        self.assertEqual(('', ''), result)

    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual("91----test-host.example.com-0",
                         utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual("hello", utils.sanitize_hostname(hostname))

    def test_read_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        os.path.getmtime(mox.IgnoreArg()).AndReturn(1)
        self.mox.ReplayAll()

        cache_data = {"data": 1123, "mtime": 1}
        data = utils.read_cached_file("/this/is/a/fake", cache_data)
        self.assertEqual(cache_data["data"], data)

    def test_read_modified_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        os.path.getmtime(mox.IgnoreArg()).AndReturn(2)
        self.mox.ReplayAll()

        fake_contents = "lorem ipsum"
        m = mock.mock_open(read_data=fake_contents)
        with mock.patch("__builtin__.open", m, create=True):
            cache_data = {"data": 1123, "mtime": 1}
            self.reload_called = False

            def test_reload(reloaded_data):
                self.assertEqual(reloaded_data, fake_contents)
                self.reload_called = True

            data = utils.read_cached_file("/this/is/a/fake", cache_data,
                                                    reload_func=test_reload)
            self.assertEqual(data, fake_contents)
            self.assertTrue(self.reload_called)

    def test_generate_password(self):
        password = utils.generate_password()
        self.assertTrue([c for c in password if c in '0123456789'])
        self.assertTrue([c for c in password
                         if c in 'abcdefghijklmnopqrstuvwxyz'])
        self.assertTrue([c for c in password
                         if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'])

    def test_read_file_as_root(self):
        def fake_execute(*args, **kwargs):
            if args[1] == 'bad':
                raise processutils.ProcessExecutionError()
            return 'fakecontents', None

        self.stubs.Set(utils, 'execute', fake_execute)
        contents = utils.read_file_as_root('good')
        self.assertEqual(contents, 'fakecontents')
        self.assertRaises(exception.FileNotFound,
                          utils.read_file_as_root, 'bad')

    def test_temporary_chown(self):
        def fake_execute(*args, **kwargs):
            if args[0] == 'chown':
                fake_execute.uid = args[1]
        self.stubs.Set(utils, 'execute', fake_execute)

        with tempfile.NamedTemporaryFile() as f:
            with utils.temporary_chown(f.name, owner_uid=2):
                self.assertEqual(fake_execute.uid, 2)
            self.assertEqual(fake_execute.uid, os.getuid())

    def test_xhtml_escape(self):
        self.assertEqual('&quot;foo&quot;', utils.xhtml_escape('"foo"'))
        self.assertEqual('&apos;foo&apos;', utils.xhtml_escape("'foo'"))
        self.assertEqual('&amp;', utils.xhtml_escape('&'))
        self.assertEqual('&gt;', utils.xhtml_escape('>'))
        self.assertEqual('&lt;', utils.xhtml_escape('<'))
        self.assertEqual('&lt;foo&gt;', utils.xhtml_escape('<foo>'))

    def test_is_valid_ipv6_cidr(self):
        self.assertTrue(utils.is_valid_ipv6_cidr("2600::/64"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
                "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254/48"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
                "0000:0000:0000:0000:0000:0000:0000:0001/32"))
        self.assertTrue(utils.is_valid_ipv6_cidr(
                "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertFalse(utils.is_valid_ipv6_cidr("foo"))
        self.assertFalse(utils.is_valid_ipv6_cidr("127.0.0.1"))

    def test_get_shortened_ipv6(self):
        self.assertEqual("abcd:ef01:2345:6789:abcd:ef01:c0a8:fefe",
                         utils.get_shortened_ipv6(
                            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertEqual("::1", utils.get_shortened_ipv6(
                                    "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertEqual("caca::caca:0:babe:201:102",
                         utils.get_shortened_ipv6(
                                    "caca:0000:0000:caca:0000:babe:0201:0102"))
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "failure")

    def test_get_shortened_ipv6_cidr(self):
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600:0000:0000:0000:0000:0000:0000:0000/64"))
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600::1/64"))
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "failure")

    def test_get_hash_str(self):
        base_str = "foo"
        value = hashlib.md5(base_str).hexdigest()
        self.assertEqual(
            value, utils.get_hash_str(base_str))


class MonkeyPatchTestCase(test.NoDBTestCase):
    """Unit test for utils.monkey_patch()."""
    def setUp(self):
        super(MonkeyPatchTestCase, self).setUp()
        self.example_package = 'nova.tests.unit.monkey_patch_example.'
        self.flags(
            monkey_patch=True,
            monkey_patch_modules=[self.example_package + 'example_a' + ':'
            + self.example_package + 'example_decorator'])

    def test_monkey_patch(self):
        utils.monkey_patch()
        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION = []
        from nova.tests.unit.monkey_patch_example import example_a
        from nova.tests.unit.monkey_patch_example import example_b

        self.assertEqual('Example function', example_a.example_function_a())
        exampleA = example_a.ExampleClassA()
        exampleA.example_method()
        ret_a = exampleA.example_method_add(3, 5)
        self.assertEqual(ret_a, 8)

        self.assertEqual('Example function', example_b.example_function_b())
        exampleB = example_b.ExampleClassB()
        exampleB.example_method()
        ret_b = exampleB.example_method_add(3, 5)

        self.assertEqual(ret_b, 8)
        package_a = self.example_package + 'example_a.'
        self.assertIn(package_a + 'example_function_a',
                      nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)

        self.assertIn(package_a + 'ExampleClassA.example_method',
                        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertIn(package_a + 'ExampleClassA.example_method_add',
                        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        package_b = self.example_package + 'example_b.'
        self.assertNotIn(package_b + 'example_function_b',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(package_b + 'ExampleClassB.example_method',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(package_b + 'ExampleClassB.example_method_add',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)


class MonkeyPatchDefaultTestCase(test.NoDBTestCase):
    """Unit test for default monkey_patch_modules value."""

    def setUp(self):
        super(MonkeyPatchDefaultTestCase, self).setUp()
        self.flags(
            monkey_patch=True)

    def test_monkey_patch_default_mod(self):
        # monkey_patch_modules is defined to be
        #    <module_to_patch>:<decorator_to_patch_with>
        #  Here we check that both parts of the default values are
        # valid
        for module in CONF.monkey_patch_modules:
            m = module.split(':', 1)
            # Check we can import the module to be patched
            importlib.import_module(m[0])
            # check the decorator is valid
            decorator_name = m[1].rsplit('.', 1)
            decorator_module = importlib.import_module(decorator_name[0])
            getattr(decorator_module, decorator_name[1])


class AuditPeriodTest(test.NoDBTestCase):

    def setUp(self):
        super(AuditPeriodTest, self).setUp()
        # a fairly random time to test with
        self.test_time = datetime.datetime(second=23,
                                           minute=12,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012)
        timeutils.set_time_override(override_time=self.test_time)

    def tearDown(self):
        timeutils.clear_time_override()
        super(AuditPeriodTest, self).tearDown()

    def test_hour(self):
        begin, end = utils.last_completed_audit_period(unit='hour')
        self.assertEqual(begin, datetime.datetime(
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@10')
        self.assertEqual(begin, datetime.datetime(
                                           minute=10,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           minute=10,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@30')
        self.assertEqual(begin, datetime.datetime(
                                           minute=30,
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           minute=30,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day(self):
        begin, end = utils.last_completed_audit_period(unit='day')
        self.assertEqual(begin, datetime.datetime(
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@6')
        self.assertEqual(begin, datetime.datetime(
                                           hour=6,
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@10')
        self.assertEqual(begin, datetime.datetime(
                                           hour=10,
                                           day=3,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=10,
                                           day=4,
                                           month=3,
                                           year=2012))

    def test_month(self):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@2')
        self.assertEqual(begin, datetime.datetime(
                                           day=2,
                                           month=2,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=2,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@15')
        self.assertEqual(begin, datetime.datetime(
                                           day=15,
                                           month=1,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=15,
                                           month=2,
                                           year=2012))

    def test_year(self):
        begin, end = utils.last_completed_audit_period(unit='year')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2011))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2012))

    def test_year_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@2')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2011))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))

    def test_year_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@6')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2010))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2011))


class MkfsTestCase(test.NoDBTestCase):

    def test_mkfs(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext4', '-F', '/my/block/dev',
                      run_as_root=False)
        utils.execute('mkfs', '-t', 'msdos', '/my/msdos/block/dev',
                      run_as_root=False)
        utils.execute('mkswap', '/my/swap/block/dev',
                      run_as_root=False)
        self.mox.ReplayAll()

        utils.mkfs('ext4', '/my/block/dev')
        utils.mkfs('msdos', '/my/msdos/block/dev')
        utils.mkfs('swap', '/my/swap/block/dev')

    def test_mkfs_with_label(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext4', '-F',
                      '-L', 'ext4-vol', '/my/block/dev', run_as_root=False)
        utils.execute('mkfs', '-t', 'msdos',
                      '-n', 'msdos-vol', '/my/msdos/block/dev',
                      run_as_root=False)
        utils.execute('mkswap', '-L', 'swap-vol', '/my/swap/block/dev',
                      run_as_root=False)
        self.mox.ReplayAll()

        utils.mkfs('ext4', '/my/block/dev', 'ext4-vol')
        utils.mkfs('msdos', '/my/msdos/block/dev', 'msdos-vol')
        utils.mkfs('swap', '/my/swap/block/dev', 'swap-vol')


class LastBytesTestCase(test.NoDBTestCase):
    """Test the last_bytes() utility method."""

    def setUp(self):
        super(LastBytesTestCase, self).setUp()
        self.f = StringIO.StringIO('1234567890')

    def test_truncated(self):
        self.f.seek(0, os.SEEK_SET)
        out, remaining = utils.last_bytes(self.f, 5)
        self.assertEqual(out, '67890')
        self.assertTrue(remaining > 0)

    def test_read_all(self):
        self.f.seek(0, os.SEEK_SET)
        out, remaining = utils.last_bytes(self.f, 1000)
        self.assertEqual(out, '1234567890')
        self.assertFalse(remaining > 0)

    def test_seek_too_far_real_file(self):
        # StringIO doesn't raise IOError if you see past the start of the file.
        flo = tempfile.TemporaryFile()
        content = '1234567890'
        flo.write(content)
        self.assertEqual((content, 0), utils.last_bytes(flo, 1000))


class IntLikeTestCase(test.NoDBTestCase):

    def test_is_int_like(self):
        self.assertTrue(utils.is_int_like(1))
        self.assertTrue(utils.is_int_like("1"))
        self.assertTrue(utils.is_int_like("514"))
        self.assertTrue(utils.is_int_like("0"))

        self.assertFalse(utils.is_int_like(1.1))
        self.assertFalse(utils.is_int_like("1.1"))
        self.assertFalse(utils.is_int_like("1.1.1"))
        self.assertFalse(utils.is_int_like(None))
        self.assertFalse(utils.is_int_like("0."))
        self.assertFalse(utils.is_int_like("aaaaaa"))
        self.assertFalse(utils.is_int_like("...."))
        self.assertFalse(utils.is_int_like("1g"))
        self.assertFalse(
            utils.is_int_like("0cc3346e-9fef-4445-abe6-5d2b2690ec64"))
        self.assertFalse(utils.is_int_like("a1"))


class MetadataToDictTestCase(test.NoDBTestCase):
    def test_metadata_to_dict(self):
        self.assertEqual(utils.metadata_to_dict(
                [{'key': 'foo1', 'value': 'bar'},
                 {'key': 'foo2', 'value': 'baz'}]),
                         {'foo1': 'bar', 'foo2': 'baz'})

    def test_metadata_to_dict_empty(self):
        self.assertEqual(utils.metadata_to_dict([]), {})

    def test_dict_to_metadata(self):
        expected = [{'key': 'foo1', 'value': 'bar1'},
                    {'key': 'foo2', 'value': 'bar2'}]
        self.assertEqual(utils.dict_to_metadata(dict(foo1='bar1',
                                                     foo2='bar2')),
                         expected)

    def test_dict_to_metadata_empty(self):
        self.assertEqual(utils.dict_to_metadata({}), [])


class WrappedCodeTestCase(test.NoDBTestCase):
    """Test the get_wrapped_function utility method."""

    def _wrapper(self, function):
        @functools.wraps(function)
        def decorated_function(self, *args, **kwargs):
            function(self, *args, **kwargs)
        return decorated_function

    def test_single_wrapped(self):
        @self._wrapper
        def wrapped(self, instance, red=None, blue=None):
            pass

        func = utils.get_wrapped_function(wrapped)
        func_code = func.func_code
        self.assertEqual(4, len(func_code.co_varnames))
        self.assertIn('self', func_code.co_varnames)
        self.assertIn('instance', func_code.co_varnames)
        self.assertIn('red', func_code.co_varnames)
        self.assertIn('blue', func_code.co_varnames)

    def test_double_wrapped(self):
        @self._wrapper
        @self._wrapper
        def wrapped(self, instance, red=None, blue=None):
            pass

        func = utils.get_wrapped_function(wrapped)
        func_code = func.func_code
        self.assertEqual(4, len(func_code.co_varnames))
        self.assertIn('self', func_code.co_varnames)
        self.assertIn('instance', func_code.co_varnames)
        self.assertIn('red', func_code.co_varnames)
        self.assertIn('blue', func_code.co_varnames)

    def test_triple_wrapped(self):
        @self._wrapper
        @self._wrapper
        @self._wrapper
        def wrapped(self, instance, red=None, blue=None):
            pass

        func = utils.get_wrapped_function(wrapped)
        func_code = func.func_code
        self.assertEqual(4, len(func_code.co_varnames))
        self.assertIn('self', func_code.co_varnames)
        self.assertIn('instance', func_code.co_varnames)
        self.assertIn('red', func_code.co_varnames)
        self.assertIn('blue', func_code.co_varnames)


class ExpectedArgsTestCase(test.NoDBTestCase):
    def test_passes(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        @dec
        def func(foo, bar, baz="lol"):
            pass

    def test_raises(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        def func(bar, baz):
            pass

        self.assertRaises(TypeError, dec, func)

    def test_var_no_of_args(self):
        @utils.expects_func_args('foo')
        def dec(f):
            return f

        @dec
        def func(bar, *args, **kwargs):
            pass

    def test_more_layers(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        def dec_2(f):
            def inner_f(*a, **k):
                return f()
            return inner_f

        @dec_2
        def func(bar, baz):
            pass

        self.assertRaises(TypeError, dec, func)


class StringLengthTestCase(test.NoDBTestCase):
    def test_check_string_length(self):
        self.assertIsNone(utils.check_string_length(
                          'test', 'name', max_length=255))
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          11, 'name', max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          '', 'name', min_length=1)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, 'name', max_length=255)

    def test_check_string_length_noname(self):
        self.assertIsNone(utils.check_string_length(
                          'test', max_length=255))
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          11, max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          '', min_length=1)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, max_length=255)


class ValidateIntegerTestCase(test.NoDBTestCase):
    def test_valid_inputs(self):
        self.assertEqual(
            utils.validate_integer(42, "answer"), 42)
        self.assertEqual(
            utils.validate_integer("42", "answer"), 42)
        self.assertEqual(
            utils.validate_integer(
                "7", "lucky", min_value=7, max_value=8), 7)
        self.assertEqual(
            utils.validate_integer(
                7, "lucky", min_value=6, max_value=7), 7)
        self.assertEqual(
            utils.validate_integer(
                300, "Spartaaa!!!", min_value=300), 300)
        self.assertEqual(
            utils.validate_integer(
                "300", "Spartaaa!!!", max_value=300), 300)

    def test_invalid_inputs(self):
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          "im-not-an-int", "not-an-int")
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          3.14, "Pie")
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          "299", "Sparta no-show",
                          min_value=300, max_value=300)
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          55, "doing 55 in a 54",
                          max_value=54)
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          unichr(129), "UnicodeError",
                          max_value=1000)


class ValidateNeutronConfiguration(test.NoDBTestCase):
    def test_nova_network(self):
        self.assertFalse(utils.is_neutron())

    def test_neutron(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        self.assertTrue(utils.is_neutron())

    def test_quantum(self):
        self.flags(network_api_class='nova.network.quantumv2.api.API')
        self.assertTrue(utils.is_neutron())


class AutoDiskConfigUtilTestCase(test.NoDBTestCase):
    def test_is_auto_disk_config_disabled(self):
        self.assertTrue(utils.is_auto_disk_config_disabled("Disabled "))

    def test_is_auto_disk_config_disabled_none(self):
        self.assertFalse(utils.is_auto_disk_config_disabled(None))

    def test_is_auto_disk_config_disabled_false(self):
        self.assertFalse(utils.is_auto_disk_config_disabled("false"))


class GetSystemMetadataFromImageTestCase(test.NoDBTestCase):
    def get_image(self):
        image_meta = {
            "id": "fake-image",
            "name": "fake-name",
            "min_ram": 1,
            "min_disk": 1,
            "disk_format": "raw",
            "container_format": "bare",
        }

        return image_meta

    def get_flavor(self):
        flavor = {
            "id": "fake.flavor",
            "root_gb": 10,
        }

        return flavor

    def test_base_image_properties(self):
        image = self.get_image()

        # Verify that we inherit all the needed keys
        sys_meta = utils.get_system_metadata_from_image(image)
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image[key], sys_meta.get(sys_key))

        # Verify that everything else is ignored
        self.assertEqual(len(sys_meta), len(utils.SM_INHERITABLE_KEYS))

    def test_inherit_image_properties(self):
        image = self.get_image()
        image["properties"] = {"foo1": "bar", "foo2": "baz"}

        sys_meta = utils.get_system_metadata_from_image(image)

        # Verify that we inherit all the image properties
        for key, expected in image["properties"].iteritems():
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(sys_meta[sys_key], expected)

    def test_vhd_min_disk_image(self):
        image = self.get_image()
        flavor = self.get_flavor()

        image["disk_format"] = "vhd"

        sys_meta = utils.get_system_metadata_from_image(image, flavor)

        # Verify that the min_disk property is taken from
        # flavor's root_gb when using vhd disk format
        sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, "min_disk")
        self.assertEqual(sys_meta[sys_key], flavor["root_gb"])

    def test_dont_inherit_empty_values(self):
        image = self.get_image()

        for key in utils.SM_INHERITABLE_KEYS:
            image[key] = None

        sys_meta = utils.get_system_metadata_from_image(image)

        # Verify that the empty properties have not been inherited
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertNotIn(sys_key, sys_meta)


class GetImageFromSystemMetadataTestCase(test.NoDBTestCase):
    def get_system_metadata(self):
        sys_meta = {
            "image_min_ram": 1,
            "image_min_disk": 1,
            "image_disk_format": "raw",
            "image_container_format": "bare",
        }

        return sys_meta

    def test_image_from_system_metadata(self):
        sys_meta = self.get_system_metadata()
        sys_meta["%soo1" % utils.SM_IMAGE_PROP_PREFIX] = "bar"
        sys_meta["%soo2" % utils.SM_IMAGE_PROP_PREFIX] = "baz"

        image = utils.get_image_from_system_metadata(sys_meta)

        # Verify that we inherit all the needed keys
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image[key], sys_meta.get(sys_key))

        # Verify that we inherit the rest of metadata as properties
        self.assertIn("properties", image)

        for key, value in image["properties"].iteritems():
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image["properties"][key], sys_meta[sys_key])

    def test_dont_inherit_empty_values(self):
        sys_meta = self.get_system_metadata()

        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            sys_meta[sys_key] = None

        image = utils.get_image_from_system_metadata(sys_meta)

        # Verify that the empty properties have not been inherited
        for key in utils.SM_INHERITABLE_KEYS:
            self.assertNotIn(key, image)

    def test_non_inheritable_image_properties(self):
        sys_meta = self.get_system_metadata()
        sys_meta["%soo1" % utils.SM_IMAGE_PROP_PREFIX] = "bar"

        self.flags(non_inheritable_image_properties=["foo1"])

        image = utils.get_image_from_system_metadata(sys_meta)

        # Verify that the foo1 key has not been inherited
        self.assertNotIn("foo1", image)


class VersionTestCase(test.NoDBTestCase):
    def test_convert_version_to_int(self):
        self.assertEqual(utils.convert_version_to_int('6.2.0'), 6002000)
        self.assertEqual(utils.convert_version_to_int((6, 4, 3)), 6004003)
        self.assertEqual(utils.convert_version_to_int((5, )), 5)
        self.assertRaises(exception.NovaException,
                          utils.convert_version_to_int, '5a.6b')

    def test_convert_version_to_string(self):
        self.assertEqual(utils.convert_version_to_str(6007000), '6.7.0')
        self.assertEqual(utils.convert_version_to_str(4), '4')

    def test_convert_version_to_tuple(self):
        self.assertEqual(utils.convert_version_to_tuple('6.7.0'), (6, 7, 0))


class ConstantTimeCompareTestCase(test.NoDBTestCase):
    def test_constant_time_compare(self):
        self.assertTrue(utils.constant_time_compare("abcd1234", "abcd1234"))
        self.assertFalse(utils.constant_time_compare("abcd1234", "a"))
        self.assertFalse(utils.constant_time_compare("abcd1234", "ABCD234"))


class ResourceFilterTestCase(test.NoDBTestCase):
    def _assert_filtering(self, res_list, filts, expected_tags):
        actual_tags = utils.filter_and_format_resource_metadata('instance',
                res_list, filts, 'metadata')
        self.assertEqual(expected_tags, actual_tags)

    def test_filter_and_format_resource_metadata(self):
        # Create some tags
        # One overlapping pair, and one different key value pair
        # i1 : foo=bar, bax=wibble
        # i2 : foo=bar, baz=quux

        # resources
        i1 = {
                'uuid': '1',
                'metadata': {'foo': 'bar', 'bax': 'wibble'},
            }
        i2 = {
                'uuid': '2',
                'metadata': {'foo': 'bar', 'baz': 'quux'},
            }

        # Resources list
        rl = [i1, i2]

        # tags
        i11 = {'instance_id': '1', 'key': 'foo', 'value': 'bar'}
        i12 = {'instance_id': '1', 'key': 'bax', 'value': 'wibble'}
        i21 = {'instance_id': '2', 'key': 'foo', 'value': 'bar'}
        i22 = {'instance_id': '2', 'key': 'baz', 'value': 'quux'}

        # No filter
        self._assert_filtering(rl, [], [i11, i12, i21, i22])
        self._assert_filtering(rl, {}, [i11, i12, i21, i22])

        # Key search

        # Both should have tags with key 'foo' and value 'bar'
        self._assert_filtering(rl, {'key': 'foo', 'value': 'bar'}, [i11, i21])

        # Both should have tags with key 'foo'
        self._assert_filtering(rl, {'key': 'foo'}, [i11, i21])

        # Only i2 should have tags with key 'baz' and value 'quux'
        self._assert_filtering(rl, {'key': 'baz', 'value': 'quux'}, [i22])

        # Only i2 should have tags with value 'quux'
        self._assert_filtering(rl, {'value': 'quux'}, [i22])

        # Empty list should be returned when no tags match
        self._assert_filtering(rl, {'key': 'split', 'value': 'banana'}, [])

        # Multiple values

        # Only i2 should have tags with key 'baz' and values in the set
        # ['quux', 'wibble']
        self._assert_filtering(rl, {'key': 'baz', 'value': ['quux', 'wibble']},
                [i22])

        # But when specified as two different filters, no tags should be
        # returned. This is because, the filter will mean "return tags which
        # have (key=baz AND value=quux) AND (key=baz AND value=wibble)
        self._assert_filtering(rl, [{'key': 'baz', 'value': 'quux'},
            {'key': 'baz', 'value': 'wibble'}], [])

        # Test for regex
        self._assert_filtering(rl, {'value': '\\Aqu..*\\Z(?s)'}, [i22])

        # Make sure bug #1365887 is fixed
        i1['metadata']['key3'] = 'a'
        self._assert_filtering(rl, {'value': 'banana'}, [])

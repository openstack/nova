# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import __builtin__
import datetime
import functools
import hashlib
import importlib
import os
import os.path
import StringIO
import tempfile

import mox
import netaddr
from oslo.config import cfg

import nova
from nova import exception
from nova.openstack.common import timeutils
from nova import test
from nova import utils

CONF = cfg.CONF


class ByteConversionTest(test.TestCase):
    def test_string_conversions(self):
        working_examples = {
            '1024KB': 1048576,
            '1024TB': 1125899906842624,
            '1024K': 1048576,
            '1024T': 1125899906842624,
            '1TB': 1099511627776,
            '1T': 1099511627776,
            '1KB': 1024,
            '1K': 1024,
            '1B': 1,
            '1B': 1,
            '1': 1,
            '1MB': 1048576,
            '7MB': 7340032,
            '0MB': 0,
            '0KB': 0,
            '0TB': 0,
            '': 0,
        }
        for (in_value, expected_value) in working_examples.items():
            b_value = utils.to_bytes(in_value)
            self.assertEquals(expected_value, b_value)
            if len(in_value):
                in_value = "-" + in_value
                b_value = utils.to_bytes(in_value)
                self.assertEquals(expected_value * -1, b_value)
        breaking_examples = [
            'junk1KB', '1023BBBB',
        ]
        for v in breaking_examples:
            self.assertRaises(TypeError, utils.to_bytes, v)


class ExecuteTestCase(test.TestCase):

    def test_retry_on_failure(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If stdin fails to get passed during one of the runs, make a note.
if ! grep -q foo
then
    echo 'failure' > "$1"
fi
# If stdin has failed to get passed during this or a previous run, exit early.
if grep failure "$1"
then
    exit 1
fi
runs="$(cat $1)"
if [ -z "$runs" ]
then
    runs=0
fi
runs=$(($runs + 1))
echo $runs > "$1"
exit 1
''')
            fp.close()
            os.chmod(tmpfilename, 0755)
            self.assertRaises(exception.ProcessExecutionError,
                              utils.execute,
                              tmpfilename, tmpfilename2, attempts=10,
                              process_input='foo',
                              delay_on_retry=False)
            fp = open(tmpfilename2, 'r')
            runs = fp.read()
            fp.close()
            self.assertNotEquals(runs.strip(), 'failure', 'stdin did not '
                                                          'always get passed '
                                                          'correctly')
            runs = int(runs.strip())
            self.assertEquals(runs, 10,
                              'Ran %d times instead of 10.' % (runs,))
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

    def test_unknown_kwargs_raises_error(self):
        self.assertRaises(exception.NovaException,
                          utils.execute,
                          '/usr/bin/env', 'true',
                          this_is_not_a_valid_kwarg=True)

    def test_check_exit_code_boolean(self):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        self.assertRaises(exception.ProcessExecutionError,
                          utils.execute,
                          '/usr/bin/env', 'false', check_exit_code=True)

    def test_no_retry_on_success(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If we've already run, bail out.
grep -q foo "$1" && exit 1
# Mark that we've run before.
echo foo > "$1"
# Check that stdin gets passed correctly.
grep foo
''')
            fp.close()
            os.chmod(tmpfilename, 0755)
            utils.execute(tmpfilename,
                          tmpfilename2,
                          process_input='foo',
                          attempts=2)
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)


class GetFromPathTestCase(test.TestCase):
    def test_tolerates_nones(self):
        f = utils.get_from_path

        input = []
        self.assertEquals([], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [None]
        self.assertEquals([], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': None}]
        self.assertEquals([], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': None}}]
        self.assertEquals([{'b': None}], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}]
        self.assertEquals([{'b': {'c': None}}], f(input, "a"))
        self.assertEquals([{'c': None}], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': None}]
        self.assertEquals([{'b': {'c': None}}], f(input, "a"))
        self.assertEquals([{'c': None}], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': {'b': None}}]
        self.assertEquals([{'b': {'c': None}}, {'b': None}], f(input, "a"))
        self.assertEquals([{'c': None}], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

    def test_does_select(self):
        f = utils.get_from_path

        input = [{'a': 'a_1'}]
        self.assertEquals(['a_1'], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': 'b_1'}}]
        self.assertEquals([{'b': 'b_1'}], f(input, "a"))
        self.assertEquals(['b_1'], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}]
        self.assertEquals([{'b': {'c': 'c_1'}}], f(input, "a"))
        self.assertEquals([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEquals(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}, {'a': None}]
        self.assertEquals([{'b': {'c': 'c_1'}}], f(input, "a"))
        self.assertEquals([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEquals(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': None}}]
        self.assertEquals([{'b': {'c': 'c_1'}}, {'b': None}], f(input, "a"))
        self.assertEquals([{'c': 'c_1'}], f(input, "a/b"))
        self.assertEquals(['c_1'], f(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': {'c': 'c_2'}}}]
        self.assertEquals([{'b': {'c': 'c_1'}}, {'b': {'c': 'c_2'}}],
                          f(input, "a"))
        self.assertEquals([{'c': 'c_1'}, {'c': 'c_2'}], f(input, "a/b"))
        self.assertEquals(['c_1', 'c_2'], f(input, "a/b/c"))

        self.assertEquals([], f(input, "a/b/c/d"))
        self.assertEquals([], f(input, "c/a/b/d"))
        self.assertEquals([], f(input, "i/r/t"))

    def test_flattens_lists(self):
        f = utils.get_from_path

        input = [{'a': [1, 2, 3]}]
        self.assertEquals([1, 2, 3], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}]
        self.assertEquals([{'b': [1, 2, 3]}], f(input, "a"))
        self.assertEquals([1, 2, 3], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}, {'a': {'b': [4, 5, 6]}}]
        self.assertEquals([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': [{'b': [1, 2, 3]}, {'b': [4, 5, 6]}]}]
        self.assertEquals([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = [{'a': [1, 2, {'b': 'b_1'}]}]
        self.assertEquals([1, 2, {'b': 'b_1'}], f(input, "a"))
        self.assertEquals(['b_1'], f(input, "a/b"))

    def test_bad_xpath(self):
        f = utils.get_from_path

        self.assertRaises(exception.NovaException, f, [], None)
        self.assertRaises(exception.NovaException, f, [], "")
        self.assertRaises(exception.NovaException, f, [], "/")
        self.assertRaises(exception.NovaException, f, [], "/a")
        self.assertRaises(exception.NovaException, f, [], "/a/")
        self.assertRaises(exception.NovaException, f, [], "//")
        self.assertRaises(exception.NovaException, f, [], "//a")
        self.assertRaises(exception.NovaException, f, [], "a//a")
        self.assertRaises(exception.NovaException, f, [], "a//a/")
        self.assertRaises(exception.NovaException, f, [], "a/a/")

    def test_real_failure1(self):
        # Real world failure case...
        #  We weren't coping when the input was a Dictionary instead of a List
        # This led to test_accepts_dictionaries
        f = utils.get_from_path

        inst = {'fixed_ip': {'floating_ips': [{'address': '1.2.3.4'}],
                             'address': '192.168.0.3'},
                'hostname': ''}

        private_ips = f(inst, 'fixed_ip/address')
        public_ips = f(inst, 'fixed_ip/floating_ips/address')
        self.assertEquals(['192.168.0.3'], private_ips)
        self.assertEquals(['1.2.3.4'], public_ips)

    def test_accepts_dictionaries(self):
        f = utils.get_from_path

        input = {'a': [1, 2, 3]}
        self.assertEquals([1, 2, 3], f(input, "a"))
        self.assertEquals([], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = {'a': {'b': [1, 2, 3]}}
        self.assertEquals([{'b': [1, 2, 3]}], f(input, "a"))
        self.assertEquals([1, 2, 3], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = {'a': [{'b': [1, 2, 3]}, {'b': [4, 5, 6]}]}
        self.assertEquals([1, 2, 3, 4, 5, 6], f(input, "a/b"))
        self.assertEquals([], f(input, "a/b/c"))

        input = {'a': [1, 2, {'b': 'b_1'}]}
        self.assertEquals([1, 2, {'b': 'b_1'}], f(input, "a"))
        self.assertEquals(['b_1'], f(input, "a/b"))


class GenericUtilsTestCase(test.TestCase):
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

    def test_bool_from_str(self):
        self.assertTrue(utils.bool_from_str('1'))
        self.assertTrue(utils.bool_from_str('2'))
        self.assertTrue(utils.bool_from_str('-1'))
        self.assertTrue(utils.bool_from_str('true'))
        self.assertTrue(utils.bool_from_str('True'))
        self.assertTrue(utils.bool_from_str('tRuE'))
        self.assertTrue(utils.bool_from_str('yes'))
        self.assertTrue(utils.bool_from_str('Yes'))
        self.assertTrue(utils.bool_from_str('YeS'))
        self.assertTrue(utils.bool_from_str('y'))
        self.assertTrue(utils.bool_from_str('Y'))
        self.assertFalse(utils.bool_from_str('False'))
        self.assertFalse(utils.bool_from_str('false'))
        self.assertFalse(utils.bool_from_str('no'))
        self.assertFalse(utils.bool_from_str('No'))
        self.assertFalse(utils.bool_from_str('n'))
        self.assertFalse(utils.bool_from_str('N'))
        self.assertFalse(utils.bool_from_str('0'))
        self.assertFalse(utils.bool_from_str(None))
        self.assertFalse(utils.bool_from_str('junk'))

    def test_read_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        os.path.getmtime(mox.IgnoreArg()).AndReturn(1)
        self.mox.ReplayAll()

        cache_data = {"data": 1123, "mtime": 1}
        data = utils.read_cached_file("/this/is/a/fake", cache_data)
        self.assertEqual(cache_data["data"], data)

    def test_read_modified_cached_file(self):
        self.mox.StubOutWithMock(os.path, "getmtime")
        self.mox.StubOutWithMock(__builtin__, 'open')
        os.path.getmtime(mox.IgnoreArg()).AndReturn(2)

        fake_contents = "lorem ipsum"
        fake_file = self.mox.CreateMockAnything()
        fake_file.read().AndReturn(fake_contents)
        fake_context_manager = self.mox.CreateMockAnything()
        fake_context_manager.__enter__().AndReturn(fake_file)
        fake_context_manager.__exit__(mox.IgnoreArg(),
                                      mox.IgnoreArg(),
                                      mox.IgnoreArg())

        __builtin__.open(mox.IgnoreArg()).AndReturn(fake_context_manager)

        self.mox.ReplayAll()
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
                raise exception.ProcessExecutionError
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

    def test_hash_file(self):
        data = 'Mary had a little lamb, its fleece as white as snow'
        flo = StringIO.StringIO(data)
        h1 = utils.hash_file(flo)
        h2 = hashlib.sha1(data).hexdigest()
        self.assertEquals(h1, h2)

    def test_is_valid_boolstr(self):
        self.assertTrue(utils.is_valid_boolstr('true'))
        self.assertTrue(utils.is_valid_boolstr('false'))
        self.assertTrue(utils.is_valid_boolstr('yes'))
        self.assertTrue(utils.is_valid_boolstr('no'))
        self.assertTrue(utils.is_valid_boolstr('y'))
        self.assertTrue(utils.is_valid_boolstr('n'))
        self.assertTrue(utils.is_valid_boolstr('1'))
        self.assertTrue(utils.is_valid_boolstr('0'))

        self.assertFalse(utils.is_valid_boolstr('maybe'))
        self.assertFalse(utils.is_valid_boolstr('only on tuesdays'))

    def test_is_valid_ipv4(self):
        self.assertTrue(utils.is_valid_ipv4('127.0.0.1'))
        self.assertFalse(utils.is_valid_ipv4('::1'))
        self.assertFalse(utils.is_valid_ipv4('bacon'))
        self.assertFalse(utils.is_valid_ipv4(""))
        self.assertFalse(utils.is_valid_ipv4(10))

    def test_is_valid_ipv6(self):
        self.assertTrue(utils.is_valid_ipv6("::1"))
        self.assertTrue(utils.is_valid_ipv6(
                            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertTrue(utils.is_valid_ipv6(
                                    "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertFalse(utils.is_valid_ipv6("foo"))
        self.assertFalse(utils.is_valid_ipv6("127.0.0.1"))
        self.assertFalse(utils.is_valid_ipv6(""))
        self.assertFalse(utils.is_valid_ipv6(10))

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
        self.assertEquals("abcd:ef01:2345:6789:abcd:ef01:c0a8:fefe",
                          utils.get_shortened_ipv6(
                            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertEquals("::1", utils.get_shortened_ipv6(
                                    "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertEquals("caca::caca:0:babe:201:102",
                          utils.get_shortened_ipv6(
                                    "caca:0000:0000:caca:0000:babe:0201:0102"))
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "failure")

    def test_get_shortened_ipv6_cidr(self):
        self.assertEquals("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600:0000:0000:0000:0000:0000:0000:0000/64"))
        self.assertEquals("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600::1/64"))
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "failure")


class MonkeyPatchTestCase(test.TestCase):
    """Unit test for utils.monkey_patch()."""
    def setUp(self):
        super(MonkeyPatchTestCase, self).setUp()
        self.example_package = 'nova.tests.monkey_patch_example.'
        self.flags(
            monkey_patch=True,
            monkey_patch_modules=[self.example_package + 'example_a' + ':'
            + self.example_package + 'example_decorator'])

    def test_monkey_patch(self):
        utils.monkey_patch()
        nova.tests.monkey_patch_example.CALLED_FUNCTION = []
        from nova.tests.monkey_patch_example import example_a
        from nova.tests.monkey_patch_example import example_b

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
        self.assertTrue(package_a + 'example_function_a'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)

        self.assertTrue(package_a + 'ExampleClassA.example_method'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertTrue(package_a + 'ExampleClassA.example_method_add'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)
        package_b = self.example_package + 'example_b.'
        self.assertFalse(package_b + 'example_function_b'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertFalse(package_b + 'ExampleClassB.example_method'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)
        self.assertFalse(package_b + 'ExampleClassB.example_method_add'
            in nova.tests.monkey_patch_example.CALLED_FUNCTION)


class MonkeyPatchDefaultTestCase(test.TestCase):
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


class AuditPeriodTest(test.TestCase):

    def setUp(self):
        super(AuditPeriodTest, self).setUp()
        #a fairly random time to test with
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
        self.assertEquals(begin, datetime.datetime(
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@10')
        self.assertEquals(begin, datetime.datetime(
                                           minute=10,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           minute=10,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@30')
        self.assertEquals(begin, datetime.datetime(
                                           minute=30,
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           minute=30,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day(self):
        begin, end = utils.last_completed_audit_period(unit='day')
        self.assertEquals(begin, datetime.datetime(
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@6')
        self.assertEquals(begin, datetime.datetime(
                                           hour=6,
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@10')
        self.assertEquals(begin, datetime.datetime(
                                           hour=10,
                                           day=3,
                                           month=3,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           hour=10,
                                           day=4,
                                           month=3,
                                           year=2012))

    def test_month(self):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEquals(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           day=1,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@2')
        self.assertEquals(begin, datetime.datetime(
                                           day=2,
                                           month=2,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           day=2,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@15')
        self.assertEquals(begin, datetime.datetime(
                                           day=15,
                                           month=1,
                                           year=2012))
        self.assertEquals(end, datetime.datetime(
                                           day=15,
                                           month=2,
                                           year=2012))

    def test_year(self):
        begin, end = utils.last_completed_audit_period(unit='year')
        self.assertEquals(begin, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2011))
        self.assertEquals(end, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2012))

    def test_year_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@2')
        self.assertEquals(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2011))
        self.assertEquals(end, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))

    def test_year_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@6')
        self.assertEquals(begin, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2010))
        self.assertEquals(end, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2011))


class DiffDict(test.TestCase):
    """Unit tests for diff_dict()."""

    def test_no_change(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=2, c=3)
        diff = utils.diff_dict(old, new)

        self.assertEqual(diff, {})

    def test_new_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=2, c=3, d=4)
        diff = utils.diff_dict(old, new)

        self.assertEqual(diff, dict(d=['+', 4]))

    def test_changed_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, b=4, c=3)
        diff = utils.diff_dict(old, new)

        self.assertEqual(diff, dict(b=['+', 4]))

    def test_removed_key(self):
        old = dict(a=1, b=2, c=3)
        new = dict(a=1, c=3)
        diff = utils.diff_dict(old, new)

        self.assertEqual(diff, dict(b=['-']))


class MkfsTestCase(test.TestCase):

    def test_mkfs(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext4', '-F', '/my/block/dev')
        utils.execute('mkfs', '-t', 'msdos', '/my/msdos/block/dev')
        utils.execute('mkswap', '/my/swap/block/dev')
        self.mox.ReplayAll()

        utils.mkfs('ext4', '/my/block/dev')
        utils.mkfs('msdos', '/my/msdos/block/dev')
        utils.mkfs('swap', '/my/swap/block/dev')

    def test_mkfs_with_label(self):
        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('mkfs', '-t', 'ext4', '-F',
                      '-L', 'ext4-vol', '/my/block/dev')
        utils.execute('mkfs', '-t', 'msdos',
                      '-n', 'msdos-vol', '/my/msdos/block/dev')
        utils.execute('mkswap', '-L', 'swap-vol', '/my/swap/block/dev')
        self.mox.ReplayAll()

        utils.mkfs('ext4', '/my/block/dev', 'ext4-vol')
        utils.mkfs('msdos', '/my/msdos/block/dev', 'msdos-vol')
        utils.mkfs('swap', '/my/swap/block/dev', 'swap-vol')


class LastBytesTestCase(test.TestCase):
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


class IntLikeTestCase(test.TestCase):

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


class MetadataToDictTestCase(test.TestCase):
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


class WrappedCodeTestCase(test.TestCase):
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
        self.assertTrue('self' in func_code.co_varnames)
        self.assertTrue('instance' in func_code.co_varnames)
        self.assertTrue('red' in func_code.co_varnames)
        self.assertTrue('blue' in func_code.co_varnames)

    def test_double_wrapped(self):
        @self._wrapper
        @self._wrapper
        def wrapped(self, instance, red=None, blue=None):
            pass

        func = utils.get_wrapped_function(wrapped)
        func_code = func.func_code
        self.assertEqual(4, len(func_code.co_varnames))
        self.assertTrue('self' in func_code.co_varnames)
        self.assertTrue('instance' in func_code.co_varnames)
        self.assertTrue('red' in func_code.co_varnames)
        self.assertTrue('blue' in func_code.co_varnames)

    def test_triple_wrapped(self):
        @self._wrapper
        @self._wrapper
        @self._wrapper
        def wrapped(self, instance, red=None, blue=None):
            pass

        func = utils.get_wrapped_function(wrapped)
        func_code = func.func_code
        self.assertEqual(4, len(func_code.co_varnames))
        self.assertTrue('self' in func_code.co_varnames)
        self.assertTrue('instance' in func_code.co_varnames)
        self.assertTrue('red' in func_code.co_varnames)
        self.assertTrue('blue' in func_code.co_varnames)


class StringLengthTestCase(test.TestCase):
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

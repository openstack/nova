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

import datetime
import os
import tempfile

import nova
from nova import exception
from nova import test
from nova import utils


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
            fp = open(tmpfilename2, 'r+')
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
        self.assertRaises(exception.Error,
                          utils.execute,
                          '/bin/true', this_is_not_a_valid_kwarg=True)

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

        self.assertRaises(exception.Error, f, [], None)
        self.assertRaises(exception.Error, f, [], "")
        self.assertRaises(exception.Error, f, [], "/")
        self.assertRaises(exception.Error, f, [], "/a")
        self.assertRaises(exception.Error, f, [], "/a/")
        self.assertRaises(exception.Error, f, [], "//")
        self.assertRaises(exception.Error, f, [], "//a")
        self.assertRaises(exception.Error, f, [], "a//a")
        self.assertRaises(exception.Error, f, [], "a//a/")
        self.assertRaises(exception.Error, f, [], "a/a/")

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

    def test_bool_from_str(self):
        self.assertTrue(utils.bool_from_str('1'))
        self.assertTrue(utils.bool_from_str('2'))
        self.assertTrue(utils.bool_from_str('-1'))
        self.assertTrue(utils.bool_from_str('true'))
        self.assertTrue(utils.bool_from_str('True'))
        self.assertTrue(utils.bool_from_str('tRuE'))
        self.assertFalse(utils.bool_from_str('False'))
        self.assertFalse(utils.bool_from_str('false'))
        self.assertFalse(utils.bool_from_str('0'))
        self.assertFalse(utils.bool_from_str(None))
        self.assertFalse(utils.bool_from_str('junk'))


class IsUUIDLikeTestCase(test.TestCase):
    def assertUUIDLike(self, val, expected):
        result = utils.is_uuid_like(val)
        self.assertEqual(result, expected)

    def test_good_uuid(self):
        val = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        self.assertUUIDLike(val, True)

    def test_integer_passed(self):
        val = 1
        self.assertUUIDLike(val, False)

    def test_non_uuid_string_passed(self):
        val = 'foo-fooo'
        self.assertUUIDLike(val, False)


class ToPrimitiveTestCase(test.TestCase):
    def test_list(self):
        self.assertEquals(utils.to_primitive([1, 2, 3]), [1, 2, 3])

    def test_empty_list(self):
        self.assertEquals(utils.to_primitive([]), [])

    def test_tuple(self):
        self.assertEquals(utils.to_primitive((1, 2, 3)), [1, 2, 3])

    def test_dict(self):
        self.assertEquals(utils.to_primitive(dict(a=1, b=2, c=3)),
                          dict(a=1, b=2, c=3))

    def test_empty_dict(self):
        self.assertEquals(utils.to_primitive({}), {})

    def test_datetime(self):
        x = datetime.datetime(1, 2, 3, 4, 5, 6, 7)
        self.assertEquals(utils.to_primitive(x), "0001-02-03 04:05:06.000007")

    def test_iter(self):
        class IterClass(object):
            def __init__(self):
                self.data = [1, 2, 3, 4, 5]
                self.index = 0

            def __iter__(self):
                return self

            def next(self):
                if self.index == len(self.data):
                    raise StopIteration
                self.index = self.index + 1
                return self.data[self.index - 1]

        x = IterClass()
        self.assertEquals(utils.to_primitive(x), [1, 2, 3, 4, 5])

    def test_iteritems(self):
        class IterItemsClass(object):
            def __init__(self):
                self.data = dict(a=1, b=2, c=3).items()
                self.index = 0

            def __iter__(self):
                return self

            def next(self):
                if self.index == len(self.data):
                    raise StopIteration
                self.index = self.index + 1
                return self.data[self.index - 1]

        x = IterItemsClass()
        ordered = utils.to_primitive(x)
        ordered.sort()
        self.assertEquals(ordered, [['a', 1], ['b', 2], ['c', 3]])

    def test_instance(self):
        class MysteryClass(object):
            a = 10

            def __init__(self):
                self.b = 1

        x = MysteryClass()
        self.assertEquals(utils.to_primitive(x, convert_instances=True),
                          dict(b=1))

        self.assertEquals(utils.to_primitive(x), x)

    def test_typeerror(self):
        x = bytearray  # Class, not instance
        self.assertEquals(utils.to_primitive(x), u"<type 'bytearray'>")

    def test_nasties(self):
        def foo():
            pass
        x = [datetime, foo, dir]
        ret = utils.to_primitive(x)
        self.assertEquals(len(ret), 3)
        self.assertTrue(ret[0].startswith(u"<module 'datetime' from "))
        self.assertTrue(ret[1].startswith(u'<function foo at 0x'))
        self.assertEquals(ret[2], u'<built-in function dir>')


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
        from nova.tests.monkey_patch_example import example_a, example_b

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

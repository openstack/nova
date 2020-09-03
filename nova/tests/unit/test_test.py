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

"""Tests for the testing base code."""

import os.path
import tempfile
import uuid

import mock
from oslo_log import log as logging
import oslo_messaging as messaging
import six

import nova.conf
from nova import exception
from nova import rpc
from nova import test
from nova.tests import fixtures

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class IsolationTestCase(test.TestCase):
    """Ensure that things are cleaned up after failed tests.

    These tests don't really do much here, but if isolation fails a bunch
    of other tests should fail.

    """
    def test_service_isolation(self):
        self.useFixture(fixtures.ServiceFixture('compute'))

    def test_rpc_consumer_isolation(self):
        class NeverCalled(object):

            def __getattribute__(self, name):
                if name == 'target' or name == 'oslo_rpc_server_ping':
                    # oslo.messaging 5.31.0 explicitly looks for 'target'
                    # on the endpoint and checks it's type, so we can't avoid
                    # it here, just ignore it if that's the case.
                    return
                assert False, "I should never get called. name: %s" % name

        server = rpc.get_server(messaging.Target(topic='compute',
                                                 server=CONF.host),
                                endpoints=[NeverCalled()])
        server.start()


class JsonTestCase(test.NoDBTestCase):
    def test_compare_dict_string(self):
        expected = {
            "employees": [
                {"firstName": "Anna", "lastName": "Smith"},
                {"firstName": "John", "lastName": "Doe"},
                {"firstName": "Peter", "lastName": "Jones"}
            ],
            "locations": set(['Boston', 'Mumbai', 'Beijing', 'Perth'])
        }
        actual = """{
    "employees": [
        {
            "lastName": "Doe",
            "firstName": "John"
        },
        {
            "lastName": "Smith",
            "firstName": "Anna"
        },
        {
            "lastName": "Jones",
            "firstName": "Peter"
        }
    ],
    "locations": [
        "Perth",
        "Boston",
        "Mumbai",
        "Beijing"
    ]
}"""
        self.assertJsonEqual(expected, actual)

    def test_fail_on_list_length(self):
        expected = {
            'top': {
                'l1': {
                    'l2': ['a', 'b', 'c']
                }
            }
        }
        actual = {
            'top': {
                'l1': {
                    'l2': ['c', 'a', 'b', 'd']
                }
            }
        }
        try:
            self.assertJsonEqual(expected, actual)
        except Exception as e:
            # error reported is going to be a cryptic length failure
            # on the level2 structure.
            self.assertEqual(
                ("3 != 4: path: root.top.l1.l2. Different list items\n"
                 "expected=['a', 'b', 'c']\n"
                 "observed=['a', 'b', 'c', 'd']\n"
                 "difference=['d']"),
                e.difference)
            self.assertIn(
                "actual:\n{'top': {'l1': {'l2': ['c', 'a', 'b', 'd']}}}",
                six.text_type(e))
            self.assertIn(
                "expected:\n{'top': {'l1': {'l2': ['a', 'b', 'c']}}}",
                six.text_type(e))
        else:
            self.fail("This should have raised a mismatch exception")

    def test_fail_on_dict_length(self):
        expected = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2, 'c': 3}
                }
            }
        }
        actual = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2}
                }
            }
        }
        try:
            self.assertJsonEqual(expected, actual)
        except Exception as e:
            self.assertEqual(
                ("3 != 2: path: root.top.l1.l2. Different dict key sets\n"
                 "expected=['a', 'b', 'c']\n"
                 "observed=['a', 'b']\n"
                 "difference=['c']"),
                e.difference)
        else:
            self.fail("This should have raised a mismatch exception")

    def test_fail_on_dict_keys(self):
        expected = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2, 'c': 3}
                }
            }
        }
        actual = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2, 'd': 3}
                }
            }
        }
        try:
            self.assertJsonEqual(expected, actual)
        except Exception as e:
            self.assertIn(
                "path: root.top.l1.l2. Dict keys are not equal",
                e.difference)
        else:
            self.fail("This should have raised a mismatch exception")

    def test_fail_on_list_value(self):
        expected = {
            'top': {
                'l1': {
                    'l2': ['a', 'b', 'c']
                }
            }
        }
        actual = {
            'top': {
                'l1': {
                    'l2': ['c', 'a', 'd']
                }
            }
        }
        try:
            self.assertJsonEqual(expected, actual)
        except Exception as e:
            self.assertEqual(
                "'b' != 'c': path: root.top.l1.l2[1]",
                e.difference)
            self.assertIn(
                "actual:\n{'top': {'l1': {'l2': ['c', 'a', 'd']}}}",
                six.text_type(e))
            self.assertIn(
                "expected:\n{'top': {'l1': {'l2': ['a', 'b', 'c']}}}",
                six.text_type(e))
        else:
            self.fail("This should have raised a mismatch exception")

    def test_fail_on_dict_value(self):
        expected = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2, 'c': 3}
                }
            }
        }
        actual = {
            'top': {
                'l1': {
                    'l2': {'a': 1, 'b': 2, 'c': 4}
                }
            }
        }
        try:
            self.assertJsonEqual(expected, actual, 'test message')
        except Exception as e:
            self.assertEqual(
                "3 != 4: path: root.top.l1.l2.c", e.difference)
            self.assertIn("actual:\n{'top': {'l1': {'l2': {", six.text_type(e))
            self.assertIn(
                "expected:\n{'top': {'l1': {'l2': {", six.text_type(e))
            self.assertIn(
                "message: test message\n", six.text_type(e))
        else:
            self.fail("This should have raised a mismatch exception")

    def test_compare_scalars(self):
        with self.assertRaisesRegex(AssertionError, 'True != False'):
            self.assertJsonEqual(True, False)


class BadLogTestCase(test.NoDBTestCase):
    """Make sure a mis-formatted debug log will get caught."""

    def test_bad_debug_log(self):
        self.assertRaises(KeyError,
            LOG.debug, "this is a misformated %(log)s", {'nothing': 'nothing'})


class MatchTypeTestCase(test.NoDBTestCase):

    def test_match_type_simple(self):
        matcher = test.MatchType(dict)

        self.assertEqual(matcher, {})
        self.assertEqual(matcher, {"hello": "world"})
        self.assertEqual(matcher, {"hello": ["world"]})
        self.assertNotEqual(matcher, [])
        self.assertNotEqual(matcher, [{"hello": "world"}])
        self.assertNotEqual(matcher, 123)
        self.assertNotEqual(matcher, "foo")

    def test_match_type_object(self):
        class Hello(object):
            pass

        class World(object):
            pass

        matcher = test.MatchType(Hello)

        self.assertEqual(matcher, Hello())
        self.assertNotEqual(matcher, World())
        self.assertNotEqual(matcher, 123)
        self.assertNotEqual(matcher, "foo")


class ContainKeyValueTestCase(test.NoDBTestCase):

    def test_contain_key_value_normal(self):
        matcher = test.ContainKeyValue('foo', 'bar')

        self.assertEqual(matcher, {123: 'nova', 'foo': 'bar'})
        self.assertNotEqual(matcher, {'foo': 123})
        self.assertNotEqual(matcher, {})

    def test_contain_key_value_exception(self):
        matcher = test.ContainKeyValue('foo', 'bar')

        # Raise TypeError
        self.assertNotEqual(matcher, 123)
        self.assertNotEqual(matcher, 'foo')
        # Raise KeyError
        self.assertNotEqual(matcher, {1: 2, '3': 4, 5: '6'})
        self.assertNotEqual(matcher, {'bar': 'foo'})


class NovaExceptionReraiseFormatErrorTestCase(test.NoDBTestCase):
    """Test that format errors are reraised in tests."""
    def test_format_error_in_nova_exception(self):
        class FakeImageException(exception.NovaException):
            msg_fmt = 'Image %(image_id)s has wrong type %(type)s.'
        # wrong kwarg
        ex = self.assertRaises(KeyError, FakeImageException,
                               bogus='wrongkwarg')
        self.assertIn('image_id', six.text_type(ex))
        # no kwarg
        ex = self.assertRaises(KeyError, FakeImageException)
        self.assertIn('image_id', six.text_type(ex))
        # not enough kwargs
        ex = self.assertRaises(KeyError, FakeImageException, image_id='image')
        self.assertIn('type', six.text_type(ex))


class PatchExistsTestCase(test.NoDBTestCase):
    def test_with_patch_exists_true(self):
        """Test that "with patch_exists" can fake the existence of a file
        without changing other file existence checks, and that calls can
        be asserted on the mocked method.
        """
        self.assertFalse(os.path.exists('fake_file'))
        with self.patch_exists('fake_file', True) as mock_exists:
            self.assertTrue(os.path.exists('fake_file'))
            self.assertTrue(os.path.exists(__file__))
            self.assertFalse(os.path.exists('non-existent/file'))
            self.assertIn(mock.call('fake_file'), mock_exists.mock_calls)

    def test_with_patch_exists_false(self):
        """Test that "with patch_exists" can fake the non-existence of a file
        without changing other file existence checks, and that calls can
        be asserted on the mocked method.
        """
        self.assertTrue(os.path.exists(__file__))
        with self.patch_exists(__file__, False) as mock_exists:
            self.assertFalse(os.path.exists(__file__))
            self.assertTrue(os.path.exists(os.path.dirname(__file__)))
            self.assertFalse(os.path.exists('non-existent/file'))
            self.assertIn(mock.call(__file__), mock_exists.mock_calls)

    @test.patch_exists('fake_file', True)
    def test_patch_exists_decorator_true(self):
        """Test that @patch_exists can fake the existence of a file
        without changing other file existence checks.
        """
        self.assertTrue(os.path.exists('fake_file'))
        self.assertTrue(os.path.exists(__file__))
        self.assertFalse(os.path.exists('non-existent/file'))

    @test.patch_exists(__file__, False)
    def test_patch_exists_decorator_false(self):
        """Test that @patch_exists can fake the non-existence of a file
        without changing other file existence checks.
        """
        self.assertFalse(os.path.exists(__file__))
        self.assertTrue(os.path.exists(os.path.dirname(__file__)))
        self.assertFalse(os.path.exists('non-existent/file'))

    @test.patch_exists('fake_file1', True)
    @test.patch_exists('fake_file2', True)
    @test.patch_exists(__file__, False)
    def test_patch_exists_multiple_decorators(self):
        """Test that @patch_exists can be used multiple times on the
        same method.
        """
        self.assertTrue(os.path.exists('fake_file1'))
        self.assertTrue(os.path.exists('fake_file2'))
        self.assertFalse(os.path.exists(__file__))

        # Check non-patched parameters
        self.assertTrue(os.path.exists(os.path.dirname(__file__)))
        self.assertFalse(os.path.exists('non-existent/file'))


class PatchOpenTestCase(test.NoDBTestCase):
    fake_contents = "These file contents don't really exist"

    def _test_patched_open(self):
        """Test that a selectively patched open can fake the contents of a
        file while still allowing normal, real file operations.
        """
        self.assertFalse(os.path.exists('fake_file'))

        with open('fake_file') as f:
            self.assertEqual(self.fake_contents, f.read())

        # Test we can still open and read this file from within the
        # same context.  NOTE: We have to make sure we open the .py
        # file not the corresponding .pyc file.
        with open(__file__.rstrip('c')) as f:
            this_file_contents = f.read()
            self.assertIn("class %s(" % self.__class__.__name__,
                          this_file_contents)
            self.assertNotIn("magic concatenated" "string",
                             this_file_contents)

        # Test we can still create, write to, and then read from a
        # temporary file, from within the same context.
        tmp = tempfile.NamedTemporaryFile()
        tmp_contents = str(uuid.uuid1())
        with open(tmp.name, 'w') as f:
            f.write(tmp_contents)
        with open(tmp.name) as f:
            self.assertEqual(tmp_contents, f.read())

        return tmp.name

    def test_with_patch_open(self):
        """Test that "with patch_open" can fake the contents of a file
        without changing other file operations, and that calls can
        be asserted on the mocked method.
        """
        with self.patch_open('fake_file', self.fake_contents) as mock_open:
            tmp_name = self._test_patched_open()

            # Test we can make assertions about how the mock_open was called.
            self.assertIn(mock.call('fake_file'), mock_open.mock_calls)
            # The mock_open should get bypassed for non-patched path values:
            self.assertNotIn(mock.call(__file__), mock_open.mock_calls)
            self.assertNotIn(mock.call(tmp_name), mock_open.mock_calls)

    @test.patch_open('fake_file', fake_contents)
    def test_patch_open_decorator(self):
        """Test that @patch_open can fake the contents of a file
        without changing other file operations.
        """
        self._test_patched_open()

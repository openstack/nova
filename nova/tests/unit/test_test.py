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

            def __getattribute__(*args):
                assert False, "I should never get called."

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
                "3 != 4: path: root.top.l1.l2. List lengths are not equal",
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
                "3 != 2: path: root.top.l1.l2. Dict lengths are not equal",
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

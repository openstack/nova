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
        self.flags(use_local=True, group='conductor')
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
    def test_json_equal(self):
        expected = {
            "employees": [
                {"firstName": "Anna", "lastName": "Smith"},
                {"firstName": "John", "lastName": "Doe"},
                {"firstName": "Peter", "lastName": "Jones"}
            ],
            "locations": set(['Boston', 'Mumbai', 'Beijing', 'Perth'])
        }
        observed = """{
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
        self.assertJsonEqual(expected, observed)

    def test_json_equal_fail_on_length(self):
        expected = {
            'top': {
                'l1': {
                    'l2': ['a', 'b', 'c']
                }
            }
        }
        observed = {
            'top': {
                'l1': {
                    'l2': ['c', 'a', 'b', 'd']
                }
            }
        }
        try:
            self.assertJsonEqual(expected, observed)
        except Exception as e:
            # error reported is going to be a cryptic length failure
            # on the level2 structure.
            self.assertEqual(e.mismatch.describe(), "3 != 4")
            self.assertIn(
                "Matchee: {'top': {'l1': {'l2': ['c', 'a', 'b', 'd']}}}",
                six.text_type(e))
            self.assertIn(
                "Matcher: {'top': {'l1': {'l2': ['a', 'b', 'c']}}}",
                six.text_type(e))
        else:
            self.fail("This should have raised a mismatch exception")

    def test_json_equal_fail_on_inner(self):
        expected = {
            'top': {
                'l1': {
                    'l2': ['a', 'b', 'c']
                }
            }
        }
        observed = {
            'top': {
                'l1': {
                    'l2': ['c', 'a', 'd']
                }
            }
        }
        try:
            self.assertJsonEqual(expected, observed)
        except Exception as e:
            # error reported is going to be a cryptic length failure
            # on the level2 structure.
            self.assertEqual(e.mismatch.describe(), "'b' != 'c'")
            self.assertIn(
                "Matchee: {'top': {'l1': {'l2': ['c', 'a', 'd']}}}",
                six.text_type(e))
            self.assertIn(
                "Matcher: {'top': {'l1': {'l2': ['a', 'b', 'c']}}}",
                six.text_type(e))
        else:
            self.fail("This should have raised a mismatch exception")


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

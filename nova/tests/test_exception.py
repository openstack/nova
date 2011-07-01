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

from nova import test
from nova import exception


class ApiErrorTestCase(test.TestCase):
    def test_return_valid_error(self):
        # without 'code' arg
        err = exception.ApiError('fake error')
        self.assertEqual(err.__str__(), 'fake error')
        self.assertEqual(err.code, None)
        self.assertEqual(err.msg, 'fake error')
        # with 'code' arg
        err = exception.ApiError('fake error', 'blah code')
        self.assertEqual(err.__str__(), 'blah code: fake error')
        self.assertEqual(err.code, 'blah code')
        self.assertEqual(err.msg, 'fake error')


class FakeNotifier(object):
    """Acts like the nova.notifier.api module."""
    ERROR = 88

    def __init__(self):
        self.provided_publisher = None
        self.provided_event = None
        self.provided_priority = None
        self.provided_payload = None

    def notify(self, publisher, event, priority, payload):
        self.provided_publisher = publisher
        self.provided_event = event
        self.provided_priority = priority
        self.provided_payload = payload


def good_function():
    return 99


def bad_function_error():
    raise exception.Error()


def bad_function_exception():
    raise Exception()


class WrapExceptionTestCase(test.TestCase):
    def test_wrap_exception_good_return(self):
        wrapped = exception.wrap_exception()
        self.assertEquals(99, wrapped(good_function)())

    def test_wrap_exception_throws_error(self):
        wrapped = exception.wrap_exception()
        self.assertRaises(exception.Error, wrapped(bad_function_error))

    def test_wrap_exception_throws_exception(self):
        wrapped = exception.wrap_exception()
        # Note that Exception is converted to Error ...
        self.assertRaises(exception.Error, wrapped(bad_function_exception))

    def test_wrap_exception_with_notifier(self):
        notifier = FakeNotifier()
        wrapped = exception.wrap_exception(notifier, "publisher", "event",
                                           "level")
        self.assertRaises(exception.Error, wrapped(bad_function_exception))
        self.assertEquals(notifier.provided_publisher, "publisher")
        self.assertEquals(notifier.provided_event, "event")
        self.assertEquals(notifier.provided_priority, "level")
        for key in ['exception', 'args']:
            self.assertTrue(key in notifier.provided_payload.keys())

    def test_wrap_exception_with_notifier_defaults(self):
        notifier = FakeNotifier()
        wrapped = exception.wrap_exception(notifier)
        self.assertRaises(exception.Error, wrapped(bad_function_exception))
        self.assertEquals(notifier.provided_publisher, None)
        self.assertEquals(notifier.provided_event, "bad_function_exception")
        self.assertEquals(notifier.provided_priority, notifier.ERROR)

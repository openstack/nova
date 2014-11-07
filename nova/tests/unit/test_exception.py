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

import inspect

import six

from nova import context
from nova import exception
from nova import test


class FakeNotifier(object):
    """Acts like messaging.Notifier."""

    def __init__(self):
        self.provided_context = None
        self.provided_event = None
        self.provided_payload = None

    def error(self, context, event, payload):
        self.provided_context = context
        self.provided_event = event
        self.provided_payload = payload


def good_function(self, context):
    return 99


def bad_function_exception(self, context, extra, blah="a", boo="b", zoo=None):
    raise test.TestingException()


class WrapExceptionTestCase(test.NoDBTestCase):
    def test_wrap_exception_good_return(self):
        wrapped = exception.wrap_exception('foo')
        self.assertEqual(99, wrapped(good_function)(1, 2))

    def test_wrap_exception_with_notifier(self):
        notifier = FakeNotifier()
        wrapped = exception.wrap_exception(notifier)
        ctxt = context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)
        self.assertEqual(notifier.provided_event, "bad_function_exception")
        self.assertEqual(notifier.provided_context, ctxt)
        self.assertEqual(notifier.provided_payload['args']['extra'], 3)
        for key in ['exception', 'args']:
            self.assertIn(key, notifier.provided_payload.keys())


class NovaExceptionTestCase(test.NoDBTestCase):
    def test_default_error_msg(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message"

        exc = FakeNovaException()
        self.assertEqual(six.text_type(exc), 'default message')

    def test_error_msg(self):
        self.assertEqual(six.text_type(exception.NovaException('test')),
                         'test')

    def test_default_error_msg_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(code)s"

        exc = FakeNovaException(code=500)
        self.assertEqual(six.text_type(exc), 'default message: 500')
        self.assertEqual(exc.message, 'default message: 500')

    def test_error_msg_exception_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(misspelled_code)s"

        exc = FakeNovaException(code=500, misspelled_code='blah')
        self.assertEqual(six.text_type(exc), 'default message: blah')
        self.assertEqual(exc.message, 'default message: blah')

    def test_default_error_code(self):
        class FakeNovaException(exception.NovaException):
            code = 404

        exc = FakeNovaException()
        self.assertEqual(exc.kwargs['code'], 404)

    def test_error_code_from_kwarg(self):
        class FakeNovaException(exception.NovaException):
            code = 500

        exc = FakeNovaException(code=404)
        self.assertEqual(exc.kwargs['code'], 404)

    def test_cleanse_dict(self):
        kwargs = {'foo': 1, 'blah_pass': 2, 'zoo_password': 3, '_pass': 4}
        self.assertEqual(exception._cleanse_dict(kwargs), {'foo': 1})

        kwargs = {}
        self.assertEqual(exception._cleanse_dict(kwargs), {})

    def test_format_message_local(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "some message"

        exc = FakeNovaException()
        self.assertEqual(six.text_type(exc), exc.format_message())

    def test_format_message_remote(self):
        class FakeNovaException_Remote(exception.NovaException):
            msg_fmt = "some message"

            def __unicode__(self):
                return u"print the whole trace"

        exc = FakeNovaException_Remote()
        self.assertEqual(six.text_type(exc), u"print the whole trace")
        self.assertEqual(exc.format_message(), "some message")

    def test_format_message_remote_error(self):
        class FakeNovaException_Remote(exception.NovaException):
            msg_fmt = "some message %(somearg)s"

            def __unicode__(self):
                return u"print the whole trace"

        self.flags(fatal_exception_format_errors=False)
        exc = FakeNovaException_Remote(lame_arg='lame')
        self.assertEqual(exc.format_message(), "some message %(somearg)s")


class ExceptionTestCase(test.NoDBTestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc()

    def test_exceptions_raise(self):
        # NOTE(dprince): disable format errors since we are not passing kwargs
        self.flags(fatal_exception_format_errors=False)
        for name in dir(exception):
            exc = getattr(exception, name)
            if isinstance(exc, type):
                self.assertRaises(exc, self._raise_exc, exc)


class ExceptionValidMessageTestCase(test.NoDBTestCase):

    def test_messages(self):
        failures = []

        for name, obj in inspect.getmembers(exception):
            if name in ['NovaException', 'InstanceFaultRollback']:
                continue

            if not inspect.isclass(obj):
                continue

            if not issubclass(obj, exception.NovaException):
                continue

            e = obj
            if e.msg_fmt == "An unknown exception occurred.":
                failures.append('%s needs a more specific msg_fmt' % name)

        if failures:
            self.fail('\n'.join(failures))

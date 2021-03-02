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

import fixtures
from webob.util import status_reasons

from nova import exception
from nova import test


class NovaExceptionTestCase(test.NoDBTestCase):
    def test_default_error_msg(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message"

        exc = FakeNovaException()
        self.assertEqual('default message', str(exc))

    def test_error_msg(self):
        self.assertEqual('test', str(exception.NovaException('test')))
        self.assertEqual('test',
                         exception.NovaException(Exception('test')).message)

    def test_default_error_msg_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(code)s"

        exc = FakeNovaException(code=500)
        self.assertEqual('default message: 500', str(exc))
        self.assertEqual('default message: 500', exc.message)

    def test_error_msg_exception_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(misspelled_code)s"

        exc = FakeNovaException(code=500, misspelled_code='blah')
        self.assertEqual('default message: blah', str(exc))
        self.assertEqual('default message: blah', exc.message)

    def test_default_error_code(self):
        class FakeNovaException(exception.NovaException):
            code = 404

        exc = FakeNovaException()
        self.assertEqual(404, exc.kwargs['code'])

    def test_error_code_from_kwarg(self):
        class FakeNovaException(exception.NovaException):
            code = 500

        exc = FakeNovaException(code=404)
        self.assertEqual(exc.kwargs['code'], 404)

    def test_format_message_local(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "some message"

        exc = FakeNovaException()
        self.assertEqual(str(exc), exc.format_message())

    def test_format_message_remote(self):
        class FakeNovaException_Remote(exception.NovaException):
            msg_fmt = "some message"

            def __str__(self):
                return "print the whole trace"

        exc = FakeNovaException_Remote()
        self.assertEqual(u"print the whole trace", str(exc))
        self.assertEqual("some message", exc.format_message())

    def test_format_message_remote_error(self):
        # NOTE(melwitt): This test checks that errors are formatted as expected
        # in a real environment where format errors are caught and not
        # reraised, so we patch in the real implementation.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.exception.NovaException._log_exception',
            test.NovaExceptionReraiseFormatError.real_log_exception))

        class FakeNovaException_Remote(exception.NovaException):
            msg_fmt = "some message %(somearg)s"

        exc = FakeNovaException_Remote(lame_arg='lame')
        self.assertEqual("some message %(somearg)s", exc.format_message())

    def test_repr(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "some message"

        mock_exc = FakeNovaException(code=500)

        exc_repr = repr(mock_exc)

        eval_repr = eval(exc_repr)
        exc_kwargs = eval_repr.get('kwargs')

        self.assertIsNotNone(exc_kwargs)

        self.assertEqual(500, exc_kwargs.get('code'))
        self.assertEqual('some message', eval_repr.get('message'))
        self.assertEqual('FakeNovaException', eval_repr.get('class'))


class ConvertedExceptionTestCase(test.NoDBTestCase):
    def test_instantiate(self):
        exc = exception.ConvertedException(400, 'Bad Request', 'reason')
        self.assertEqual(exc.code, 400)
        self.assertEqual(exc.title, 'Bad Request')
        self.assertEqual(exc.explanation, 'reason')

    def test_instantiate_without_title_known_code(self):
        exc = exception.ConvertedException(500)
        self.assertEqual(exc.title, status_reasons[500])

    def test_instantiate_without_title_unknown_code(self):
        exc = exception.ConvertedException(499)
        self.assertEqual(exc.title, 'Unknown Client Error')

    def test_instantiate_bad_code(self):
        self.assertRaises(KeyError, exception.ConvertedException, 10)


class ExceptionTestCase(test.NoDBTestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc(500)

    def test_exceptions_raise(self):
        # NOTE(dprince): disable format errors since we are not passing kwargs
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

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
import mock
import six
from webob.util import status_reasons

from nova import context
from nova import exception
from nova import exception_wrapper
from nova import rpc
from nova import test
from nova.tests.unit import fake_notifier


def good_function(self, context):
    return 99


def bad_function_exception(self, context, extra, blah="a", boo="b", zoo=None):
    raise test.TestingException('bad things happened')


def bad_function_unknown_module(self, context):
    """Example traceback that points to a module that getmodule() can't find.

    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
      File "src/lxml/lxml.etree.pyx", line 2402, in
          lxml.etree._Attrib.__setitem__ (src/lxml/lxml.etree.c:67548)
      File "src/lxml/apihelpers.pxi", line 570, in
          lxml.etree._setAttributeValue (src/lxml/lxml.etree.c:21551)
      File "src/lxml/apihelpers.pxi", line 1437, in
          lxml.etree._utf8 (src/lxml/lxml.etree.c:30194)
    TypeError: Argument must be bytes or unicode, got 'NoneType'

    """
    from lxml import etree
    x = etree.fromstring('<hello/>')
    x.attrib['foo'] = None


class WrapExceptionTestCase(test.NoDBTestCase):
    def setUp(self):
        super(WrapExceptionTestCase, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

    def test_wrap_exception_good_return(self):
        wrapped = exception_wrapper.wrap_exception(rpc.get_notifier('fake'))
        self.assertEqual(99, wrapped(good_function)(1, 2))
        self.assertEqual(0, len(fake_notifier.NOTIFICATIONS))
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

    def test_wrap_exception_unknown_module(self):
        ctxt = context.get_admin_context()
        wrapped = exception_wrapper.wrap_exception(
            rpc.get_notifier('fake'), binary='nova-compute')
        self.assertRaises(
            TypeError, wrapped(bad_function_unknown_module), None, ctxt)
        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        notification = fake_notifier.VERSIONED_NOTIFICATIONS[0]
        payload = notification['payload']['nova_object.data']
        self.assertEqual('unknown', payload['module_name'])

    def test_wrap_exception_with_notifier(self):
        wrapped = exception_wrapper.wrap_exception(rpc.get_notifier('fake'),
                                                   binary='nova-compute')
        ctxt = context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        notification = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('bad_function_exception', notification.event_type)
        self.assertEqual(ctxt, notification.context)
        self.assertEqual(3, notification.payload['args']['extra'])
        for key in ['exception', 'args']:
            self.assertIn(key, notification.payload.keys())
        self.assertNotIn('context', notification.payload['args'].keys())

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        notification = fake_notifier.VERSIONED_NOTIFICATIONS[0]
        self.assertEqual('compute.exception', notification['event_type'])
        self.assertEqual('nova-compute:fake-mini',
                         notification['publisher_id'])
        self.assertEqual('ERROR', notification['priority'])

        payload = notification['payload']
        self.assertEqual('ExceptionPayload', payload['nova_object.name'])
        self.assertEqual('1.1', payload['nova_object.version'])

        payload = payload['nova_object.data']
        self.assertEqual('TestingException', payload['exception'])
        self.assertEqual('bad things happened', payload['exception_message'])
        self.assertEqual('bad_function_exception', payload['function_name'])
        self.assertEqual('nova.tests.unit.test_exception',
                         payload['module_name'])
        self.assertIn('bad_function_exception', payload['traceback'])

    @mock.patch('nova.rpc.NOTIFIER')
    @mock.patch('nova.notifications.objects.exception.'
                'ExceptionNotification.__init__')
    def test_wrap_exception_notification_not_emitted_if_disabled(
            self, mock_notification, mock_notifier):
        mock_notifier.is_enabled.return_value = False

        wrapped = exception_wrapper.wrap_exception(rpc.get_notifier('fake'),
                                                   binary='nova-compute')
        ctxt = context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)
        self.assertFalse(mock_notification.called)

    @mock.patch('nova.notifications.objects.exception.'
                'ExceptionNotification.__init__')
    def test_wrap_exception_notification_not_emitted_if_unversioned(
            self, mock_notifier):
        self.flags(notification_format='unversioned', group='notifications')

        wrapped = exception_wrapper.wrap_exception(rpc.get_notifier('fake'),
                                                   binary='nova-compute')
        ctxt = context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)
        self.assertFalse(mock_notifier.called)


class NovaExceptionTestCase(test.NoDBTestCase):
    def test_default_error_msg(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message"

        exc = FakeNovaException()
        self.assertEqual('default message', six.text_type(exc))

    def test_error_msg(self):
        self.assertEqual('test',
                         six.text_type(exception.NovaException('test')))
        self.assertEqual('test',
                         exception.NovaException(Exception('test')).message)

    def test_default_error_msg_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(code)s"

        exc = FakeNovaException(code=500)
        self.assertEqual('default message: 500', six.text_type(exc))
        self.assertEqual('default message: 500', exc.message)

    def test_error_msg_exception_with_kwargs(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "default message: %(misspelled_code)s"

        exc = FakeNovaException(code=500, misspelled_code='blah')
        self.assertEqual('default message: blah', six.text_type(exc))
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

    def test_cleanse_dict(self):
        kwargs = {'foo': 1, 'blah_pass': 2, 'zoo_password': 3, '_pass': 4}
        self.assertEqual({'foo': 1}, exception_wrapper._cleanse_dict(kwargs))

        kwargs = {}
        self.assertEqual({}, exception_wrapper._cleanse_dict(kwargs))

    def test_format_message_local(self):
        class FakeNovaException(exception.NovaException):
            msg_fmt = "some message"

        exc = FakeNovaException()
        self.assertEqual(six.text_type(exc), exc.format_message())

    def test_format_message_remote(self):
        class FakeNovaException_Remote(exception.NovaException):
            msg_fmt = "some message"

            if six.PY2:
                def __unicode__(self):
                    return u"print the whole trace"
            else:
                def __str__(self):
                    return "print the whole trace"

        exc = FakeNovaException_Remote()
        self.assertEqual(u"print the whole trace", six.text_type(exc))
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

            def __unicode__(self):
                return u"print the whole trace"

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

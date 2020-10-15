# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from nova import context as nova_context
from nova import exception_wrapper
from nova import test
from nova.tests import fixtures as nova_fixtures


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


def good_function(self, context):
    return 99


class WrapExceptionTestCase(test.NoDBTestCase):
    def setUp(self):
        super(WrapExceptionTestCase, self).setUp()
        self.notifier = self.useFixture(
            nova_fixtures.NotificationFixture(self))

    def test_cleanse_dict(self):
        kwargs = {'foo': 1, 'blah_pass': 2, 'zoo_password': 3, '_pass': 4}
        self.assertEqual({'foo': 1}, exception_wrapper._cleanse_dict(kwargs))

        kwargs = {}
        self.assertEqual({}, exception_wrapper._cleanse_dict(kwargs))

    def test_wrap_exception_good_return(self):
        wrapped = exception_wrapper.wrap_exception(
            service='compute', binary='nova-compute')
        self.assertEqual(99, wrapped(good_function)(1, 2))
        self.assertEqual(0, len(self.notifier.notifications))
        self.assertEqual(0, len(self.notifier.versioned_notifications))

    def test_wrap_exception_unknown_module(self):
        ctxt = nova_context.get_admin_context()
        wrapped = exception_wrapper.wrap_exception(
            service='compute', binary='nova-compute')
        self.assertRaises(
            TypeError, wrapped(bad_function_unknown_module), None, ctxt)
        self.assertEqual(1, len(self.notifier.versioned_notifications))
        notification = self.notifier.versioned_notifications[0]
        payload = notification['payload']['nova_object.data']
        self.assertEqual('unknown', payload['module_name'])

    def test_wrap_exception_with_notifier(self):
        wrapped = exception_wrapper.wrap_exception(
            service='compute', binary='nova-compute')
        ctxt = nova_context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)

        self.assertEqual(1, len(self.notifier.notifications))
        notification = self.notifier.notifications[0]
        self.assertEqual('bad_function_exception', notification.event_type)
        self.assertEqual(ctxt, notification.context)
        self.assertEqual(3, notification.payload['args']['extra'])
        for key in ['exception', 'args']:
            self.assertIn(key, notification.payload.keys())
        self.assertNotIn('context', notification.payload['args'].keys())

        self.assertEqual(1, len(self.notifier.versioned_notifications))
        notification = self.notifier.versioned_notifications[0]
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
        self.assertEqual('nova.tests.unit.test_exception_wrapper',
                         payload['module_name'])
        self.assertIn('bad_function_exception', payload['traceback'])

    @mock.patch('nova.rpc.NOTIFIER')
    @mock.patch('nova.notifications.objects.exception.'
                'ExceptionNotification.__init__')
    def test_wrap_exception_notification_not_emitted_if_disabled(
            self, mock_notification, mock_notifier):
        mock_notifier.is_enabled.return_value = False

        wrapped = exception_wrapper.wrap_exception(
            service='compute', binary='nova-compute')
        ctxt = nova_context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)
        self.assertFalse(mock_notification.called)

    @mock.patch('nova.notifications.objects.exception.'
                'ExceptionNotification.__init__')
    def test_wrap_exception_notification_not_emitted_if_unversioned(
            self, mock_notifier):
        self.flags(notification_format='unversioned', group='notifications')

        wrapped = exception_wrapper.wrap_exception(
            service='compute', binary='nova-compute')
        ctxt = nova_context.get_admin_context()
        self.assertRaises(test.TestingException,
                          wrapped(bad_function_exception), 1, ctxt, 3, zoo=3)
        self.assertFalse(mock_notifier.called)

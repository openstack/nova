# Copyright 2011 OpenStack LLC.
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

import stubout

import nova
from nova import context
from nova import flags
from nova import log as logging
from nova import rpc
import nova.notifier.api
from nova.notifier.api import notify
from nova.notifier import log_notifier
from nova.notifier import no_op_notifier
from nova.notifier import list_notifier
from nova.notifier import rabbit_notifier
from nova import test


class NotifierListTestCase(test.TestCase):
    """Test case for notifications"""
    def setUp(self):
        super(NotifierListTestCase, self).setUp()
        list_notifier._reset_drivers()
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.stubs.UnsetAll()
        list_notifier._reset_drivers()
        super(NotifierListTestCase, self).tearDown()

    def test_send_notifications_successfully(self):
        self.flags(notification_driver='nova.notifier.list_notifier',
                   list_notifier_drivers=['nova.notifier.no_op_notifier',
                                          'nova.notifier.no_op_notifier'])
        self.notify_count = 0

        def mock_notify(cls, *args):
            self.notify_count += 1

        self.stubs.Set(nova.notifier.no_op_notifier, 'notify',
                mock_notify)

        notify('publisher_id', 'event_type',
                nova.notifier.api.WARN, dict(a=3))
        self.assertEqual(self.notify_count, 2)

    def test_send_notifications_with_errors(self):
        self.exception_count = 0
        def mock_exception(cls, *args):
            self.exception_count += 1

        self.notify_count = 0
        def mock_notify(cls, *args):
            self.notify_count += 1

        def mock_notify2(cls, *args):
            raise RuntimeError("Bad notifier.")

        self.flags(notification_driver='nova.notifier.list_notifier',
                   list_notifier_drivers=['nova.notifier.no_op_notifier',
                                          'nova.notifier.log_notifier'])

        list_notifier_log = logging.getLogger('nova.notifier.list_notifier')
        list_notifier_log.exception
        self.stubs.Set(list_notifier_log, "exception", mock_exception)
        self.stubs.Set(nova.notifier.no_op_notifier, 'notify', mock_notify)
        self.stubs.Set(nova.notifier.log_notifier, 'notify', mock_notify2)

        notify('publisher_id', 'event_type', nova.notifier.api.WARN, dict(a=3))

        self.assertEqual(self.notify_count, 1)
        self.assertEqual(self.exception_count, 1)

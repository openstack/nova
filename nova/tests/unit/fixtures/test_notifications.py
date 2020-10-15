# Copyright 2018 Red Hat, Inc.
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

from nova import context
from nova import exception_wrapper
from nova import test
from nova.tests import fixtures


class TestNotificationFixture(test.NoDBTestCase):
    def setUp(self):
        super(TestNotificationFixture, self).setUp()

        self.notifier = self.useFixture(fixtures.NotificationFixture(self))

        self.context = context.RequestContext()

    @exception_wrapper.wrap_exception(service='compute', binary='nova-compute')
    def _raise_exception(self, context):
        raise test.TestingException

    def _generate_exception_notification(self):
        self.assertRaises(test.TestingException, self._raise_exception,
                          self.context)

    def test_wait_for_versioned_notifications(self):
        # Wait for a single notification which we emitted first
        self._generate_exception_notification()

        notifications = self.notifier.wait_for_versioned_notifications(
                'compute.exception')
        self.assertEqual(1, len(notifications))

    def test_wait_for_versioned_notifications_fail(self):
        # Wait for a single notification which is never sent
        self.assertRaises(
            AssertionError,
            self.notifier.wait_for_versioned_notifications,
            'compute.exception', timeout=0.1)

    def test_wait_for_versioned_notifications_n(self):
        # Wait for 2 notifications which we emitted first
        self._generate_exception_notification()
        self._generate_exception_notification()

        notifications = self.notifier.wait_for_versioned_notifications(
                'compute.exception', 2)
        self.assertEqual(2, len(notifications))

    def test_wait_for_versioned_notifications_n_fail(self):
        # Wait for 2 notifications when we only emitted one
        self._generate_exception_notification()

        self.assertRaises(
            AssertionError,
            self.notifier.wait_for_versioned_notifications,
            'compute.exception', 2, timeout=0.1)

    def test_wait_for_versioned_notifications_too_many(self):
        # Wait for a single notification when there are 2 in the queue
        self._generate_exception_notification()
        self._generate_exception_notification()

        notifications = self.notifier.wait_for_versioned_notifications(
                'compute.exception')
        self.assertEqual(2, len(notifications))

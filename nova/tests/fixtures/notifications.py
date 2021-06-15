# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import functools
import threading

import fixtures
from oslo_log import log as logging
import oslo_messaging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import timeutils

from nova import rpc

LOG = logging.getLogger(__name__)


class _Sub(object):
    """Allow a subscriber to efficiently wait for an event to occur, and
    retrieve events which have occurred.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._notifications = []

    def received(self, notification):
        with self._cond:
            self._notifications.append(notification)
            self._cond.notifyAll()

    def wait_n(self, n, event, timeout):
        """Wait until at least n notifications have been received, and return
        them. May return less than n notifications if timeout is reached.
        """

        with timeutils.StopWatch(timeout) as timer:
            with self._cond:
                while len(self._notifications) < n:
                    if timer.expired():
                        # notifications = pprint.pformat(
                        #     {event: sub._notifications
                        #      for event, sub in VERSIONED_SUBS.items()})
                        # FIXME: tranform this to get access to all the
                        # versioned notifications
                        notifications = []
                        raise AssertionError(
                            "Notification %(event)s hasn't been "
                            "received. Received:\n%(notifications)s" % {
                                'event': event,
                                'notifications': notifications,
                            })
                    self._cond.wait(timer.leftover())

                # Return a copy of the notifications list
                return list(self._notifications)


FakeMessage = collections.namedtuple(
    'FakeMessage',
    ['publisher_id', 'priority', 'event_type', 'payload', 'context'])


class FakeNotifier(object):

    def __init__(
        self, transport, publisher_id, serializer=None, parent=None,
    ):
        self.transport = transport
        self.publisher_id = publisher_id
        self._serializer = \
            serializer or oslo_messaging.serializer.NoOpSerializer()
        if parent:
            self.notifications = parent.notifications
        else:
            self.notifications = []

        for priority in ['debug', 'info', 'warn', 'error', 'critical']:
            setattr(
                self, priority,
                functools.partial(self._notify, priority.upper()),
            )

    def prepare(self, publisher_id=None):
        if publisher_id is None:
            publisher_id = self.publisher_id

        return self.__class__(
            self.transport, publisher_id,
            serializer=self._serializer, parent=self,
        )

    def _notify(self, priority, ctxt, event_type, payload):
        try:
            payload = self._serializer.serialize_entity(ctxt, payload)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Error serializing payload: %s', payload)

        # NOTE(sileht): simulate the kombu serializer
        # this permit to raise an exception if something have not
        # been serialized correctly
        jsonutils.to_primitive(payload)
        # NOTE(melwitt): Try to serialize the context, as the rpc would.
        #                An exception will be raised if something is wrong
        #                with the context.
        self._serializer.serialize_context(ctxt)
        msg = FakeMessage(
            self.publisher_id, priority, event_type, payload, ctxt)
        self.notifications.append(msg)

    def is_enabled(self):
        return True

    def reset(self):
        self.notifications.clear()


class FakeVersionedNotifier(FakeNotifier):
    def __init__(
        self, transport, publisher_id, serializer=None, parent=None,
    ):
        super().__init__(transport, publisher_id, serializer)
        if parent:
            self.versioned_notifications = parent.versioned_notifications
        else:
            self.versioned_notifications = []

        if parent:
            self.subscriptions = parent.subscriptions
        else:
            self.subscriptions = collections.defaultdict(_Sub)

    def _notify(self, priority, ctxt, event_type, payload):
        payload = self._serializer.serialize_entity(ctxt, payload)
        notification = {
            'publisher_id': self.publisher_id,
            'priority': priority,
            'event_type': event_type,
            'payload': payload,
        }
        self.versioned_notifications.append(notification)
        self.subscriptions[event_type].received(notification)

    def reset(self):
        self.versioned_notifications.clear()
        self.subscriptions.clear()

    def wait_for_versioned_notifications(
        self, event_type, n_events=1, timeout=10.0,
    ):
        return self.subscriptions[event_type].wait_n(
            n_events, event_type, timeout)


class NotificationFixture(fixtures.Fixture):
    def __init__(self, test):
        self.test = test

    def setUp(self):
        super().setUp()
        self.addCleanup(self.reset)

        self.fake_notifier = FakeNotifier(
            rpc.LEGACY_NOTIFIER.transport,
            rpc.LEGACY_NOTIFIER.publisher_id,
            serializer=getattr(
                rpc.LEGACY_NOTIFIER, '_serializer', None))
        self.fake_versioned_notifier = FakeVersionedNotifier(
            rpc.NOTIFIER.transport,
            rpc.NOTIFIER.publisher_id,
            serializer=getattr(rpc.NOTIFIER, '_serializer', None))
        if rpc.LEGACY_NOTIFIER and rpc.NOTIFIER:
            self.test.stub_out('nova.rpc.LEGACY_NOTIFIER', self.fake_notifier)
            self.test.stub_out(
                'nova.rpc.NOTIFIER', self.fake_versioned_notifier)

    def reset(self):
        self.fake_notifier.reset()
        self.fake_versioned_notifier.reset()

    def wait_for_versioned_notifications(
        self, event_type, n_events=1, timeout=10.0,
    ):
        return self.fake_versioned_notifier.wait_for_versioned_notifications(
            event_type, n_events, timeout,
        )

    @property
    def versioned_notifications(self):
        return self.fake_versioned_notifier.versioned_notifications

    @property
    def notifications(self):
        return self.fake_notifier.notifications

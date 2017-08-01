# Copyright 2013 Red Hat, Inc.
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

import collections
import copy
import functools
import threading

import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova import rpc


class _Sub(object):
    """Allow a subscriber to efficiently wait for an event to occur, and
    retrieve events which have occured.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._notifications = []

    def received(self, notification):
        with self._cond:
            self._notifications.append(notification)
            self._cond.notifyAll()

    def wait_n(self, n, timeout=1.0):
        """Wait until at least n notifications have been received, and return
        them. May return less than n notifications if timeout is reached.
        """

        with timeutils.StopWatch(timeout) as timer:
            with self._cond:
                while len(self._notifications) < n and not timer.expired():
                    self._cond.wait(timer.leftover())
                return copy.copy(self._notifications)


VERSIONED_SUBS = collections.defaultdict(_Sub)
VERSIONED_NOTIFICATIONS = []
NOTIFICATIONS = []


def reset():
    del NOTIFICATIONS[:]
    del VERSIONED_NOTIFICATIONS[:]
    VERSIONED_SUBS.clear()


FakeMessage = collections.namedtuple('Message',
                                     ['publisher_id', 'priority',
                                      'event_type', 'payload', 'context'])


class FakeNotifier(object):

    def __init__(self, transport, publisher_id, serializer=None):
        self.transport = transport
        self.publisher_id = publisher_id
        self._serializer = serializer or messaging.serializer.NoOpSerializer()

        for priority in ['debug', 'info', 'warn', 'error', 'critical']:
            setattr(self, priority,
                    functools.partial(self._notify, priority.upper()))

    def prepare(self, publisher_id=None):
        if publisher_id is None:
            publisher_id = self.publisher_id
        return self.__class__(self.transport, publisher_id,
                              serializer=self._serializer)

    def _notify(self, priority, ctxt, event_type, payload):
        payload = self._serializer.serialize_entity(ctxt, payload)
        # NOTE(sileht): simulate the kombu serializer
        # this permit to raise an exception if something have not
        # been serialized correctly
        jsonutils.to_primitive(payload)
        # NOTE(melwitt): Try to serialize the context, as the rpc would.
        #                An exception will be raised if something is wrong
        #                with the context.
        self._serializer.serialize_context(ctxt)
        msg = FakeMessage(self.publisher_id, priority, event_type,
                          payload, ctxt)
        NOTIFICATIONS.append(msg)

    def is_enabled(self):
        return True


class FakeVersionedNotifier(FakeNotifier):
    def _notify(self, priority, ctxt, event_type, payload):
        payload = self._serializer.serialize_entity(ctxt, payload)
        notification = {'publisher_id': self.publisher_id,
                        'priority': priority,
                        'event_type': event_type,
                        'payload': payload}
        VERSIONED_NOTIFICATIONS.append(notification)
        VERSIONED_SUBS[event_type].received(notification)


def stub_notifier(test):
    test.stub_out('oslo_messaging.Notifier', FakeNotifier)
    if rpc.LEGACY_NOTIFIER and rpc.NOTIFIER:
        test.stub_out('nova.rpc.LEGACY_NOTIFIER',
              FakeNotifier(rpc.LEGACY_NOTIFIER.transport,
                           rpc.LEGACY_NOTIFIER.publisher_id,
                           serializer=getattr(rpc.LEGACY_NOTIFIER,
                                              '_serializer',
                                              None)))
        test.stub_out('nova.rpc.NOTIFIER',
              FakeVersionedNotifier(rpc.NOTIFIER.transport,
                                    rpc.NOTIFIER.publisher_id,
                                    serializer=getattr(rpc.NOTIFIER,
                                                       '_serializer',
                                                       None)))


def wait_for_versioned_notifications(event_type, n_events=1, timeout=1.0):
    return VERSIONED_SUBS[event_type].wait_n(n_events, timeout=timeout)

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
import functools
import threading

import oslo_messaging as messaging
from oslo_serialization import jsonutils

from nova import rpc


SUBSCRIBERS = collections.defaultdict(threading.Event)
NOTIFICATIONS = []
VERSIONED_NOTIFICATIONS = []


def reset():
    del NOTIFICATIONS[:]
    del VERSIONED_NOTIFICATIONS[:]
    SUBSCRIBERS.clear()


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
        _notify_subscribers(notification)


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


def wait_for_versioned_notification(event_type, timeout=1.0):
    # NOTE: The event stored in SUBSCRIBERS is not used for synchronizing
    # the access to shared state as there is no parallel access to
    # SUBSCRIBERS because the only parallelism is due to eventlet.
    # The event is simply used to avoid polling the list of received
    # notifications
    return SUBSCRIBERS[event_type].wait(timeout)


def _notify_subscribers(notification):
    SUBSCRIBERS[notification['event_type']].set()

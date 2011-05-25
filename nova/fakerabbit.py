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

"""Based a bit on the carrot.backeds.queue backend... but a lot better."""

import Queue as queue

from carrot.backends import base
from eventlet import greenthread

from nova import log as logging


LOG = logging.getLogger("nova.fakerabbit")


EXCHANGES = {}
QUEUES = {}
CONSUMERS = {}


class Message(base.BaseMessage):
    pass


class Exchange(object):
    def __init__(self, name, exchange_type):
        self.name = name
        self.exchange_type = exchange_type
        self._queue = queue.Queue()
        self._routes = {}

    def publish(self, message, routing_key=None):
        nm = self.name
        LOG.debug(_('(%(nm)s) publish (key: %(routing_key)s)'
                ' %(message)s') % locals())
        if routing_key in self._routes:
            for f in self._routes[routing_key]:
                LOG.debug(_('Publishing to route %s'), f)
                f(message, routing_key=routing_key)

    def bind(self, callback, routing_key):
        self._routes.setdefault(routing_key, [])
        self._routes[routing_key].append(callback)


class Queue(object):
    def __init__(self, name):
        self.name = name
        self._queue = queue.Queue()

    def __repr__(self):
        return '<Queue: %s>' % self.name

    def push(self, message, routing_key=None):
        self._queue.put(message)

    def size(self):
        return self._queue.qsize()

    def pop(self):
        return self._queue.get()


class Backend(base.BaseBackend):
    def queue_declare(self, queue, **kwargs):
        global QUEUES
        if queue not in QUEUES:
            LOG.debug(_('Declaring queue %s'), queue)
            QUEUES[queue] = Queue(queue)

    def exchange_declare(self, exchange, type, *args, **kwargs):
        global EXCHANGES
        if exchange not in EXCHANGES:
            LOG.debug(_('Declaring exchange %s'), exchange)
            EXCHANGES[exchange] = Exchange(exchange, type)

    def queue_bind(self, queue, exchange, routing_key, **kwargs):
        global EXCHANGES
        global QUEUES
        LOG.debug(_('Binding %(queue)s to %(exchange)s with'
                ' key %(routing_key)s') % locals())
        EXCHANGES[exchange].bind(QUEUES[queue].push, routing_key)

    def declare_consumer(self, queue, callback, consumer_tag, *args, **kwargs):
        global CONSUMERS
        LOG.debug("Adding consumer %s", consumer_tag)
        CONSUMERS[consumer_tag] = (queue, callback)

    def cancel(self, consumer_tag):
        global CONSUMERS
        LOG.debug("Removing consumer %s", consumer_tag)
        del CONSUMERS[consumer_tag]

    def consume(self, limit=None):
        global CONSUMERS
        num = 0
        while True:
            for (queue, callback) in CONSUMERS.itervalues():
                item = self.get(queue)
                if item:
                    callback(item)
                    num += 1
                    yield
                    if limit and num == limit:
                        raise StopIteration()
            greenthread.sleep(0.1)

    def get(self, queue, no_ack=False):
        global QUEUES
        if not queue in QUEUES or not QUEUES[queue].size():
            return None
        (message_data, content_type, content_encoding) = QUEUES[queue].pop()
        message = Message(backend=self, body=message_data,
                          content_type=content_type,
                          content_encoding=content_encoding)
        message.result = True
        LOG.debug(_('Getting from %(queue)s: %(message)s') % locals())
        return message

    def prepare_message(self, message_data, delivery_mode,
                        content_type, content_encoding, **kwargs):
        """Prepare message for sending."""
        return (message_data, content_type, content_encoding)

    def publish(self, message, exchange, routing_key, **kwargs):
        global EXCHANGES
        if exchange in EXCHANGES:
            EXCHANGES[exchange].publish(message, routing_key=routing_key)


def reset_all():
    global EXCHANGES
    global QUEUES
    global CONSUMERS
    EXCHANGES = {}
    QUEUES = {}
    CONSUMERS = {}

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

""" Based a bit on the carrot.backeds.queue backend... but a lot better """

import logging
import Queue as queue

from carrot.backends import base


class Message(base.BaseMessage):
    pass


class Exchange(object):
    def __init__(self, name, exchange_type):
        self.name = name
        self.exchange_type = exchange_type
        self._queue = queue.Queue()
        self._routes = {}

    def publish(self, message, routing_key=None):
        logging.debug('(%s) publish (key: %s) %s',
                      self.name, routing_key, message)
        if routing_key in self._routes:
            for f in self._routes[routing_key]:
                logging.debug('Publishing to route %s', f)
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


class Backend(object):
    """ Singleton backend for testing """
    class __impl(base.BaseBackend):
        def __init__(self, *args, **kwargs):
            #super(__impl, self).__init__(*args, **kwargs)
            self._exchanges = {}
            self._queues = {}

        def _reset_all(self):
            self._exchanges = {}
            self._queues = {}

        def queue_declare(self, queue, **kwargs):
            if queue not in self._queues:
                logging.debug('Declaring queue %s', queue)
                self._queues[queue] = Queue(queue)

        def exchange_declare(self, exchange, type, *args, **kwargs):
            if exchange not in self._exchanges:
                logging.debug('Declaring exchange %s', exchange)
                self._exchanges[exchange] = Exchange(exchange, type)

        def queue_bind(self, queue, exchange, routing_key, **kwargs):
            logging.debug('Binding %s to %s with key %s',
                          queue, exchange, routing_key)
            self._exchanges[exchange].bind(self._queues[queue].push,
                                           routing_key)

        def get(self, queue, no_ack=False):
            if not queue in self._queues or not self._queues[queue].size():
                return None
            (message_data, content_type, content_encoding) = \
                    self._queues[queue].pop()
            message = Message(backend=self, body=message_data,
                              content_type=content_type,
                              content_encoding=content_encoding)
            logging.debug('Getting from %s: %s', queue, message)
            return message

        def prepare_message(self, message_data, delivery_mode,
                            content_type, content_encoding, **kwargs):
            """Prepare message for sending."""
            return (message_data, content_type, content_encoding)

        def publish(self, message, exchange, routing_key, **kwargs):
            if exchange in self._exchanges:
                self._exchanges[exchange].publish(
                        message, routing_key=routing_key)


    __instance = None

    def __init__(self, *args, **kwargs):
        if Backend.__instance is None:
            Backend.__instance = Backend.__impl(*args, **kwargs)
        self.__dict__['_Backend__instance'] = Backend.__instance

    def __getattr__(self, attr):
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, value):
        return setattr(self.__instance, attr, value)


def reset_all():
    Backend()._reset_all()

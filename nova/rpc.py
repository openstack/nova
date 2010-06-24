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

"""
AMQP-based RPC. Queues have consumers and publishers.
No fan-out support yet.
"""

import json
import logging
import sys
import uuid

from nova import vendor
from carrot import connection
from carrot import messaging
from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import task

from nova import exception
from nova import fakerabbit
from nova import flags


FLAGS = flags.FLAGS


_log = logging.getLogger('amqplib')
_log.setLevel(logging.WARN)


class Connection(connection.BrokerConnection):
    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            params = dict(hostname=FLAGS.rabbit_host,
                          port=FLAGS.rabbit_port,
                          userid=FLAGS.rabbit_userid,
                          password=FLAGS.rabbit_password,
                          virtual_host=FLAGS.rabbit_virtual_host)

            if FLAGS.fake_rabbit:
                params['backend_cls'] = fakerabbit.Backend

            cls._instance = cls(**params)
        return cls._instance


class Consumer(messaging.Consumer):
    # TODO(termie): it would be nice to give these some way of automatically
    #               cleaning up after themselves
    def attach_to_tornado(self, io_inst=None):
        from tornado import ioloop
        if io_inst is None:
            io_inst = ioloop.IOLoop.instance()

        injected = ioloop.PeriodicCallback(
            lambda: self.fetch(enable_callbacks=True), 100, io_loop=io_inst)
        injected.start()
        return injected

    attachToTornado = attach_to_tornado

    @exception.wrap_exception
    def fetch(self, *args, **kwargs):
        super(Consumer, self).fetch(*args, **kwargs)

    def attach_to_twisted(self):
        loop = task.LoopingCall(self.fetch, enable_callbacks=True)
        loop.start(interval=0.1)

class Publisher(messaging.Publisher):
    pass


class TopicConsumer(Consumer):
    exchange_type = "topic"
    def __init__(self, connection=None, topic="broadcast"):
        self.queue = topic
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        super(TopicConsumer, self).__init__(connection=connection)


class AdapterConsumer(TopicConsumer):
    def __init__(self, connection=None, topic="broadcast", proxy=None):
        _log.debug('Initing the Adapter Consumer for %s' % (topic))
        self.proxy = proxy
        super(AdapterConsumer, self).__init__(connection=connection, topic=topic)

    @exception.wrap_exception
    def receive(self, message_data, message):
        _log.debug('received %s' % (message_data))
        msg_id = message_data.pop('_msg_id', None)

        method = message_data.get('method')
        args = message_data.get('args', {})
        message.ack()
        if not method:
            # vish: we may not want to ack here, but that means that bad
            #       messages stay in the queue indefinitely, so for now
            #       we just log the message and send an error string back
            #       to the caller
            _log.warn('no method for message: %s' % (message_data))
            msg_reply(msg_id, 'No method for message: %s' % message_data)
            return

        node_func = getattr(self.proxy, str(method))
        node_args = dict((str(k), v) for k, v in args.iteritems())
        d = defer.maybeDeferred(node_func, **node_args)
        if msg_id:
            d.addCallback(lambda rval: msg_reply(msg_id, rval))
            d.addErrback(lambda e: msg_reply(msg_id, str(e)))
        return


class TopicPublisher(Publisher):
    exchange_type = "topic"
    def __init__(self, connection=None, topic="broadcast"):
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        super(TopicPublisher, self).__init__(connection=connection)


class DirectConsumer(Consumer):
    exchange_type = "direct"
    def __init__(self, connection=None, msg_id=None):
        self.queue = msg_id
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        super(DirectConsumer, self).__init__(connection=connection)


class DirectPublisher(Publisher):
    exchange_type = "direct"
    def __init__(self, connection=None, msg_id=None):
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        super(DirectPublisher, self).__init__(connection=connection)


def msg_reply(msg_id, reply):
    conn = Connection.instance()
    publisher = DirectPublisher(connection=conn, msg_id=msg_id)

    try:
        publisher.send({'result': reply})
    except TypeError:
        publisher.send(
                {'result': dict((k, repr(v))
                                for k, v in reply.__dict__.iteritems())
                 })
    publisher.close()


def call(topic, msg):
    _log.debug("Making asynchronous call...")
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    _log.debug("MSG_ID is %s" % (msg_id))

    conn = Connection.instance()
    d = defer.Deferred()
    consumer = DirectConsumer(connection=conn, msg_id=msg_id)
    consumer.register_callback(lambda data, message: d.callback(data))
    injected = consumer.attach_to_tornado()

    # clean up after the injected listened and return x
    d.addCallback(lambda x: injected.stop() and x or x)

    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()
    return d


def cast(topic, msg):
    _log.debug("Making asynchronous cast...")
    conn = Connection.instance()
    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()


def generic_response(message_data, message):
    _log.debug('response %s', message_data)
    message.ack()
    sys.exit(0)


def send_message(topic, message, wait=True):
    msg_id = uuid.uuid4().hex
    message.update({'_msg_id': msg_id})
    _log.debug('topic is %s', topic)
    _log.debug('message %s', message)

    if wait:
        consumer = messaging.Consumer(connection=Connection.instance(),
                                      queue=msg_id,
                                      exchange=msg_id,
                                      auto_delete=True,
                                      exchange_type="direct",
                                      routing_key=msg_id)
        consumer.register_callback(generic_response)

    publisher = messaging.Publisher(connection=Connection.instance(),
                                    exchange="nova",
                                    exchange_type="topic",
                                    routing_key=topic)
    publisher.send(message)
    publisher.close()

    if wait:
        consumer.wait()


# TODO: Replace with a docstring test
if __name__ == "__main__":
    send_message(sys.argv[1], json.loads(sys.argv[2]))

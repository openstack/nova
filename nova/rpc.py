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

"""
AMQP-based RPC. Queues have consumers and publishers.
No fan-out support yet.
"""

import json
import logging
import sys
import uuid

from carrot import connection as carrot_connection
from carrot import messaging
from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import fakerabbit
from nova import flags


FLAGS = flags.FLAGS


LOG = logging.getLogger('amqplib')
LOG.setLevel(logging.DEBUG)


class Connection(carrot_connection.BrokerConnection):
    """Connection instance object"""
    @classmethod
    def instance(cls):
        """Returns the instance"""
        if not hasattr(cls, '_instance'):
            params = dict(hostname=FLAGS.rabbit_host,
                          port=FLAGS.rabbit_port,
                          userid=FLAGS.rabbit_userid,
                          password=FLAGS.rabbit_password,
                          virtual_host=FLAGS.rabbit_virtual_host)

            if FLAGS.fake_rabbit:
                params['backend_cls'] = fakerabbit.Backend

            # NOTE(vish): magic is fun!
            # pylint: disable-msg=W0142
            cls._instance = cls(**params)
        return cls._instance

    @classmethod
    def recreate(cls):
        """Recreates the connection instance

        This is necessary to recover from some network errors/disconnects"""
        del cls._instance
        return cls.instance()


class Consumer(messaging.Consumer):
    """Consumer base class

    Contains methods for connecting the fetch method to async loops
    """
    def __init__(self, *args, **kwargs):
        self.failed_connection = False
        super(Consumer, self).__init__(*args, **kwargs)

    def fetch(self, no_ack=None, auto_ack=None, enable_callbacks=False):
        """Wraps the parent fetch with some logic for failed connections"""
        # TODO(vish): the logic for failed connections and logging should be
        #             refactored into some sort of connection manager object
        try:
            if self.failed_connection:
                # NOTE(vish): conn is defined in the parent class, we can
                #             recreate it as long as we create the backend too
                # pylint: disable-msg=W0201
                self.conn = Connection.recreate()
                self.backend = self.conn.create_backend()
            super(Consumer, self).fetch(no_ack, auto_ack, enable_callbacks)
            if self.failed_connection:
                logging.error("Reconnected to queue")
                self.failed_connection = False
        # NOTE(vish): This is catching all errors because we really don't
        #             exceptions to be logged 10 times a second if some
        #             persistent failure occurs.
        except Exception:  # pylint: disable-msg=W0703
            if not self.failed_connection:
                logging.exception("Failed to fetch message from queue")
                self.failed_connection = True

    def attach_to_twisted(self):
        """Attach a callback to twisted that fires 10 times a second"""
        loop = task.LoopingCall(self.fetch, enable_callbacks=True)
        loop.start(interval=0.1)
        return loop


class Publisher(messaging.Publisher):
    """Publisher base class"""
    pass


class TopicConsumer(Consumer):
    """Consumes messages on a specific topic"""
    exchange_type = "topic"

    def __init__(self, connection=None, topic="broadcast"):
        self.queue = topic
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = False
        super(TopicConsumer, self).__init__(connection=connection)


class AdapterConsumer(TopicConsumer):
    """Calls methods on a proxy object based on method and args"""
    def __init__(self, connection=None, topic="broadcast", proxy=None):
        LOG.debug('Initing the Adapter Consumer for %s' % (topic))
        self.proxy = proxy
        super(AdapterConsumer, self).__init__(connection=connection,
                                              topic=topic)

    @exception.wrap_exception
    def receive(self, message_data, message):
        """Magically looks for a method on the proxy object and calls it

        Message data should be a dictionary with two keys:
            method: string representing the method to call
            args: dictionary of arg: value

        Example: {'method': 'echo', 'args': {'value': 42}}
        """
        LOG.debug('received %s' % (message_data))
        msg_id = message_data.pop('_msg_id', None)

        method = message_data.get('method')
        args = message_data.get('args', {})
        message.ack()
        if not method:
            # NOTE(vish): we may not want to ack here, but that means that bad
            #             messages stay in the queue indefinitely, so for now
            #             we just log the message and send an error string
            #             back to the caller
            LOG.warn('no method for message: %s' % (message_data))
            msg_reply(msg_id, 'No method for message: %s' % message_data)
            return

        node_func = getattr(self.proxy, str(method))
        node_args = dict((str(k), v) for k, v in args.iteritems())
        # NOTE(vish): magic is fun!
        # pylint: disable-msg=W0142
        d = defer.maybeDeferred(node_func, **node_args)
        if msg_id:
            d.addCallback(lambda rval: msg_reply(msg_id, rval, None))
            d.addErrback(lambda e: msg_reply(msg_id, None, e))
        return


class TopicPublisher(Publisher):
    """Publishes messages on a specific topic"""
    exchange_type = "topic"

    def __init__(self, connection=None, topic="broadcast"):
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = False
        super(TopicPublisher, self).__init__(connection=connection)


class DirectConsumer(Consumer):
    """Consumes messages directly on a channel specified by msg_id"""
    exchange_type = "direct"

    def __init__(self, connection=None, msg_id=None):
        self.queue = msg_id
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        super(DirectConsumer, self).__init__(connection=connection)


class DirectPublisher(Publisher):
    """Publishes messages directly on a channel specified by msg_id"""
    exchange_type = "direct"

    def __init__(self, connection=None, msg_id=None):
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        super(DirectPublisher, self).__init__(connection=connection)


def msg_reply(msg_id, reply=None, failure=None):
    """Sends a reply or an error on the channel signified by msg_id

    failure should be a twisted failure object"""
    if failure:
        message = failure.getErrorMessage()
        traceback = failure.getTraceback()
        logging.error("Returning exception %s to caller", message)
        logging.error(traceback)
        failure = (failure.type.__name__, str(failure.value), traceback)
    conn = Connection.instance()
    publisher = DirectPublisher(connection=conn, msg_id=msg_id)
    try:
        publisher.send({'result': reply, 'failure': failure})
    except TypeError:
        publisher.send(
                {'result': dict((k, repr(v))
                                for k, v in reply.__dict__.iteritems()),
                 'failure': failure})
    publisher.close()


class RemoteError(exception.Error):
    """Signifies that a remote class has raised an exception

    Containes a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevent info."""
    def __init__(self, exc_type, value, traceback):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__("%s %s\n%s" % (exc_type,
                                                         value,
                                                         traceback))


def call(topic, msg):
    """Sends a message on a topic and wait for a response"""
    LOG.debug("Making asynchronous call...")
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug("MSG_ID is %s" % (msg_id))
    conn = Connection.instance()
    d = defer.Deferred()
    consumer = DirectConsumer(connection=conn, msg_id=msg_id)

    def deferred_receive(data, message):
        """Acks message and callbacks or errbacks"""
        message.ack()
        if data['failure']:
            return d.errback(RemoteError(*data['failure']))
        else:
            return d.callback(data['result'])

    consumer.register_callback(deferred_receive)
    injected = consumer.attach_to_twisted()

    # clean up after the injected listened and return x
    d.addCallback(lambda x: injected.stop() and x or x)

    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()
    return d


def cast(topic, msg):
    """Sends a message on a topic without waiting for a response"""
    LOG.debug("Making asynchronous cast...")
    conn = Connection.instance()
    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()


def generic_response(message_data, message):
    """Logs a result and exits"""
    LOG.debug('response %s', message_data)
    message.ack()
    sys.exit(0)


def send_message(topic, message, wait=True):
    """Sends a message for testing"""
    msg_id = uuid.uuid4().hex
    message.update({'_msg_id': msg_id})
    LOG.debug('topic is %s', topic)
    LOG.debug('message %s', message)

    if wait:
        consumer = messaging.Consumer(connection=Connection.instance(),
                                      queue=msg_id,
                                      exchange=msg_id,
                                      auto_delete=True,
                                      exchange_type="direct",
                                      routing_key=msg_id)
        consumer.register_callback(generic_response)

    publisher = messaging.Publisher(connection=Connection.instance(),
                                    exchange=FLAGS.control_exchange,
                                    durable=False,
                                    exchange_type="topic",
                                    routing_key=topic)
    publisher.send(message)
    publisher.close()

    if wait:
        consumer.wait()


if __name__ == "__main__":
    # NOTE(vish): you can send messages from the command line using
    #             topic and a json sting representing a dictionary
    #             for the method
    send_message(sys.argv[1], json.loads(sys.argv[2]))

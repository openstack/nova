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

"""AMQP-based RPC.

Queues have consumers and publishers.

No fan-out support yet.

"""

import json
import sys
import time
import traceback
import types
import uuid

from carrot import connection as carrot_connection
from carrot import messaging
import eventlet
from eventlet import greenpool
from eventlet import pools
from eventlet import queue
import greenlet

from nova import context
from nova import exception
from nova import fakerabbit
from nova import flags
from nova.rpc.common import RemoteError, LOG

# Needed for tests
eventlet.monkey_patch()

FLAGS = flags.FLAGS


class Connection(carrot_connection.BrokerConnection):
    """Connection instance object."""

    def __init__(self, *args, **kwargs):
        super(Connection, self).__init__(*args, **kwargs)
        self._rpc_consumers = []
        self._rpc_consumer_thread = None

    @classmethod
    def instance(cls, new=True):
        """Returns the instance."""
        if new or not hasattr(cls, '_instance'):
            params = dict(hostname=FLAGS.rabbit_host,
                          port=FLAGS.rabbit_port,
                          ssl=FLAGS.rabbit_use_ssl,
                          userid=FLAGS.rabbit_userid,
                          password=FLAGS.rabbit_password,
                          virtual_host=FLAGS.rabbit_virtual_host)

            if FLAGS.fake_rabbit:
                params['backend_cls'] = fakerabbit.Backend

            # NOTE(vish): magic is fun!
            # pylint: disable=W0142
            if new:
                return cls(**params)
            else:
                cls._instance = cls(**params)
        return cls._instance

    @classmethod
    def recreate(cls):
        """Recreates the connection instance.

        This is necessary to recover from some network errors/disconnects.

        """
        try:
            del cls._instance
        except AttributeError, e:
            # The _instance stuff is for testing purposes. Usually we don't use
            # it. So don't freak out if it doesn't exist.
            pass
        return cls.instance()

    def close(self):
        self.cancel_consumer_thread()
        for consumer in self._rpc_consumers:
            try:
                consumer.close()
            except Exception:
                # ignore all errors
                pass
        self._rpc_consumers = []
        super(Connection, self).close()

    def consume_in_thread(self):
        """Consumer from all queues/consumers in a greenthread"""

        consumer_set = ConsumerSet(connection=self,
                consumer_list=self._rpc_consumers)

        def _consumer_thread():
            try:
                consumer_set.wait()
            except greenlet.GreenletExit:
                return
        if self._rpc_consumer_thread is None:
            self._rpc_consumer_thread = eventlet.spawn(_consumer_thread)
        return self._rpc_consumer_thread

    def cancel_consumer_thread(self):
        """Cancel a consumer thread"""
        if self._rpc_consumer_thread is not None:
            self._rpc_consumer_thread.kill()
            try:
                self._rpc_consumer_thread.wait()
            except greenlet.GreenletExit:
                pass
            self._rpc_consumer_thread = None

    def create_consumer(self, topic, proxy, fanout=False):
        """Create a consumer that calls methods in the proxy"""
        if fanout:
            consumer = FanoutAdapterConsumer(
                    connection=self,
                    topic=topic,
                    proxy=proxy)
        else:
            consumer = TopicAdapterConsumer(
                    connection=self,
                    topic=topic,
                    proxy=proxy)
        self._rpc_consumers.append(consumer)


class Pool(pools.Pool):
    """Class that implements a Pool of Connections."""

    # TODO(comstud): Timeout connections not used in a while
    def create(self):
        LOG.debug('Pool creating new connection')
        return Connection.instance(new=True)

# Create a ConnectionPool to use for RPC calls.  We'll order the
# pool as a stack (LIFO), so that we can potentially loop through and
# timeout old unused connections at some point
ConnectionPool = Pool(
        max_size=FLAGS.rpc_conn_pool_size,
        order_as_stack=True)


class Consumer(messaging.Consumer):
    """Consumer base class.

    Contains methods for connecting the fetch method to async loops.

    """

    def __init__(self, *args, **kwargs):
        max_retries = FLAGS.rabbit_max_retries
        sleep_time = FLAGS.rabbit_retry_interval
        tries = 0
        while True:
            tries += 1
            if tries > 1:
                time.sleep(sleep_time)
                # backoff for next retry attempt.. if there is one
                sleep_time += FLAGS.rabbit_retry_backoff
                if sleep_time > 30:
                    sleep_time = 30
            try:
                super(Consumer, self).__init__(*args, **kwargs)
                self.failed_connection = False
                break
            except Exception as e:  # Catching all because carrot sucks
                self.failed_connection = True
                if max_retries > 0 and tries == max_retries:
                    break
                fl_host = FLAGS.rabbit_host
                fl_port = FLAGS.rabbit_port
                fl_intv = sleep_time
                LOG.error(_('AMQP server on %(fl_host)s:%(fl_port)d is'
                            ' unreachable: %(e)s. Trying again in %(fl_intv)d'
                            ' seconds.') % locals())
        if self.failed_connection:
            LOG.error(_('Unable to connect to AMQP server '
                        'after %(tries)d tries. Shutting down.') % locals())
            sys.exit(1)

    def fetch(self, no_ack=None, auto_ack=None, enable_callbacks=False):
        """Wraps the parent fetch with some logic for failed connection."""
        # TODO(vish): the logic for failed connections and logging should be
        #             refactored into some sort of connection manager object
        try:
            if self.failed_connection:
                # NOTE(vish): connection is defined in the parent class, we can
                #             recreate it as long as we create the backend too
                # pylint: disable=W0201
                self.connection = Connection.recreate()
                self.backend = self.connection.create_backend()
                self.declare()
            return super(Consumer, self).fetch(no_ack,
                                               auto_ack,
                                               enable_callbacks)
            if self.failed_connection:
                LOG.error(_('Reconnected to queue'))
                self.failed_connection = False
        # NOTE(vish): This is catching all errors because we really don't
        #             want exceptions to be logged 10 times a second if some
        #             persistent failure occurs.
        except Exception, e:  # pylint: disable=W0703
            if not self.failed_connection:
                LOG.exception(_('Failed to fetch message from queue: %s' % e))
                self.failed_connection = True


class AdapterConsumer(Consumer):
    """Calls methods on a proxy object based on method and args."""

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        LOG.debug(_('Initing the Adapter Consumer for %s') % topic)
        self.proxy = proxy
        self.pool = greenpool.GreenPool(FLAGS.rpc_thread_pool_size)
        super(AdapterConsumer, self).__init__(connection=connection,
                                              topic=topic)
        self.register_callback(self.process_data)

    def process_data(self, message_data, message):
        """Consumer callback to call a method on a proxy object.

        Parses the message for validity and fires off a thread to call the
        proxy object method.

        Message data should be a dictionary with two keys:
            method: string representing the method to call
            args: dictionary of arg: value

        Example: {'method': 'echo', 'args': {'value': 42}}

        """
        LOG.debug(_('received %s') % message_data)
        # This will be popped off in _unpack_context
        msg_id = message_data.get('_msg_id', None)
        ctxt = _unpack_context(message_data)

        method = message_data.get('method')
        args = message_data.get('args', {})
        message.ack()
        if not method:
            # NOTE(vish): we may not want to ack here, but that means that bad
            #             messages stay in the queue indefinitely, so for now
            #             we just log the message and send an error string
            #             back to the caller
            LOG.warn(_('no method for message: %s') % message_data)
            if msg_id:
                msg_reply(msg_id,
                          _('No method for message: %s') % message_data)
            return
        self.pool.spawn_n(self._process_data, msg_id, ctxt, method, args)

    @exception.wrap_exception()
    def _process_data(self, msg_id, ctxt, method, args):
        """Thread that maigcally looks for a method on the proxy
        object and calls it.
        """

        node_func = getattr(self.proxy, str(method))
        node_args = dict((str(k), v) for k, v in args.iteritems())
        # NOTE(vish): magic is fun!
        try:
            rval = node_func(context=ctxt, **node_args)
            if msg_id:
                # Check if the result was a generator
                if isinstance(rval, types.GeneratorType):
                    for x in rval:
                        msg_reply(msg_id, x, None)
                else:
                    msg_reply(msg_id, rval, None)

                # This final None tells multicall that it is done.
                msg_reply(msg_id, None, None)
            elif isinstance(rval, types.GeneratorType):
                # NOTE(vish): this iterates through the generator
                list(rval)
        except Exception as e:
            LOG.exception('Exception during message handling')
            if msg_id:
                msg_reply(msg_id, None, sys.exc_info())
        return


class TopicAdapterConsumer(AdapterConsumer):
    """Consumes messages on a specific topic."""

    exchange_type = 'topic'

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        self.queue = topic
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = FLAGS.rabbit_durable_queues
        super(TopicAdapterConsumer, self).__init__(connection=connection,
                                    topic=topic, proxy=proxy)


class FanoutAdapterConsumer(AdapterConsumer):
    """Consumes messages from a fanout exchange."""

    exchange_type = 'fanout'

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        self.exchange = '%s_fanout' % topic
        self.routing_key = topic
        unique = uuid.uuid4().hex
        self.queue = '%s_fanout_%s' % (topic, unique)
        self.durable = False
        # Fanout creates unique queue names, so we should auto-remove
        # them when done, so they're not left around on restart.
        # Also, we're the only one that should be consuming.  exclusive
        # implies auto_delete, so we'll just set that..
        self.exclusive = True
        LOG.info(_('Created "%(exchange)s" fanout exchange '
                   'with "%(key)s" routing key'),
                 dict(exchange=self.exchange, key=self.routing_key))
        super(FanoutAdapterConsumer, self).__init__(connection=connection,
                                    topic=topic, proxy=proxy)


class ConsumerSet(object):
    """Groups consumers to listen on together on a single connection."""

    def __init__(self, connection, consumer_list):
        self.consumer_list = set(consumer_list)
        self.consumer_set = None
        self.enabled = True
        self.init(connection)

    def init(self, conn):
        if not conn:
            conn = Connection.instance(new=True)
        if self.consumer_set:
            self.consumer_set.close()
        self.consumer_set = messaging.ConsumerSet(conn)
        for consumer in self.consumer_list:
            consumer.connection = conn
            # consumer.backend is set for us
            self.consumer_set.add_consumer(consumer)

    def reconnect(self):
        self.init(None)

    def wait(self, limit=None):
        running = True
        while running:
            it = self.consumer_set.iterconsume(limit=limit)
            if not it:
                break
            while True:
                try:
                    it.next()
                except StopIteration:
                    return
                except greenlet.GreenletExit:
                    running = False
                    break
                except Exception as e:
                    LOG.exception(_("Exception while processing consumer"))
                    self.reconnect()
                    # Break to outer loop
                    break

    def close(self):
        self.consumer_set.close()


class Publisher(messaging.Publisher):
    """Publisher base class."""
    pass


class TopicPublisher(Publisher):
    """Publishes messages on a specific topic."""

    exchange_type = 'topic'

    def __init__(self, connection=None, topic='broadcast'):
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = FLAGS.rabbit_durable_queues
        super(TopicPublisher, self).__init__(connection=connection)


class FanoutPublisher(Publisher):
    """Publishes messages to a fanout exchange."""

    exchange_type = 'fanout'

    def __init__(self, topic, connection=None):
        self.exchange = '%s_fanout' % topic
        self.queue = '%s_fanout' % topic
        self.durable = False
        self.auto_delete = True
        LOG.info(_('Creating "%(exchange)s" fanout exchange'),
                 dict(exchange=self.exchange))
        super(FanoutPublisher, self).__init__(connection=connection)


class DirectConsumer(Consumer):
    """Consumes messages directly on a channel specified by msg_id."""

    exchange_type = 'direct'

    def __init__(self, connection=None, msg_id=None):
        self.queue = msg_id
        self.routing_key = msg_id
        self.exchange = msg_id
        self.durable = False
        self.auto_delete = True
        self.exclusive = True
        super(DirectConsumer, self).__init__(connection=connection)


class DirectPublisher(Publisher):
    """Publishes messages directly on a channel specified by msg_id."""

    exchange_type = 'direct'

    def __init__(self, connection=None, msg_id=None):
        self.routing_key = msg_id
        self.exchange = msg_id
        self.durable = False
        self.auto_delete = True
        super(DirectPublisher, self).__init__(connection=connection)


def msg_reply(msg_id, reply=None, failure=None):
    """Sends a reply or an error on the channel signified by msg_id.

    Failure should be a sys.exc_info() tuple.

    """
    if failure:
        message = str(failure[1])
        tb = traceback.format_exception(*failure)
        LOG.error(_("Returning exception %s to caller"), message)
        LOG.error(tb)
        failure = (failure[0].__name__, str(failure[1]), tb)

    with ConnectionPool.item() as conn:
        publisher = DirectPublisher(connection=conn, msg_id=msg_id)
        try:
            publisher.send({'result': reply, 'failure': failure})
        except TypeError:
            publisher.send(
                    {'result': dict((k, repr(v))
                                    for k, v in reply.__dict__.iteritems()),
                     'failure': failure})

        publisher.close()


def _unpack_context(msg):
    """Unpack context from msg."""
    context_dict = {}
    for key in list(msg.keys()):
        # NOTE(vish): Some versions of python don't like unicode keys
        #             in kwargs.
        key = str(key)
        if key.startswith('_context_'):
            value = msg.pop(key)
            context_dict[key[9:]] = value
    context_dict['msg_id'] = msg.pop('_msg_id', None)
    LOG.debug(_('unpacked context: %s'), context_dict)
    return RpcContext.from_dict(context_dict)


def _pack_context(msg, context):
    """Pack context into msg.

    Values for message keys need to be less than 255 chars, so we pull
    context out into a bunch of separate keys. If we want to support
    more arguments in rabbit messages, we may want to do the same
    for args at some point.

    """
    context_d = dict([('_context_%s' % key, value)
                      for (key, value) in context.to_dict().iteritems()])
    msg.update(context_d)


class RpcContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        msg_id = kwargs.pop('msg_id', None)
        self.msg_id = msg_id
        super(RpcContext, self).__init__(*args, **kwargs)

    def reply(self, *args, **kwargs):
        msg_reply(self.msg_id, *args, **kwargs)


def multicall(context, topic, msg):
    """Make a call that returns multiple times."""
    LOG.debug(_('Making asynchronous call on %s ...'), topic)
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug(_('MSG_ID is %s') % (msg_id))
    _pack_context(msg, context)

    con_conn = ConnectionPool.get()
    consumer = DirectConsumer(connection=con_conn, msg_id=msg_id)
    wait_msg = MulticallWaiter(consumer)
    consumer.register_callback(wait_msg)

    publisher = TopicPublisher(connection=con_conn, topic=topic)
    publisher.send(msg)
    publisher.close()

    return wait_msg


class MulticallWaiter(object):
    def __init__(self, consumer):
        self._consumer = consumer
        self._results = queue.Queue()
        self._closed = False

    def close(self):
        self._closed = True
        self._consumer.close()
        ConnectionPool.put(self._consumer.connection)

    def __call__(self, data, message):
        """Acks message and sets result."""
        message.ack()
        if data['failure']:
            self._results.put(RemoteError(*data['failure']))
        else:
            self._results.put(data['result'])

    def __iter__(self):
        return self.wait()

    def wait(self):
        while True:
            rv = None
            while rv is None and not self._closed:
                try:
                    rv = self._consumer.fetch(enable_callbacks=True)
                except Exception:
                    self.close()
                    raise
                time.sleep(0.01)

            result = self._results.get()
            if isinstance(result, Exception):
                self.close()
                raise result
            if result == None:
                self.close()
                raise StopIteration
            yield result


def create_connection(new=True):
    """Create a connection"""
    return Connection.instance(new=new)


def call(context, topic, msg):
    """Sends a message on a topic and wait for a response."""
    rv = multicall(context, topic, msg)
    # NOTE(vish): return the last result from the multicall
    rv = list(rv)
    if not rv:
        return
    return rv[-1]


def cast(context, topic, msg):
    """Sends a message on a topic without waiting for a response."""
    LOG.debug(_('Making asynchronous cast on %s...'), topic)
    _pack_context(msg, context)
    with ConnectionPool.item() as conn:
        publisher = TopicPublisher(connection=conn, topic=topic)
        publisher.send(msg)
        publisher.close()


def fanout_cast(context, topic, msg):
    """Sends a message on a fanout exchange without waiting for a response."""
    LOG.debug(_('Making asynchronous fanout cast...'))
    _pack_context(msg, context)
    with ConnectionPool.item() as conn:
        publisher = FanoutPublisher(topic, connection=conn)
        publisher.send(msg)
        publisher.close()


def generic_response(message_data, message):
    """Logs a result and exits."""
    LOG.debug(_('response %s'), message_data)
    message.ack()
    sys.exit(0)


def send_message(topic, message, wait=True):
    """Sends a message for testing."""
    msg_id = uuid.uuid4().hex
    message.update({'_msg_id': msg_id})
    LOG.debug(_('topic is %s'), topic)
    LOG.debug(_('message %s'), message)

    if wait:
        consumer = messaging.Consumer(connection=Connection.instance(),
                                      queue=msg_id,
                                      exchange=msg_id,
                                      auto_delete=True,
                                      exchange_type='direct',
                                      routing_key=msg_id)
        consumer.register_callback(generic_response)

    publisher = messaging.Publisher(connection=Connection.instance(),
                                    exchange=FLAGS.control_exchange,
                                    durable=FLAGS.rabbit_durable_queues,
                                    exchange_type='topic',
                                    routing_key=topic)
    publisher.send(message)
    publisher.close()

    if wait:
        consumer.wait()
        consumer.close()


if __name__ == '__main__':
    # You can send messages from the command line using
    # topic and a json string representing a dictionary
    # for the method
    send_message(sys.argv[1], json.loads(sys.argv[2]))

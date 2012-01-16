# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
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

import inspect
import itertools
import sys
import time
import traceback
import uuid

import eventlet
from eventlet import greenpool
from eventlet import pools
import greenlet
import kombu
import kombu.entity
import kombu.messaging
import kombu.connection

from nova import context
from nova import exception
from nova import flags
from nova import local
from nova.rpc import common as rpc_common

FLAGS = flags.FLAGS
LOG = rpc_common.LOG


class ConsumerBase(object):
    """Consumer base class."""

    def __init__(self, channel, callback, tag, **kwargs):
        """Declare a queue on an amqp channel.

        'channel' is the amqp channel to use
        'callback' is the callback to call when messages are received
        'tag' is a unique ID for the consumer on the channel

        queue name, exchange name, and other kombu options are
        passed in here as a dictionary.
        """
        self.callback = callback
        self.tag = str(tag)
        self.kwargs = kwargs
        self.queue = None
        self.reconnect(channel)

    def reconnect(self, channel):
        """Re-declare the queue after a rabbit reconnect"""
        self.channel = channel
        self.kwargs['channel'] = channel
        self.queue = kombu.entity.Queue(**self.kwargs)
        self.queue.declare()

    def consume(self, *args, **kwargs):
        """Actually declare the consumer on the amqp channel.  This will
        start the flow of messages from the queue.  Using the
        Connection.iterconsume() iterator will process the messages,
        calling the appropriate callback.

        If a callback is specified in kwargs, use that.  Otherwise,
        use the callback passed during __init__()

        If kwargs['nowait'] is True, then this call will block until
        a message is read.

        Messages will automatically be acked if the callback doesn't
        raise an exception
        """

        options = {'consumer_tag': self.tag}
        options['nowait'] = kwargs.get('nowait', False)
        callback = kwargs.get('callback', self.callback)
        if not callback:
            raise ValueError("No callback defined")

        def _callback(raw_message):
            message = self.channel.message_to_python(raw_message)
            callback(message.payload)
            message.ack()

        self.queue.consume(*args, callback=_callback, **options)

    def cancel(self):
        """Cancel the consuming from the queue, if it has started"""
        try:
            self.queue.cancel(self.tag)
        except KeyError, e:
            # NOTE(comstud): Kludge to get around a amqplib bug
            if str(e) != "u'%s'" % self.tag:
                raise
        self.queue = None


class DirectConsumer(ConsumerBase):
    """Queue/consumer class for 'direct'"""

    def __init__(self, channel, msg_id, callback, tag, **kwargs):
        """Init a 'direct' queue.

        'channel' is the amqp channel to use
        'msg_id' is the msg_id to listen on
        'callback' is the callback to call when messages are received
        'tag' is a unique ID for the consumer on the channel

        Other kombu options may be passed
        """
        # Default options
        options = {'durable': False,
                'auto_delete': True,
                'exclusive': True}
        options.update(kwargs)
        exchange = kombu.entity.Exchange(
                name=msg_id,
                type='direct',
                durable=options['durable'],
                auto_delete=options['auto_delete'])
        super(DirectConsumer, self).__init__(
                channel,
                callback,
                tag,
                name=msg_id,
                exchange=exchange,
                routing_key=msg_id,
                **options)


class TopicConsumer(ConsumerBase):
    """Consumer class for 'topic'"""

    def __init__(self, channel, topic, callback, tag, **kwargs):
        """Init a 'topic' queue.

        'channel' is the amqp channel to use
        'topic' is the topic to listen on
        'callback' is the callback to call when messages are received
        'tag' is a unique ID for the consumer on the channel

        Other kombu options may be passed
        """
        # Default options
        options = {'durable': FLAGS.rabbit_durable_queues,
                'auto_delete': False,
                'exclusive': False}
        options.update(kwargs)
        exchange = kombu.entity.Exchange(
                name=FLAGS.control_exchange,
                type='topic',
                durable=options['durable'],
                auto_delete=options['auto_delete'])
        super(TopicConsumer, self).__init__(
                channel,
                callback,
                tag,
                name=topic,
                exchange=exchange,
                routing_key=topic,
                **options)


class FanoutConsumer(ConsumerBase):
    """Consumer class for 'fanout'"""

    def __init__(self, channel, topic, callback, tag, **kwargs):
        """Init a 'fanout' queue.

        'channel' is the amqp channel to use
        'topic' is the topic to listen on
        'callback' is the callback to call when messages are received
        'tag' is a unique ID for the consumer on the channel

        Other kombu options may be passed
        """
        unique = uuid.uuid4().hex
        exchange_name = '%s_fanout' % topic
        queue_name = '%s_fanout_%s' % (topic, unique)

        # Default options
        options = {'durable': False,
                'auto_delete': True,
                'exclusive': True}
        options.update(kwargs)
        exchange = kombu.entity.Exchange(
                name=exchange_name,
                type='fanout',
                durable=options['durable'],
                auto_delete=options['auto_delete'])
        super(FanoutConsumer, self).__init__(
                channel,
                callback,
                tag,
                name=queue_name,
                exchange=exchange,
                routing_key=topic,
                **options)


class Publisher(object):
    """Base Publisher class"""

    def __init__(self, channel, exchange_name, routing_key, **kwargs):
        """Init the Publisher class with the exchange_name, routing_key,
        and other options
        """
        self.exchange_name = exchange_name
        self.routing_key = routing_key
        self.kwargs = kwargs
        self.reconnect(channel)

    def reconnect(self, channel):
        """Re-establish the Producer after a rabbit reconnection"""
        self.exchange = kombu.entity.Exchange(name=self.exchange_name,
                **self.kwargs)
        self.producer = kombu.messaging.Producer(exchange=self.exchange,
                channel=channel, routing_key=self.routing_key)

    def send(self, msg):
        """Send a message"""
        self.producer.publish(msg)


class DirectPublisher(Publisher):
    """Publisher class for 'direct'"""
    def __init__(self, channel, msg_id, **kwargs):
        """init a 'direct' publisher.

        Kombu options may be passed as keyword args to override defaults
        """

        options = {'durable': False,
                'auto_delete': True,
                'exclusive': True}
        options.update(kwargs)
        super(DirectPublisher, self).__init__(channel,
                msg_id,
                msg_id,
                type='direct',
                **options)


class TopicPublisher(Publisher):
    """Publisher class for 'topic'"""
    def __init__(self, channel, topic, **kwargs):
        """init a 'topic' publisher.

        Kombu options may be passed as keyword args to override defaults
        """
        options = {'durable': FLAGS.rabbit_durable_queues,
                'auto_delete': False,
                'exclusive': False}
        options.update(kwargs)
        super(TopicPublisher, self).__init__(channel,
                FLAGS.control_exchange,
                topic,
                type='topic',
                **options)


class FanoutPublisher(Publisher):
    """Publisher class for 'fanout'"""
    def __init__(self, channel, topic, **kwargs):
        """init a 'fanout' publisher.

        Kombu options may be passed as keyword args to override defaults
        """
        options = {'durable': False,
                'auto_delete': True,
                'exclusive': True}
        options.update(kwargs)
        super(FanoutPublisher, self).__init__(channel,
                '%s_fanout' % topic,
                None,
                type='fanout',
                **options)


class NotifyPublisher(TopicPublisher):
    """Publisher class for 'notify'"""

    def __init__(self, *args, **kwargs):
        self.durable = kwargs.pop('durable', FLAGS.rabbit_durable_queues)
        super(NotifyPublisher, self).__init__(*args, **kwargs)

    def reconnect(self, channel):
        super(NotifyPublisher, self).reconnect(channel)

        # NOTE(jerdfelt): Normally the consumer would create the queue, but
        # we do this to ensure that messages don't get dropped if the
        # consumer is started after we do
        queue = kombu.entity.Queue(channel=channel,
                exchange=self.exchange,
                durable=self.durable,
                name=self.routing_key,
                routing_key=self.routing_key)
        queue.declare()


class Connection(object):
    """Connection object."""

    def __init__(self):
        self.consumers = []
        self.consumer_thread = None
        self.max_retries = FLAGS.rabbit_max_retries
        # Try forever?
        if self.max_retries <= 0:
            self.max_retries = None
        self.interval_start = FLAGS.rabbit_retry_interval
        self.interval_stepping = FLAGS.rabbit_retry_backoff
        # max retry-interval = 30 seconds
        self.interval_max = 30
        self.memory_transport = False

        self.params = dict(hostname=FLAGS.rabbit_host,
                          port=FLAGS.rabbit_port,
                          userid=FLAGS.rabbit_userid,
                          password=FLAGS.rabbit_password,
                          virtual_host=FLAGS.rabbit_virtual_host)
        if FLAGS.fake_rabbit:
            self.params['transport'] = 'memory'
            self.memory_transport = True
        else:
            self.memory_transport = False
        self.connection = None
        self.reconnect()

    def _connect(self):
        """Connect to rabbit.  Re-establish any queues that may have
        been declared before if we are reconnecting.  Exceptions should
        be handled by the caller.
        """
        if self.connection:
            LOG.info(_("Reconnecting to AMQP server on "
                    "%(hostname)s:%(port)d") % self.params)
            try:
                self.connection.close()
            except self.connection_errors:
                pass
            # Setting this in case the next statement fails, though
            # it shouldn't be doing any network operations, yet.
            self.connection = None
        self.connection = kombu.connection.BrokerConnection(
                **self.params)
        self.connection_errors = self.connection.connection_errors
        if self.memory_transport:
            # Kludge to speed up tests.
            self.connection.transport.polling_interval = 0.0
        self.consumer_num = itertools.count(1)
        self.connection.connect()
        self.channel = self.connection.channel()
        # work around 'memory' transport bug in 1.1.3
        if self.memory_transport:
            self.channel._new_queue('ae.undeliver')
        for consumer in self.consumers:
            consumer.reconnect(self.channel)
        LOG.info(_('Connected to AMQP server on '
                '%(hostname)s:%(port)d' % self.params))

    def reconnect(self):
        """Handles reconnecting and re-establishing queues.
        Will retry up to self.max_retries number of times.
        self.max_retries = 0 means to retry forever.
        Sleep between tries, starting at self.interval_start
        seconds, backing off self.interval_stepping number of seconds
        each attempt.
        """

        attempt = 0
        while True:
            attempt += 1
            try:
                self._connect()
                return
            except self.connection_errors, e:
                pass
            except Exception, e:
                # NOTE(comstud): Unfortunately it's possible for amqplib
                # to return an error not covered by its transport
                # connection_errors in the case of a timeout waiting for
                # a protocol response.  (See paste link in LP888621)
                # So, we check all exceptions for 'timeout' in them
                # and try to reconnect in this case.
                if 'timeout' not in str(e):
                    raise

            log_info = {}
            log_info['err_str'] = str(e)
            log_info['max_retries'] = self.max_retries
            log_info.update(self.params)

            if self.max_retries and attempt == self.max_retries:
                LOG.exception(_('Unable to connect to AMQP server on '
                        '%(hostname)s:%(port)d after %(max_retries)d '
                        'tries: %(err_str)s') % log_info)
                # NOTE(comstud): Copied from original code.  There's
                # really no better recourse because if this was a queue we
                # need to consume on, we have no way to consume anymore.
                sys.exit(1)

            if attempt == 1:
                sleep_time = self.interval_start or 1
            elif attempt > 1:
                sleep_time += self.interval_stepping
            if self.interval_max:
                sleep_time = min(sleep_time, self.interval_max)

            log_info['sleep_time'] = sleep_time
            LOG.exception(_('AMQP server on %(hostname)s:%(port)d is'
                    ' unreachable: %(err_str)s. Trying again in '
                    '%(sleep_time)d seconds.') % log_info)
            time.sleep(sleep_time)

    def ensure(self, error_callback, method, *args, **kwargs):
        while True:
            try:
                return method(*args, **kwargs)
            except self.connection_errors, e:
                pass
            except Exception, e:
                # NOTE(comstud): Unfortunately it's possible for amqplib
                # to return an error not covered by its transport
                # connection_errors in the case of a timeout waiting for
                # a protocol response.  (See paste link in LP888621)
                # So, we check all exceptions for 'timeout' in them
                # and try to reconnect in this case.
                if 'timeout' not in str(e):
                    raise
            if error_callback:
                error_callback(e)
            self.reconnect()

    def get_channel(self):
        """Convenience call for bin/clear_rabbit_queues"""
        return self.channel

    def close(self):
        """Close/release this connection"""
        self.cancel_consumer_thread()
        self.connection.release()
        self.connection = None

    def reset(self):
        """Reset a connection so it can be used again"""
        self.cancel_consumer_thread()
        self.channel.close()
        self.channel = self.connection.channel()
        # work around 'memory' transport bug in 1.1.3
        if self.memory_transport:
            self.channel._new_queue('ae.undeliver')
        self.consumers = []

    def declare_consumer(self, consumer_cls, topic, callback):
        """Create a Consumer using the class that was passed in and
        add it to our list of consumers
        """

        def _connect_error(exc):
            log_info = {'topic': topic, 'err_str': str(exc)}
            LOG.error(_("Failed to declare consumer for topic '%(topic)s': "
                "%(err_str)s") % log_info)

        def _declare_consumer():
            consumer = consumer_cls(self.channel, topic, callback,
                    self.consumer_num.next())
            self.consumers.append(consumer)
            return consumer

        return self.ensure(_connect_error, _declare_consumer)

    def iterconsume(self, limit=None):
        """Return an iterator that will consume from all queues/consumers"""

        info = {'do_consume': True}

        def _error_callback(exc):
            LOG.exception(_('Failed to consume message from queue: %s') %
                    str(exc))
            info['do_consume'] = True

        def _consume():
            if info['do_consume']:
                queues_head = self.consumers[:-1]
                queues_tail = self.consumers[-1]
                for queue in queues_head:
                    queue.consume(nowait=True)
                queues_tail.consume(nowait=False)
                info['do_consume'] = False
            return self.connection.drain_events()

        for iteration in itertools.count(0):
            if limit and iteration >= limit:
                raise StopIteration
            yield self.ensure(_error_callback, _consume)

    def cancel_consumer_thread(self):
        """Cancel a consumer thread"""
        if self.consumer_thread is not None:
            self.consumer_thread.kill()
            try:
                self.consumer_thread.wait()
            except greenlet.GreenletExit:
                pass
            self.consumer_thread = None

    def publisher_send(self, cls, topic, msg, **kwargs):
        """Send to a publisher based on the publisher class"""

        def _error_callback(exc):
            log_info = {'topic': topic, 'err_str': str(exc)}
            LOG.exception(_("Failed to publish message to topic "
                "'%(topic)s': %(err_str)s") % log_info)

        def _publish():
            publisher = cls(self.channel, topic, **kwargs)
            publisher.send(msg)

        self.ensure(_error_callback, _publish)

    def declare_direct_consumer(self, topic, callback):
        """Create a 'direct' queue.
        In nova's use, this is generally a msg_id queue used for
        responses for call/multicall
        """
        self.declare_consumer(DirectConsumer, topic, callback)

    def declare_topic_consumer(self, topic, callback=None):
        """Create a 'topic' consumer."""
        self.declare_consumer(TopicConsumer, topic, callback)

    def declare_fanout_consumer(self, topic, callback):
        """Create a 'fanout' consumer"""
        self.declare_consumer(FanoutConsumer, topic, callback)

    def direct_send(self, msg_id, msg):
        """Send a 'direct' message"""
        self.publisher_send(DirectPublisher, msg_id, msg)

    def topic_send(self, topic, msg):
        """Send a 'topic' message"""
        self.publisher_send(TopicPublisher, topic, msg)

    def fanout_send(self, topic, msg):
        """Send a 'fanout' message"""
        self.publisher_send(FanoutPublisher, topic, msg)

    def notify_send(self, topic, msg, **kwargs):
        """Send a notify message on a topic"""
        self.publisher_send(NotifyPublisher, topic, msg, **kwargs)

    def consume(self, limit=None):
        """Consume from all queues/consumers"""
        it = self.iterconsume(limit=limit)
        while True:
            try:
                it.next()
            except StopIteration:
                return

    def consume_in_thread(self):
        """Consumer from all queues/consumers in a greenthread"""
        def _consumer_thread():
            try:
                self.consume()
            except greenlet.GreenletExit:
                return
        if self.consumer_thread is None:
            self.consumer_thread = eventlet.spawn(_consumer_thread)
        return self.consumer_thread

    def create_consumer(self, topic, proxy, fanout=False):
        """Create a consumer that calls a method in a proxy object"""
        if fanout:
            self.declare_fanout_consumer(topic, ProxyCallback(proxy))
        else:
            self.declare_topic_consumer(topic, ProxyCallback(proxy))


class Pool(pools.Pool):
    """Class that implements a Pool of Connections."""

    # TODO(comstud): Timeout connections not used in a while
    def create(self):
        LOG.debug('Pool creating new connection')
        return Connection()

# Create a ConnectionPool to use for RPC calls.  We'll order the
# pool as a stack (LIFO), so that we can potentially loop through and
# timeout old unused connections at some point
ConnectionPool = Pool(
        max_size=FLAGS.rpc_conn_pool_size,
        order_as_stack=True)


class ConnectionContext(rpc_common.Connection):
    """The class that is actually returned to the caller of
    create_connection().  This is a essentially a wrapper around
    Connection that supports 'with' and can return a new Connection or
    one from a pool.  It will also catch when an instance of this class
    is to be deleted so that we can return Connections to the pool on
    exceptions and so forth without making the caller be responsible for
    catching all exceptions and making sure to return a connection to
    the pool.
    """

    def __init__(self, pooled=True):
        """Create a new connection, or get one from the pool"""
        self.connection = None
        if pooled:
            self.connection = ConnectionPool.get()
        else:
            self.connection = Connection()
        self.pooled = pooled

    def __enter__(self):
        """with ConnectionContext() should return self"""
        return self

    def _done(self):
        """If the connection came from a pool, clean it up and put it back.
        If it did not come from a pool, close it.
        """
        if self.connection:
            if self.pooled:
                # Reset the connection so it's ready for the next caller
                # to grab from the pool
                self.connection.reset()
                ConnectionPool.put(self.connection)
            else:
                try:
                    self.connection.close()
                except Exception:
                    # There's apparently a bug in kombu 'memory' transport
                    # which causes an assert failure.
                    # But, we probably want to ignore all exceptions when
                    # trying to close a connection, anyway...
                    pass
            self.connection = None

    def __exit__(self, t, v, tb):
        """end of 'with' statement.  We're done here."""
        self._done()

    def __del__(self):
        """Caller is done with this connection.  Make sure we cleaned up."""
        self._done()

    def close(self):
        """Caller is done with this connection."""
        self._done()

    def create_consumer(self, topic, proxy, fanout=False):
        self.connection.create_consumer(topic, proxy, fanout)

    def consume_in_thread(self):
        self.connection.consume_in_thread()

    def __getattr__(self, key):
        """Proxy all other calls to the Connection instance"""
        if self.connection:
            return getattr(self.connection, key)
        else:
            raise exception.InvalidRPCConnectionReuse()


class ProxyCallback(object):
    """Calls methods on a proxy object based on method and args."""

    def __init__(self, proxy):
        self.proxy = proxy
        self.pool = greenpool.GreenPool(FLAGS.rpc_thread_pool_size)

    def __call__(self, message_data):
        """Consumer callback to call a method on a proxy object.

        Parses the message for validity and fires off a thread to call the
        proxy object method.

        Message data should be a dictionary with two keys:
            method: string representing the method to call
            args: dictionary of arg: value

        Example: {'method': 'echo', 'args': {'value': 42}}

        """
        # It is important to clear the context here, because at this point
        # the previous context is stored in local.store.context
        if hasattr(local.store, 'context'):
            del local.store.context
        LOG.debug(_('received %s') % message_data)
        ctxt = _unpack_context(message_data)
        method = message_data.get('method')
        args = message_data.get('args', {})
        if not method:
            LOG.warn(_('no method for message: %s') % message_data)
            ctxt.reply(_('No method for message: %s') % message_data)
            return
        self.pool.spawn_n(self._process_data, ctxt, method, args)

    @exception.wrap_exception()
    def _process_data(self, ctxt, method, args):
        """Thread that magically looks for a method on the proxy
        object and calls it.
        """

        try:
            node_func = getattr(self.proxy, str(method))
            node_args = dict((str(k), v) for k, v in args.iteritems())
            # NOTE(vish): magic is fun!
            rval = node_func(context=ctxt, **node_args)
            # Check if the result was a generator
            if inspect.isgenerator(rval):
                for x in rval:
                    ctxt.reply(x, None)
            else:
                ctxt.reply(rval, None)
            # This final None tells multicall that it is done.
            ctxt.reply(ending=True)
        except Exception as e:
            LOG.exception('Exception during message handling')
            ctxt.reply(None, sys.exc_info())
        return


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
    ctx = RpcContext.from_dict(context_dict)
    LOG.debug(_('unpacked context: %s'), ctx.to_dict())
    return ctx


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
    """Context that supports replying to a rpc.call"""
    def __init__(self, *args, **kwargs):
        msg_id = kwargs.pop('msg_id', None)
        self.msg_id = msg_id
        super(RpcContext, self).__init__(*args, **kwargs)

    def reply(self, reply=None, failure=None, ending=False):
        if self.msg_id:
            msg_reply(self.msg_id, reply, failure, ending)
            if ending:
                self.msg_id = None


class MulticallWaiter(object):
    def __init__(self, connection):
        self._connection = connection
        self._iterator = connection.iterconsume()
        self._result = None
        self._done = False
        self._got_ending = False

    def done(self):
        if self._done:
            return
        self._done = True
        self._iterator.close()
        self._iterator = None
        self._connection.close()

    def __call__(self, data):
        """The consume() callback will call this.  Store the result."""
        if data['failure']:
            self._result = rpc_common.RemoteError(*data['failure'])
        elif data.get('ending', False):
            self._got_ending = True
        else:
            self._result = data['result']

    def __iter__(self):
        """Return a result until we get a 'None' response from consumer"""
        if self._done:
            raise StopIteration
        while True:
            self._iterator.next()
            if self._got_ending:
                self.done()
                raise StopIteration
            result = self._result
            if isinstance(result, Exception):
                self.done()
                raise result
            yield result


def create_connection(new=True):
    """Create a connection"""
    return ConnectionContext(pooled=not new)


def multicall(context, topic, msg):
    """Make a call that returns multiple times."""
    # Can't use 'with' for multicall, as it returns an iterator
    # that will continue to use the connection.  When it's done,
    # connection.close() will get called which will put it back into
    # the pool
    LOG.debug(_('Making asynchronous call on %s ...'), topic)
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug(_('MSG_ID is %s') % (msg_id))
    _pack_context(msg, context)

    conn = ConnectionContext()
    wait_msg = MulticallWaiter(conn)
    conn.declare_direct_consumer(msg_id, wait_msg)
    conn.topic_send(topic, msg)
    return wait_msg


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
    with ConnectionContext() as conn:
        conn.topic_send(topic, msg)


def fanout_cast(context, topic, msg):
    """Sends a message on a fanout exchange without waiting for a response."""
    LOG.debug(_('Making asynchronous fanout cast...'))
    _pack_context(msg, context)
    with ConnectionContext() as conn:
        conn.fanout_send(topic, msg)


def notify(context, topic, msg):
    """Sends a notification event on a topic."""
    LOG.debug(_('Sending notification on %s...'), topic)
    _pack_context(msg, context)
    with ConnectionContext() as conn:
        conn.notify_send(topic, msg, durable=True)


def msg_reply(msg_id, reply=None, failure=None, ending=False):
    """Sends a reply or an error on the channel signified by msg_id.

    Failure should be a sys.exc_info() tuple.

    """
    with ConnectionContext() as conn:
        if failure:
            message = str(failure[1])
            tb = traceback.format_exception(*failure)
            LOG.error(_("Returning exception %s to caller"), message)
            LOG.error(tb)
            failure = (failure[0].__name__, str(failure[1]), tb)

        try:
            msg = {'result': reply, 'failure': failure}
        except TypeError:
            msg = {'result': dict((k, repr(v))
                            for k, v in reply.__dict__.iteritems()),
                    'failure': failure}
        if ending:
            msg['ending'] = True
        conn.direct_send(msg_id, msg)

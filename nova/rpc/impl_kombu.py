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

from nova import flags
from nova import log as logging

import kombu
import kombu.entity
import kombu.messaging
import kombu.connection
import itertools
import sys
import time
import uuid


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.rpc')


class QueueBase(object):
    """Queue base class."""

    def __init__(self, channel, callback, tag, **kwargs):
        """Init the queue.

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
        """Re-create the queue after a rabbit reconnect"""
        self.channel = channel
        self.kwargs['channel'] = channel
        self.queue = kombu.entity.Queue(**self.kwargs)
        self.queue.declare()

    def consume(self, *args, **kwargs):
        """Consume from this queue.
        If a callback is specified in kwargs, use that.  Otherwise,
        use the callback passed during __init__()

        The callback will be called if a message was read off of the
        queue.

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


class DirectQueue(QueueBase):
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
        super(DirectQueue, self).__init__(
                channel,
                callback,
                tag,
                name=msg_id,
                exchange=exchange,
                routing_key=msg_id,
                **options)


class TopicQueue(QueueBase):
    """Queue/consumer class for 'topic'"""

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
        super(TopicQueue, self).__init__(
                channel,
                callback,
                tag,
                name=topic,
                exchange=exchange,
                routing_key=topic,
                **options)


class FanoutQueue(QueueBase):
    """Queue/consumer class for 'fanout'"""

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
        super(FanoutQueue, self).__init__(
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


class Connection(object):
    """Connection instance object."""

    def __init__(self):
        self.queues = []
        self.max_retries = FLAGS.rabbit_max_retries
        self.interval_start = FLAGS.rabbit_retry_interval
        self.interval_stepping = 0
        self.interval_max = FLAGS.rabbit_retry_interval

        self.params = dict(hostname=FLAGS.rabbit_host,
                          port=FLAGS.rabbit_port,
                          userid=FLAGS.rabbit_userid,
                          password=FLAGS.rabbit_password,
                          virtual_host=FLAGS.rabbit_virtual_host)
        if FLAGS.fake_rabbit:
            self.params['transport'] = 'memory'
        self.connection = None
        self.reconnect()

    def reconnect(self):
        """Handles reconnecting and re-estblishing queues"""
        if self.connection:
            try:
                self.connection.close()
            except self.connection.connection_errors:
                pass
            time.sleep(1)
        self.connection = kombu.connection.Connection(**self.params)
        self.queue_num = itertools.count(1)

        try:
            self.connection.ensure_connection(errback=self.connect_error,
                    max_retries=self.max_retries,
                    interval_start=self.interval_start,
                    interval_step=self.interval_stepping,
                    interval_max=self.interval_max)
        except self.connection.connection_errors, e:
            err_str = str(e)
            max_retries = FLAGS.rabbit_max_retries
            LOG.error(_('Unable to connect to AMQP server '
                    'after %(max_retries)d tries: %(err_str)s') % locals())
            # NOTE(comstud): Original carrot code exits after so many
            # attempts, but I wonder if we should re-try indefinitely
            sys.exit(1)
        LOG.info(_('Connected to AMQP server on %(hostname)s:%(port)d' %
                self.params))
        self.channel = self.connection.channel()
        for consumer in self.queues:
            consumer.reconnect(self.channel)
        if self.queues:
            LOG.debug(_("Re-established AMQP queues"))

    def get_channel(self):
        """Convenience call for bin/clear_rabbit_queues"""
        return self.channel

    def connect_error(self, exc, interval):
        """Callback when there are connection re-tries by kombu"""
        info = self.params.copy()
        info['intv'] = interval
        info['e'] = exc
        LOG.error(_('AMQP server on %(hostname)s:%(port)d is'
                ' unreachable: %(e)s. Trying again in %(intv)d'
                ' seconds.') % info)

    def close(self):
        """Close/release this connection"""
        self.connection.release()
        self.connection = None

    def reset(self):
        """Reset a connection so it can be used again"""
        self.channel.close()
        self.channel = self.connection.channel()
        self.queues = []

    def create_queue(self, queue_cls, topic, callback):
        """Create a queue using the class that was passed in and
        add it to our list of queues used for consuming
        """
        self.queues.append(queue_cls(self.channel, topic, callback,
            self.queue_num.next()))

    def consume(self, limit=None):
        """Consume from all queues"""
        while True:
            try:
                queues_head = self.queues[:-1]
                queues_tail = self.queues[-1]
                for queue in queues_head:
                    queue.consume(nowait=True)
                queues_tail.consume(nowait=False)

                for iteration in itertools.count(0):
                    if limit and iteration >= limit:
                        raise StopIteration
                    yield self.connection.drain_events()
            except self.connection.connection_errors, e:
                LOG.exception(_('Failed to consume message from queue: '
                        '%s' % str(e)))
                self.reconnect()

    def publisher_send(self, cls, topic, msg):
        """Send to a publisher based on the publisher class"""
        while True:
            publisher = None
            try:
                publisher = cls(self.channel, topic)
                publisher.send(msg)
                return
            except self.connection.connection_errors, e:
                LOG.exception(_('Failed to publish message %s' % str(e)))
                try:
                    self.reconnect()
                    if publisher:
                        publisher.reconnect(self.channel)
                except self.connection.connection_errors, e:
                    pass

    def direct_consumer(self, topic, callback):
        """Create a 'direct' queue.
        In nova's use, this is generally a msg_id queue used for
        responses for call/multicall
        """
        self.create_queue(DirectQueue, topic, callback)

    def topic_consumer(self, topic, callback=None):
        """Create a 'topic' queue."""
        self.create_queue(TopicQueue, topic, callback)

    def fanout_consumer(self, topic, callback):
        """Create a 'fanout' queue"""
        self.create_queue(FanoutQueue, topic, callback)

    def direct_send(self, msg_id, msg):
        """Send a 'direct' message"""
        self.publisher_send(DirectPublisher, msg_id, msg)

    def topic_send(self, topic, msg):
        """Send a 'topic' message"""
        self.publisher_send(TopicPublisher, topic, msg)

    def fanout_send(self, topic, msg):
        """Send a 'fanout' message"""
        self.publisher_send(FanoutPublisher, topic, msg)

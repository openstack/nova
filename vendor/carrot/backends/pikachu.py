import asyncore
import weakref
import functools
import itertools

import pika

from carrot.backends.base import BaseMessage, BaseBackend

DEFAULT_PORT = 5672


class Message(BaseMessage):

    def __init__(self, backend, amqp_message, **kwargs):
        channel, method, header, body = amqp_message
        self._channel = channel
        self._method = method
        self._header = header
        self.backend = backend

        kwargs.update({"body": body,
                       "delivery_tag": method.delivery_tag,
                       "content_type": header.content_type,
                       "content_encoding": header.content_encoding,
                       "delivery_info": dict(
                            consumer_tag=method.consumer_tag,
                            routing_key=method.routing_key,
                            delivery_tag=method.delivery_tag,
                            exchange=method.exchange)})

        super(Message, self).__init__(backend, **kwargs)


class SyncBackend(BaseBackend):
    default_port = DEFAULT_PORT
    _connection_cls = pika.BlockingConnection

    Message = Message

    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.default_port = kwargs.get("default_port", self.default_port)
        self._channel_ref = None

    @property
    def _channel(self):
        return callable(self._channel_ref) and self._channel_ref()

    @property
    def channel(self):
        """If no channel exists, a new one is requested."""
        if not self._channel:
            self._channel_ref = weakref.ref(self.connection.get_channel())
        return self._channel

    def establish_connection(self):
        """Establish connection to the AMQP broker."""
        conninfo = self.connection
        if not conninfo.port:
            conninfo.port = self.default_port
        credentials = pika.PlainCredentials(conninfo.userid,
                                            conninfo.password)
        return self._connection_cls(pika.ConnectionParameters(
                                           conninfo.hostname,
                                           port=conninfo.port,
                                           virtual_host=conninfo.virtual_host,
                                           credentials=credentials))

    def close_connection(self, connection):
        """Close the AMQP broker connection."""
        connection.close()

    def queue_exists(self, queue):
        return False # FIXME

    def queue_delete(self, queue, if_unused=False, if_empty=False):
        """Delete queue by name."""
        return self.channel.queue_delete(queue=queue, if_unused=if_unused,
                                         if_empty=if_empty)

    def queue_purge(self, queue, **kwargs):
        """Discard all messages in the queue. This will delete the messages
        and results in an empty queue."""
        return self.channel.queue_purge(queue=queue)

    def queue_declare(self, queue, durable, exclusive, auto_delete,
            warn_if_exists=False):
        """Declare a named queue."""

        return self.channel.queue_declare(queue=queue,
                                          durable=durable,
                                          exclusive=exclusive,
                                          auto_delete=auto_delete)

    def exchange_declare(self, exchange, type, durable, auto_delete):
        """Declare an named exchange."""
        return self.channel.exchange_declare(exchange=exchange,
                                             type=type,
                                             durable=durable,
                                             auto_delete=auto_delete)

    def queue_bind(self, queue, exchange, routing_key, arguments=None):
        """Bind queue to an exchange using a routing key."""
        return self.channel.queue_bind(queue=queue,
                                       exchange=exchange,
                                       routing_key=routing_key,
                                       arguments=arguments)

    def message_to_python(self, raw_message):
        """Convert encoded message body back to a Python value."""
        return self.Message(backend=self, amqp_message=raw_message)

    def get(self, queue, no_ack=False):
        """Receive a message from a declared queue by name.

        :returns: A :class:`Message` object if a message was received,
            ``None`` otherwise. If ``None`` was returned, it probably means
            there was no messages waiting on the queue.

        """
        raw_message = self.channel.basic_get(queue, no_ack=no_ack)
        if not raw_message:
            return None
        return self.message_to_python(raw_message)

    def declare_consumer(self, queue, no_ack, callback, consumer_tag,
            nowait=False):
        """Declare a consumer."""

        @functools.wraps(callback)
        def _callback_decode(channel, method, header, body):
            return callback((channel, method, header, body))

        return self.channel.basic_consume(_callback_decode,
                                          queue=queue,
                                          no_ack=no_ack,
                                          consumer_tag=consumer_tag)

    def consume(self, limit=None):
        """Returns an iterator that waits for one message at a time."""
        for total_message_count in itertools.count():
            if limit and total_message_count >= limit:
                raise StopIteration
            self.connection.connection.drain_events()
            yield True

    def cancel(self, consumer_tag):
        """Cancel a channel by consumer tag."""
        if not self._channel:
            return
        self.channel.basic_cancel(consumer_tag)

    def close(self):
        """Close the channel if open."""
        if self._channel and not self._channel.handler.channel_close:
            self._channel.close()
        self._channel_ref = None

    def ack(self, delivery_tag):
        """Acknowledge a message by delivery tag."""
        return self.channel.basic_ack(delivery_tag)

    def reject(self, delivery_tag):
        """Reject a message by deliver tag."""
        return self.channel.basic_reject(delivery_tag, requeue=False)

    def requeue(self, delivery_tag):
        """Reject and requeue a message by delivery tag."""
        return self.channel.basic_reject(delivery_tag, requeue=True)

    def prepare_message(self, message_data, delivery_mode, priority=None,
            content_type=None, content_encoding=None):
        """Encapsulate data into a AMQP message."""
        properties = pika.BasicProperties(priority=priority,
                                          content_type=content_type,
                                          content_encoding=content_encoding,
                                          delivery_mode=delivery_mode)
        return message_data, properties

    def publish(self, message, exchange, routing_key, mandatory=None,
            immediate=None, headers=None):
        """Publish a message to a named exchange."""
        body, properties = message

        if headers:
            properties.headers = headers

        ret = self.channel.basic_publish(body=body,
                                         properties=properties,
                                         exchange=exchange,
                                         routing_key=routing_key,
                                         mandatory=mandatory,
                                         immediate=immediate)
        if mandatory or immediate:
            self.close()

    def qos(self, prefetch_size, prefetch_count, apply_global=False):
        """Request specific Quality of Service."""
        self.channel.basic_qos(prefetch_size, prefetch_count,
                                apply_global)

    def flow(self, active):
        """Enable/disable flow from peer."""
        self.channel.flow(active)


class AsyncoreBackend(SyncBackend):
    _connection_cls = pika.AsyncoreConnection

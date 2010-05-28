"""

Backend base classes.

"""
from carrot import serialization

ACKNOWLEDGED_STATES = frozenset(["ACK", "REJECTED", "REQUEUED"])


class MessageStateError(Exception):
    """The message has already been acknowledged."""


class BaseMessage(object):
    """Base class for received messages."""
    _state = None

    MessageStateError = MessageStateError

    def __init__(self, backend, **kwargs):
        self.backend = backend
        self.body = kwargs.get("body")
        self.delivery_tag = kwargs.get("delivery_tag")
        self.content_type = kwargs.get("content_type")
        self.content_encoding = kwargs.get("content_encoding")
        self.delivery_info = kwargs.get("delivery_info", {})
        self._decoded_cache = None
        self._state = "RECEIVED"

    def decode(self):
        """Deserialize the message body, returning the original
        python structure sent by the publisher."""
        return serialization.decode(self.body, self.content_type,
                                    self.content_encoding)

    @property
    def payload(self):
        """The decoded message."""
        if not self._decoded_cache:
            self._decoded_cache = self.decode()
        return self._decoded_cache

    def ack(self):
        """Acknowledge this message as being processed.,
        This will remove the message from the queue.

        :raises MessageStateError: If the message has already been
            acknowledged/requeued/rejected.

        """
        if self.acknowledged:
            raise self.MessageStateError(
                "Message already acknowledged with state: %s" % self._state)
        self.backend.ack(self.delivery_tag)
        self._state = "ACK"

    def reject(self):
        """Reject this message.

        The message will be discarded by the server.

        :raises MessageStateError: If the message has already been
            acknowledged/requeued/rejected.

        """
        if self.acknowledged:
            raise self.MessageStateError(
                "Message already acknowledged with state: %s" % self._state)
        self.backend.reject(self.delivery_tag)
        self._state = "REJECTED"

    def requeue(self):
        """Reject this message and put it back on the queue.

        You must not use this method as a means of selecting messages
        to process.

        :raises MessageStateError: If the message has already been
            acknowledged/requeued/rejected.

        """
        if self.acknowledged:
            raise self.MessageStateError(
                "Message already acknowledged with state: %s" % self._state)
        self.backend.requeue(self.delivery_tag)
        self._state = "REQUEUED"

    @property
    def acknowledged(self):
        return self._state in ACKNOWLEDGED_STATES


class BaseBackend(object):
    """Base class for backends."""
    default_port = None
    extra_options = None

    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.extra_options = kwargs.get("extra_options")

    def queue_declare(self, *args, **kwargs):
        """Declare a queue by name."""
        pass

    def queue_delete(self, *args, **kwargs):
        """Delete a queue by name."""
        pass

    def exchange_declare(self, *args, **kwargs):
        """Declare an exchange by name."""
        pass

    def queue_bind(self, *args, **kwargs):
        """Bind a queue to an exchange."""
        pass

    def get(self, *args, **kwargs):
        """Pop a message off the queue."""
        pass

    def declare_consumer(self, *args, **kwargs):
        pass

    def consume(self, *args, **kwargs):
        """Iterate over the declared consumers."""
        pass

    def cancel(self, *args, **kwargs):
        """Cancel the consumer."""
        pass

    def ack(self, delivery_tag):
        """Acknowledge the message."""
        pass

    def queue_purge(self, queue, **kwargs):
        """Discard all messages in the queue. This will delete the messages
        and results in an empty queue."""
        return 0

    def reject(self, delivery_tag):
        """Reject the message."""
        pass

    def requeue(self, delivery_tag):
        """Requeue the message."""
        pass

    def purge(self, queue, **kwargs):
        """Discard all messages in the queue."""
        pass

    def message_to_python(self, raw_message):
        """Convert received message body to a python datastructure."""
        return raw_message

    def prepare_message(self, message_data, delivery_mode, **kwargs):
        """Prepare message for sending."""
        return message_data

    def publish(self, message, exchange, routing_key, **kwargs):
        """Publish a message."""
        pass

    def close(self):
        """Close the backend."""
        pass

    def establish_connection(self):
        """Establish a connection to the backend."""
        pass

    def close_connection(self, connection):
        """Close the connection."""
        pass

    def flow(self, active):
        """Enable/disable flow from peer."""
        pass

    def qos(self, prefetch_size, prefetch_count, apply_global=False):
        """Request specific Quality of Service."""
        pass

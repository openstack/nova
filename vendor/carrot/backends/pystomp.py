from stompy import Client
from stompy import Empty as QueueEmpty
from carrot.backends.base import BaseMessage, BaseBackend
from itertools import count
import socket

DEFAULT_PORT = 61613


class Message(BaseMessage):
    """A message received by the STOMP broker.

    Usually you don't insantiate message objects yourself, but receive
    them using a :class:`carrot.messaging.Consumer`.

    :param backend: see :attr:`backend`.
    :param frame: see :attr:`_frame`.

    .. attribute:: body

        The message body.

    .. attribute:: delivery_tag

        The message delivery tag, uniquely identifying this message.

    .. attribute:: backend

        The message backend used.
        A subclass of :class:`carrot.backends.base.BaseBackend`.

    .. attribute:: _frame

        The frame received by the STOMP client. This is considered a private
        variable and should never be used in production code.

    """

    def __init__(self, backend, frame, **kwargs):
        self._frame = frame
        self.backend = backend

        kwargs["body"] = frame.body
        kwargs["delivery_tag"] = frame.headers["message-id"]
        kwargs["content_type"] = frame.headers.get("content-type")
        kwargs["content_encoding"] = frame.headers.get("content-encoding")
        kwargs["priority"] = frame.headers.get("priority")

        super(Message, self).__init__(backend, **kwargs)

    def ack(self):
        """Acknowledge this message as being processed.,
        This will remove the message from the queue.

        :raises MessageStateError: If the message has already been
            acknowledged/requeued/rejected.

        """
        if self.acknowledged:
            raise self.MessageStateError(
                "Message already acknowledged with state: %s" % self._state)
        self.backend.ack(self._frame)
        self._state = "ACK"

    def reject(self):
        raise NotImplementedError(
            "The STOMP backend does not implement basic.reject")

    def requeue(self):
        raise NotImplementedError(
            "The STOMP backend does not implement requeue")


class Backend(BaseBackend):
    Stomp = Client
    Message = Message
    default_port = DEFAULT_PORT

    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.default_port = kwargs.get("default_port", self.default_port)
        self._channel = None
        self._consumers = {} # open consumers by consumer tag
        self._callbacks = {}

    def establish_connection(self):
        conninfo = self.connection
        if not conninfo.port:
            conninfo.port = self.default_port
        stomp = self.Stomp(conninfo.hostname, conninfo.port)
        stomp.connect()
        return stomp

    def close_connection(self, connection):
        try:
            connection.disconnect()
        except socket.error:
            pass

    def queue_exists(self, queue):
        return True

    def queue_purge(self, queue, **kwargs):
        for purge_count in count(0):
            try:
                frame = self.channel.get_nowait()
            except QueueEmpty:
                return purge_count
            else:
                self.channel.ack(frame)

    def declare_consumer(self, queue, no_ack, callback, consumer_tag,
            **kwargs):
        ack = no_ack and "auto" or "client"
        self.channel.subscribe(queue, ack=ack)
        self._consumers[consumer_tag] = queue
        self._callbacks[queue] = callback

    def consume(self, limit=None):
        """Returns an iterator that waits for one message at a time."""
        for total_message_count in count():
            if limit and total_message_count >= limit:
                raise StopIteration
            while True:
                frame = self.channel.get()
                if frame:
                    break
            queue = frame.headers.get("destination")

            if not queue or queue not in self._callbacks:
                continue

            self._callbacks[queue](frame)

            yield True

    def queue_declare(self, queue, *args, **kwargs):
        self.channel.subscribe(queue, ack="client")

    def get(self, queue, no_ack=False):
        try:
            frame = self.channel.get_nowait()
        except QueueEmpty:
            return None
        else:
            return self.message_to_python(frame)

    def ack(self, frame):
        self.channel.ack(frame)

    def message_to_python(self, raw_message):
        """Convert encoded message body back to a Python value."""
        return self.Message(backend=self, frame=raw_message)

    def prepare_message(self, message_data, delivery_mode, priority=0,
            content_type=None, content_encoding=None):
        persistent = "false"
        if delivery_mode == 2:
            persistent = "true"
        priority = priority or 0
        return {"body": message_data,
                "persistent": persistent,
                "priority": priority,
                "content-encoding": content_encoding,
                "content-type": content_type}

    def publish(self, message, exchange, routing_key, **kwargs):
        message["destination"] = exchange
        self.channel.stomp.send(message)

    def cancel(self, consumer_tag):
        if not self._channel or consumer_tag not in self._consumers:
            return
        queue = self._consumers.pop(consumer_tag)
        self.channel.unsubscribe(queue)

    def close(self):
        for consumer_tag in self._consumers.keys():
            self.cancel(consumer_tag)
        if self._channel:
            try:
                self._channel.disconnect()
            except socket.error:
                pass

    @property
    def channel(self):
        if not self._channel:
            # Sorry, but the python-stomp library needs one connection
            # for each channel.
            self._channel = self.establish_connection()
        return self._channel

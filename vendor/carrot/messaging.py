"""

Sending/Receiving Messages.

"""
from itertools import count
from carrot.utils import gen_unique_id
import warnings

from carrot import serialization


class Consumer(object):
    """Message consumer.

    :param connection: see :attr:`connection`.
    :param queue: see :attr:`queue`.
    :param exchange: see :attr:`exchange`.
    :param routing_key: see :attr:`routing_key`.

    :keyword durable: see :attr:`durable`.
    :keyword auto_delete: see :attr:`auto_delete`.
    :keyword exclusive: see :attr:`exclusive`.
    :keyword exchange_type: see :attr:`exchange_type`.
    :keyword auto_ack: see :attr:`auto_ack`.
    :keyword no_ack: see :attr:`no_ack`.
    :keyword auto_declare: see :attr:`auto_declare`.


    .. attribute:: connection

        The connection to the broker.
        A :class:`carrot.connection.BrokerConnection` instance.

    .. attribute:: queue

       Name of the queue.

    .. attribute:: exchange

        Name of the exchange the queue binds to.

    .. attribute:: routing_key

        The routing key (if any). The interpretation of the routing key
        depends on the value of the :attr:`exchange_type` attribute:

            * direct exchange

                Matches if the routing key property of the message and
                the :attr:`routing_key` attribute are identical.

            * fanout exchange

                Always matches, even if the binding does not have a key.

            * topic exchange

                Matches the routing key property of the message by a primitive
                pattern matching scheme. The message routing key then consists
                of words separated by dots (``"."``, like domain names), and
                two special characters are available; star (``"*"``) and hash
                (``"#"``). The star matches any word, and the hash matches
                zero or more words. For example ``"*.stock.#"`` matches the
                routing keys ``"usd.stock"`` and ``"eur.stock.db"`` but not
                ``"stock.nasdaq"``.

    .. attribute:: durable

        Durable exchanges remain active when a server restarts. Non-durable
        exchanges (transient exchanges) are purged when a server restarts.
        Default is ``True``.

    .. attribute:: auto_delete

        If set, the exchange is deleted when all queues have finished
        using it. Default is ``False``.

    .. attribute:: exclusive

        Exclusive queues may only be consumed from by the current connection.
        When :attr:`exclusive` is on, this also implies :attr:`auto_delete`.
        Default is ``False``.

    .. attribute:: exchange_type

        AMQP defines four default exchange types (routing algorithms) that
        covers most of the common messaging use cases. An AMQP broker can
        also define additional exchange types, so see your message brokers
        manual for more information about available exchange types.

            * Direct

                Direct match between the routing key in the message, and the
                routing criteria used when a queue is bound to this exchange.

            * Topic

                Wildcard match between the routing key and the routing pattern
                specified in the binding. The routing key is treated as zero
                or more words delimited by ``"."`` and supports special
                wildcard characters. ``"*"`` matches a single word and ``"#"``
                matches zero or more words.

            * Fanout

                Queues are bound to this exchange with no arguments. Hence any
                message sent to this exchange will be forwarded to all queues
                bound to this exchange.

            * Headers

                Queues are bound to this exchange with a table of arguments
                containing headers and values (optional). A special argument
                named "x-match" determines the matching algorithm, where
                ``"all"`` implies an ``AND`` (all pairs must match) and
                ``"any"`` implies ``OR`` (at least one pair must match).

                Use the :attr:`routing_key`` is used to specify the arguments,
                the same when sending messages.

            This description of AMQP exchange types was shamelessly stolen
            from the blog post `AMQP in 10 minutes: Part 4`_ by
            Rajith Attapattu. Recommended reading.

            .. _`AMQP in 10 minutes: Part 4`:
                http://bit.ly/amqp-exchange-types

    .. attribute:: callbacks

        List of registered callbacks to trigger when a message is received
        by :meth:`wait`, :meth:`process_next` or :meth:`iterqueue`.

    .. attribute:: warn_if_exists

        Emit a warning if the queue has already been declared. If a queue
        already exists, and you try to redeclare the queue with new settings,
        the new settings will be silently ignored, so this can be
        useful if you've recently changed the :attr:`routing_key` attribute
        or other settings.

    .. attribute:: auto_ack

        Acknowledgement is handled automatically once messages are received.
        This means that the :meth:`carrot.backends.base.BaseMessage.ack` and
        :meth:`carrot.backends.base.BaseMessage.reject` methods
        on the message object are no longer valid.
        By default :attr:`auto_ack` is set to ``False``, and the receiver is
        required to manually handle acknowledgment.

    .. attribute:: no_ack

        Disable acknowledgement on the server-side. This is different from
        :attr:`auto_ack` in that acknowledgement is turned off altogether.
        This functionality increases performance but at the cost of
        reliability. Messages can get lost if a client dies before it can
        deliver them to the application.

    .. attribute auto_declare

        If this is ``True`` the following will be automatically declared:

            * The queue if :attr:`queue` is set.
            * The exchange if :attr:`exchange` is set.
            * The :attr:`queue` will be bound to the :attr:`exchange`.

        This is the default behaviour.


    :raises `amqplib.client_0_8.channel.AMQPChannelException`: if the queue is
        exclusive and the queue already exists and is owned by another
        connection.


    Example Usage

        >>> consumer = Consumer(connection=DjangoBrokerConnection(),
        ...               queue="foo", exchange="foo", routing_key="foo")
        >>> def process_message(message_data, message):
        ...     print("Got message %s: %s" % (
        ...             message.delivery_tag, message_data))
        >>> consumer.register_callback(process_message)
        >>> consumer.wait() # Go into receive loop

    """
    queue = ""
    exchange = ""
    routing_key = ""
    durable = True
    exclusive = False
    auto_delete = False
    exchange_type = "direct"
    channel_open = False
    warn_if_exists = False
    auto_declare = True
    auto_ack = False
    no_ack = False
    _closed = True

    def __init__(self, connection, queue=None, exchange=None,
            routing_key=None, **kwargs):
        self.connection = connection
        self.backend = kwargs.get("backend", None)
        if not self.backend:
            self.backend = self.connection.create_backend()
        self.queue = queue or self.queue

        # Binding.
        self.queue = queue or self.queue
        self.exchange = exchange or self.exchange
        self.routing_key = routing_key or self.routing_key
        self.callbacks = []

        # Options
        self.durable = kwargs.get("durable", self.durable)
        self.exclusive = kwargs.get("exclusive", self.exclusive)
        self.auto_delete = kwargs.get("auto_delete", self.auto_delete)
        self.exchange_type = kwargs.get("exchange_type", self.exchange_type)
        self.warn_if_exists = kwargs.get("warn_if_exists",
                                         self.warn_if_exists)
        self.auto_ack = kwargs.get("auto_ack", self.auto_ack)
        self.auto_declare = kwargs.get("auto_declare", self.auto_declare)

        # exclusive implies auto-delete.
        if self.exclusive:
            self.auto_delete = True

        self.consumer_tag = self._generate_consumer_tag()

        if self.auto_declare:
            self.declare()

    def __enter__(self):
        return self

    def __exit__(self, e_type, e_value, e_trace):
        if e_type:
            raise e_type(e_value)
        self.close()

    def __iter__(self):
        """iter(Consumer) -> Consumer.iterqueue(infinite=True)"""
        return self.iterqueue(infinite=True)

    def _generate_consumer_tag(self):
        """Generate a unique consumer tag.

        :rtype string:

        """
        return "%s.%s-%s" % (
                self.__class__.__module__,
                self.__class__.__name__,
                gen_unique_id())

    def declare(self):
        """Declares the queue, the exchange and binds the queue to
        the exchange."""
        arguments = None
        routing_key = self.routing_key
        if self.exchange_type == "headers":
            arguments, routing_key = routing_key, ""

        if self.queue:
            self.backend.queue_declare(queue=self.queue, durable=self.durable,
                                       exclusive=self.exclusive,
                                       auto_delete=self.auto_delete,
                                       warn_if_exists=self.warn_if_exists)
        if self.exchange:
            self.backend.exchange_declare(exchange=self.exchange,
                                          type=self.exchange_type,
                                          durable=self.durable,
                                          auto_delete=self.auto_delete)
        if self.queue:
            self.backend.queue_bind(queue=self.queue,
                                    exchange=self.exchange,
                                    routing_key=routing_key,
                                    arguments=arguments)
        self._closed = False
        return self

    def _receive_callback(self, raw_message):
        """Internal method used when a message is received in consume mode."""
        message = self.backend.message_to_python(raw_message)

        if self.auto_ack and not message.acknowledged:
            message.ack()
        self.receive(message.payload, message)

    def fetch(self, no_ack=None, auto_ack=None, enable_callbacks=False):
        """Receive the next message waiting on the queue.

        :returns: A :class:`carrot.backends.base.BaseMessage` instance,
            or ``None`` if there's no messages to be received.

        :keyword enable_callbacks: Enable callbacks. The message will be
            processed with all registered callbacks. Default is disabled.
        :keyword auto_ack: Override the default :attr:`auto_ack` setting.
        :keyword no_ack: Override the default :attr:`no_ack` setting.

        """
        no_ack = no_ack or self.no_ack
        auto_ack = auto_ack or self.auto_ack
        message = self.backend.get(self.queue, no_ack=no_ack)
        if message:
            if auto_ack and not message.acknowledged:
                message.ack()
            if enable_callbacks:
                self.receive(message.payload, message)
        return message

    def process_next(self):
        """**DEPRECATED** Use :meth:`fetch` like this instead:

            >>> message = self.fetch(enable_callbacks=True)

        """
        warnings.warn(DeprecationWarning(
            "Consumer.process_next has been deprecated in favor of \
            Consumer.fetch(enable_callbacks=True)"))
        return self.fetch(enable_callbacks=True)

    def receive(self, message_data, message):
        """This method is called when a new message is received by
        running :meth:`wait`, :meth:`process_next` or :meth:`iterqueue`.

        When a message is received, it passes the message on to the
        callbacks listed in the :attr:`callbacks` attribute.
        You can register callbacks using :meth:`register_callback`.

        :param message_data: The deserialized message data.

        :param message: The :class:`carrot.backends.base.BaseMessage` instance.

        :raises NotImplementedError: If no callbacks has been registered.

        """
        if not self.callbacks:
            raise NotImplementedError("No consumer callbacks registered")
        for callback in self.callbacks:
            callback(message_data, message)

    def register_callback(self, callback):
        """Register a callback function to be triggered by :meth:`receive`.

        The ``callback`` function must take two arguments:

            * message_data

                The deserialized message data

            * message

                The :class:`carrot.backends.base.BaseMessage` instance.
        """
        self.callbacks.append(callback)

    def discard_all(self, filterfunc=None):
        """Discard all waiting messages.

        :param filterfunc: A filter function to only discard the messages this
            filter returns.

        :returns: the number of messages discarded.

        *WARNING*: All incoming messages will be ignored and not processed.

        Example using filter:

            >>> def waiting_feeds_only(message):
            ...     try:
            ...         message_data = message.decode()
            ...     except: # Should probably be more specific.
            ...         pass
            ...
            ...     if message_data.get("type") == "feed":
            ...         return True
            ...     else:
            ...         return False
        """
        if not filterfunc:
            return self.backend.queue_purge(self.queue)

        if self.no_ack or self.auto_ack:
            raise Exception("discard_all: Can't use filter with auto/no-ack.")

        discarded_count = 0
        while True:
            message = self.fetch()
            if message is None:
                return discarded_count

            if filterfunc(message):
                message.ack()
                discarded_count += 1

    def iterconsume(self, limit=None, no_ack=None):
        """Iterator processing new messages as they arrive.
        Every new message will be passed to the callbacks, and the iterator
        returns ``True``. The iterator is infinite unless the ``limit``
        argument is specified or someone closes the consumer.

        :meth:`iterconsume` uses transient requests for messages on the
        server, while :meth:`iterequeue` uses synchronous access. In most
        cases you want :meth:`iterconsume`, but if your environment does not
        support this behaviour you can resort to using :meth:`iterqueue`
        instead.

        Also, :meth:`iterconsume` does not return the message
        at each step, something which :meth:`iterqueue` does.

        :keyword limit: Maximum number of messages to process.

        :raises StopIteration: if limit is set and the message limit has been
            reached.

        """
        no_ack = no_ack or self.no_ack
        self.backend.declare_consumer(queue=self.queue, no_ack=no_ack,
                                      callback=self._receive_callback,
                                      consumer_tag=self.consumer_tag,
                                      nowait=True)
        self.channel_open = True
        return self.backend.consume(limit=limit)

    def wait(self, limit=None):
        """Go into consume mode.

        Mostly for testing purposes and simple programs, you probably
        want :meth:`iterconsume` or :meth:`iterqueue` instead.

        This runs an infinite loop, processing all incoming messages
        using :meth:`receive` to apply the message to all registered
        callbacks.

        """
        it = self.iterconsume(limit)
        while True:
            it.next()

    def iterqueue(self, limit=None, infinite=False):
        """Infinite iterator yielding pending messages, by using
        synchronous direct access to the queue (``basic_get``).

        :meth:`iterqueue` is used where synchronous functionality is more
        important than performance. If you can, use :meth:`iterconsume`
        instead.

        :keyword limit: If set, the iterator stops when it has processed
            this number of messages in total.

        :keyword infinite: Don't raise :exc:`StopIteration` if there is no
            messages waiting, but return ``None`` instead. If infinite you
            obviously shouldn't consume the whole iterator at once without
            using a ``limit``.

        :raises StopIteration: If there is no messages waiting, and the
            iterator is not infinite.

        """
        for items_since_start in count():
            item = self.fetch()
            if (not infinite and item is None) or \
                    (limit and items_since_start >= limit):
                raise StopIteration
            yield item

    def cancel(self):
        """Cancel a running :meth:`iterconsume` session."""
        if self.channel_open:
            try:
                self.backend.cancel(self.consumer_tag)
            except KeyError:
                pass

    def close(self):
        """Close the channel to the queue."""
        self.cancel()
        self.backend.close()
        self._closed = True

    def flow(self, active):
        """This method asks the peer to pause or restart the flow of
        content data.

        This is a simple flow-control mechanism that a
        peer can use to avoid oveflowing its queues or otherwise
        finding itself receiving more messages than it can process.
        Note that this method is not intended for window control.  The
        peer that receives a request to stop sending content should
        finish sending the current content, if any, and then wait
        until it receives the ``flow(active=True)`` restart method.

        """
        self.backend.flow(active)

    def qos(self, prefetch_size=0, prefetch_count=0, apply_global=False):
        """Request specific Quality of Service.

        This method requests a specific quality of service.  The QoS
        can be specified for the current channel or for all channels
        on the connection.  The particular properties and semantics of
        a qos method always depend on the content class semantics.
        Though the qos method could in principle apply to both peers,
        it is currently meaningful only for the server.

        :param prefetch_size: Prefetch window in octets.
            The client can request that messages be sent in
            advance so that when the client finishes processing a
            message, the following message is already held
            locally, rather than needing to be sent down the
            channel.  Prefetching gives a performance improvement.
            This field specifies the prefetch window size in
            octets.  The server will send a message in advance if
            it is equal to or smaller in size than the available
            prefetch size (and also falls into other prefetch
            limits). May be set to zero, meaning "no specific
            limit", although other prefetch limits may still
            apply. The ``prefetch_size`` is ignored if the
            :attr:`no_ack` option is set.

        :param prefetch_count: Specifies a prefetch window in terms of whole
            messages. This field may be used in combination with
            ``prefetch_size``; A message will only be sent
            in advance if both prefetch windows (and those at the
            channel and connection level) allow it. The prefetch-
            count is ignored if the :attr:`no_ack` option is set.

        :keyword apply_global: By default the QoS settings apply to the
            current channel only. If this is set, they are applied
            to the entire connection.

        """
        return self.backend.qos(prefetch_size, prefetch_count, apply_global)


class Publisher(object):
    """Message publisher.

    :param connection: see :attr:`connection`.
    :param exchange: see :attr:`exchange`.
    :param routing_key: see :attr:`routing_key`.

    :keyword exchange_type: see :attr:`Consumer.exchange_type`.
    :keyword durable: see :attr:`Consumer.durable`.
    :keyword auto_delete: see :attr:`Consumer.auto_delete`.
    :keyword serializer: see :attr:`serializer`.
    :keyword auto_declare: See :attr:`auto_declare`.


    .. attribute:: connection

        The connection to the broker.
        A :class:`carrot.connection.BrokerConnection` instance.

    .. attribute:: exchange

        Name of the exchange we send messages to.

    .. attribute:: routing_key

        The default routing key for messages sent using this publisher.
        See :attr:`Consumer.routing_key` for more information.
        You can override the routing key by passing an explicit
        ``routing_key`` argument to :meth:`send`.

    .. attribute:: delivery_mode

        The default delivery mode used for messages. The value is an integer.
        The following delivery modes are supported by (at least) RabbitMQ:

            * 1 or "non-persistent"

                The message is non-persistent. Which means it is stored in
                memory only, and is lost if the server dies or restarts.

            * 2 or "persistent"
                The message is persistent. Which means the message is
                stored both in-memory, and on disk, and therefore
                preserved if the server dies or restarts.

        The default value is ``2`` (persistent).

    .. attribute:: exchange_type

        See :attr:`Consumer.exchange_type`.

    .. attribute:: durable

        See :attr:`Consumer.durable`.

    .. attribute:: auto_delete

        See :attr:`Consumer.auto_delete`.

    .. attribute:: auto_declare

        If this is ``True`` and the :attr:`exchange` name is set, the exchange
        will be automatically declared at instantiation.
        You can manually the declare the exchange by using the :meth:`declare`
        method.

        Auto declare is on by default.

    .. attribute:: serializer

        A string identifying the default serialization method to use.
        Defaults to ``json``. Can be ``json`` (default), ``raw``,
        ``pickle``, ``hessian``, ``yaml``, or any custom serialization
        methods that have been registered with
        :mod:`carrot.serialization.registry`.

    """

    NONE_PERSISTENT_DELIVERY_MODE = 1
    PERSISTENT_DELIVERY_MODE = 2
    DELIVERY_MODES = {
            "non-persistent": NONE_PERSISTENT_DELIVERY_MODE,
            "persistent": PERSISTENT_DELIVERY_MODE,
    }

    exchange = ""
    routing_key = ""
    delivery_mode = PERSISTENT_DELIVERY_MODE
    _closed = True
    exchange_type = "direct"
    durable = True
    auto_delete = False
    auto_declare = True
    serializer = None

    def __init__(self, connection, exchange=None, routing_key=None, **kwargs):
        self.connection = connection
        self.backend = self.connection.create_backend()
        self.exchange = exchange or self.exchange
        self.routing_key = routing_key or self.routing_key
        self.delivery_mode = kwargs.get("delivery_mode", self.delivery_mode)
        self.delivery_mode = self.DELIVERY_MODES.get(self.delivery_mode,
                                                     self.delivery_mode)
        self.exchange_type = kwargs.get("exchange_type", self.exchange_type)
        self.durable = kwargs.get("durable", self.durable)
        self.auto_delete = kwargs.get("auto_delete", self.auto_delete)
        self.serializer = kwargs.get("serializer", self.serializer)
        self.auto_declare = kwargs.get("auto_declare", self.auto_declare)
        self._closed = False

        if self.auto_declare and self.exchange:
            self.declare()

    def declare(self):
        """Declare the exchange.

        Creates the exchange on the broker.

        """
        self.backend.exchange_declare(exchange=self.exchange,
                                        type=self.exchange_type,
                                          durable=self.durable,
                                          auto_delete=self.auto_delete)

    def __enter__(self):
        return self

    def __exit__(self, e_type, e_value, e_trace):
        if e_type:
            raise e_type(e_value)
        self.close()

    def create_message(self, message_data, delivery_mode=None, priority=None,
                       content_type=None, content_encoding=None,
                       serializer=None):
        """With any data, serialize it and encapsulate it in a AMQP
        message with the proper headers set."""

        delivery_mode = delivery_mode or self.delivery_mode

        # No content_type? Then we're serializing the data internally.
        if not content_type:
            serializer = serializer or self.serializer
            (content_type, content_encoding,
             message_data) = serialization.encode(message_data,
                                                  serializer=serializer)
        else:
            # If the programmer doesn't want us to serialize,
            # make sure content_encoding is set.
            if isinstance(message_data, unicode):
                if not content_encoding:
                    content_encoding = 'utf-8'
                message_data = message_data.encode(content_encoding)

            # If they passed in a string, we can't know anything
            # about it.  So assume it's binary data.
            elif not content_encoding:
                content_encoding = 'binary'

        return self.backend.prepare_message(message_data, delivery_mode,
                                            priority=priority,
                                            content_type=content_type,
                                            content_encoding=content_encoding)

    def send(self, message_data, routing_key=None, delivery_mode=None,
            mandatory=False, immediate=False, priority=0, content_type=None,
            content_encoding=None, serializer=None):
        """Send a message.

        :param message_data: The message data to send. Can be a list,
            dictionary or a string.

        :keyword routing_key: A custom routing key for the message.
            If not set, the default routing key set in the :attr:`routing_key`
            attribute is used.

        :keyword mandatory: If set, the message has mandatory routing.
            By default the message is silently dropped by the server if it
            can't be routed to a queue. However - If the message is mandatory,
            an exception will be raised instead.

        :keyword immediate: Request immediate delivery.
            If the message cannot be routed to a queue consumer immediately,
            an exception will be raised. This is instead of the default
            behaviour, where the server will accept and queue the message,
            but with no guarantee that the message will ever be consumed.

        :keyword delivery_mode: Override the default :attr:`delivery_mode`.

        :keyword priority: The message priority, ``0`` to ``9``.

        :keyword content_type: The messages content_type. If content_type
            is set, no serialization occurs as it is assumed this is either
            a binary object, or you've done your own serialization.
            Leave blank if using built-in serialization as our library
            properly sets content_type.

        :keyword content_encoding: The character set in which this object
            is encoded. Use "binary" if sending in raw binary objects.
            Leave blank if using built-in serialization as our library
            properly sets content_encoding.

        :keyword serializer: Override the default :attr:`serializer`.

        """
        headers = None
        routing_key = routing_key or self.routing_key

        if self.exchange_type == "headers":
            headers, routing_key = routing_key, ""


        message = self.create_message(message_data, priority=priority,
                                      delivery_mode=delivery_mode,
                                      content_type=content_type,
                                      content_encoding=content_encoding,
                                      serializer=serializer)
        self.backend.publish(message,
                             exchange=self.exchange, routing_key=routing_key,
                             mandatory=mandatory, immediate=immediate,
                             headers=headers)

    def close(self):
        """Close connection to queue."""
        self.backend.close()
        self._closed = True


class Messaging(object):
    """A combined message publisher and consumer."""
    queue = ""
    exchange = ""
    routing_key = ""
    publisher_cls = Publisher
    consumer_cls = Consumer
    _closed = True

    def __init__(self, connection, **kwargs):
        self.connection = connection
        self.exchange = kwargs.get("exchange", self.exchange)
        self.queue = kwargs.get("queue", self.queue)
        self.routing_key = kwargs.get("routing_key", self.routing_key)
        self.publisher = self.publisher_cls(connection,
                exchange=self.exchange, routing_key=self.routing_key)
        self.consumer = self.consumer_cls(connection, queue=self.queue,
                exchange=self.exchange, routing_key=self.routing_key)
        self.consumer.register_callback(self.receive)
        self.callbacks = []
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, e_type, e_value, e_trace):
        if e_type:
            raise e_type(e_value)
        self.close()

    def register_callback(self, callback):
        """See :meth:`Consumer.register_callback`"""
        self.callbacks.append(callback)

    def receive(self, message_data, message):
        """See :meth:`Consumer.receive`"""
        if not self.callbacks:
            raise NotImplementedError("No consumer callbacks registered")
        for callback in self.callbacks:
            callback(message_data, message)

    def send(self, message_data, delivery_mode=None):
        """See :meth:`Publisher.send`"""
        self.publisher.send(message_data, delivery_mode=delivery_mode)

    def fetch(self, **kwargs):
        """See :meth:`Consumer.fetch`"""
        return self.consumer.fetch(**kwargs)

    def close(self):
        """Close any open channels."""
        self.consumer.close()
        self.publisher.close()
        self._closed = True


class ConsumerSet(object):
    """Receive messages from multiple consumers.

    :param connection: see :attr:`connection`.
    :param from_dict: see :attr:`from_dict`.
    :param consumers: see :attr:`consumers`.
    :param callbacks: see :attr:`callbacks`.

    .. attribute:: connection

        The connection to the broker.
        A :class:`carrot.connection.BrokerConnection` instance.

    .. attribute:: callbacks

        A list of callbacks to be called when a message is received.
        See :class:`Consumer.register_callback`.

    .. attribute:: from_dict

        Add consumers from a dictionary configuration::

            {
                "webshot": {
                            "exchange": "link_exchange",
                            "exchange_type": "topic",
                            "binding_key": "links.webshot",
                            "default_routing_key": "links.webshot",
                    },
                "retrieve": {
                            "exchange": "link_exchange",
                            "exchange_type" = "topic",
                            "binding_key": "links.*",
                            "default_routing_key": "links.retrieve",
                            "auto_delete": True,
                            # ...
                    },
            }

    .. attribute:: consumers

        Add consumers from a list of :class:`Consumer` instances.

    .. attribute:: auto_ack

        Default value for the :attr:`Consumer.auto_ack` attribute.

    """
    auto_ack = False

    def __init__(self, connection, from_dict=None, consumers=None,
            callbacks=None, **options):
        self.connection = connection
        self.options = options
        self.from_dict = from_dict or {}
        self.consumers = consumers or []
        self.callbacks = callbacks or []
        self._open_consumers = []

        self.backend = self.connection.create_backend()

        self.auto_ack = options.get("auto_ack", self.auto_ack)

        [self.add_consumer_from_dict(queue_name, **queue_options)
                for queue_name, queue_options in self.from_dict.items()]

    def _receive_callback(self, raw_message):
        """Internal method used when a message is received in consume mode."""
        message = self.backend.message_to_python(raw_message)
        if self.auto_ack and not message.acknowledged:
            message.ack()
        self.receive(message.decode(), message)

    def add_consumer_from_dict(self, queue, **options):
        """Add another consumer from dictionary configuration."""
        consumer = Consumer(self.connection, queue=queue,
                backend=self.backend, **options)
        self.consumers.append(consumer)

    def add_consumer(self, consumer):
        """Add another consumer from a :class:`Consumer` instance."""
        consumer.backend = self.backend
        self.consumers.append(consumer)

    def register_callback(self, callback):
        """Register new callback to be called when a message is received.
        See :meth:`Consumer.register_callback`"""
        self.callbacks.append(callback)

    def receive(self, message_data, message):
        """What to do when a message is received.
        See :meth:`Consumer.receive`."""
        if not self.callbacks:
            raise NotImplementedError("No consumer callbacks registered")
        for callback in self.callbacks:
            callback(message_data, message)

    def _declare_consumer(self, consumer, nowait=False):
        """Declare consumer so messages can be received from it using
        :meth:`iterconsume`."""
        # Use the ConsumerSet's consumer by default, but if the
        # child consumer has a callback, honor it.
        callback = consumer.callbacks and \
                consumer._receive_callback or self._receive_callback
        self.backend.declare_consumer(queue=consumer.queue,
                                      no_ack=consumer.no_ack,
                                      nowait=nowait,
                                      callback=callback,
                                      consumer_tag=consumer.consumer_tag)
        self._open_consumers.append(consumer.consumer_tag)

    def iterconsume(self, limit=None):
        """Cycle between all consumers in consume mode.

        See :meth:`Consumer.iterconsume`.
        """
        head = self.consumers[:-1]
        tail = self.consumers[-1]
        [self._declare_consumer(consumer, nowait=True)
                for consumer in head]
        self._declare_consumer(tail, nowait=False)

        return self.backend.consume(limit=limit)

    def discard_all(self):
        """Discard all messages. Does not support filtering.
        See :meth:`Consumer.discard_all`."""
        return sum([consumer.discard_all()
                        for consumer in self.consumers])

    def flow(self, active):
        """This method asks the peer to pause or restart the flow of
        content data.

        See :meth:`Consumer.flow`.

        """
        self.backend.flow(active)

    def qos(self, prefetch_size=0, prefetch_count=0, apply_global=False):
        """Request specific Quality of Service.

        See :meth:`Consumer.cos`.

        """
        self.backend.qos(prefetch_size, prefetch_count, apply_global)

    def cancel(self):
        """Cancel a running :meth:`iterconsume` session."""
        for consumer_tag in self._open_consumers:
            try:
                self.backend.cancel(consumer_tag)
            except KeyError:
                pass
        self._open_consumers = []

    def close(self):
        """Close all consumers."""
        self.cancel()
        for consumer in self.consumers:
            consumer.close()

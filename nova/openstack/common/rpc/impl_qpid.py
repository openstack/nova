# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack Foundation
#    Copyright 2011 - 2012, Red Hat, Inc.
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

import functools
import itertools
import time
import uuid

import eventlet
import greenlet
from oslo.config import cfg

from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import amqp as rpc_amqp
from nova.openstack.common.rpc import common as rpc_common

qpid_codec = importutils.try_import("qpid.codec010")
qpid_messaging = importutils.try_import("qpid.messaging")
qpid_exceptions = importutils.try_import("qpid.messaging.exceptions")

LOG = logging.getLogger(__name__)

qpid_opts = [
    cfg.StrOpt('qpid_hostname',
               default='localhost',
               help='Qpid broker hostname'),
    cfg.IntOpt('qpid_port',
               default=5672,
               help='Qpid broker port'),
    cfg.ListOpt('qpid_hosts',
                default=['$qpid_hostname:$qpid_port'],
                help='Qpid HA cluster host:port pairs'),
    cfg.StrOpt('qpid_username',
               default='',
               help='Username for qpid connection'),
    cfg.StrOpt('qpid_password',
               default='',
               help='Password for qpid connection',
               secret=True),
    cfg.StrOpt('qpid_sasl_mechanisms',
               default='',
               help='Space separated list of SASL mechanisms to use for auth'),
    cfg.IntOpt('qpid_heartbeat',
               default=60,
               help='Seconds between connection keepalive heartbeats'),
    cfg.StrOpt('qpid_protocol',
               default='tcp',
               help="Transport to use, either 'tcp' or 'ssl'"),
    cfg.BoolOpt('qpid_tcp_nodelay',
                default=True,
                help='Disable Nagle algorithm'),
    # NOTE(russellb) If any additional versions are added (beyond 1 and 2),
    # this file could probably use some additional refactoring so that the
    # differences between each version are split into different classes.
    cfg.IntOpt('qpid_topology_version',
               default=1,
               help="The qpid topology version to use.  Version 1 is what "
                    "was originally used by impl_qpid.  Version 2 includes "
                    "some backwards-incompatible changes that allow broker "
                    "federation to work.  Users should update to version 2 "
                    "when they are able to take everything down, as it "
                    "requires a clean break."),
]

cfg.CONF.register_opts(qpid_opts)

JSON_CONTENT_TYPE = 'application/json; charset=utf8'


def raise_invalid_topology_version(conf):
    msg = (_("Invalid value for qpid_topology_version: %d") %
           conf.qpid_topology_version)
    LOG.error(msg)
    raise Exception(msg)


class ConsumerBase(object):
    """Consumer base class."""

    def __init__(self, conf, session, callback, node_name, node_opts,
                 link_name, link_opts):
        """Declare a queue on an amqp session.

        'session' is the amqp session to use
        'callback' is the callback to call when messages are received
        'node_name' is the first part of the Qpid address string, before ';'
        'node_opts' will be applied to the "x-declare" section of "node"
                    in the address string.
        'link_name' goes into the "name" field of the "link" in the address
                    string
        'link_opts' will be applied to the "x-declare" section of "link"
                    in the address string.
        """
        self.callback = callback
        self.receiver = None
        self.session = None

        if conf.qpid_topology_version == 1:
            addr_opts = {
                "create": "always",
                "node": {
                    "type": "topic",
                    "x-declare": {
                        "durable": True,
                        "auto-delete": True,
                    },
                },
                "link": {
                    "name": link_name,
                    "durable": True,
                    "x-declare": {
                        "durable": False,
                        "auto-delete": True,
                        "exclusive": False,
                    },
                },
            }
            addr_opts["node"]["x-declare"].update(node_opts)
        elif conf.qpid_topology_version == 2:
            addr_opts = {
                "link": {
                    "x-declare": {
                        "auto-delete": True,
                    },
                },
            }
        else:
            raise_invalid_topology_version()

        addr_opts["link"]["x-declare"].update(link_opts)

        self.address = "%s ; %s" % (node_name, jsonutils.dumps(addr_opts))

        self.connect(session)

    def connect(self, session):
        """Declare the reciever on connect."""
        self._declare_receiver(session)

    def reconnect(self, session):
        """Re-declare the receiver after a qpid reconnect."""
        self._declare_receiver(session)

    def _declare_receiver(self, session):
        self.session = session
        self.receiver = session.receiver(self.address)
        self.receiver.capacity = 1

    def _unpack_json_msg(self, msg):
        """Load the JSON data in msg if msg.content_type indicates that it
           is necessary.  Put the loaded data back into msg.content and
           update msg.content_type appropriately.

        A Qpid Message containing a dict will have a content_type of
        'amqp/map', whereas one containing a string that needs to be converted
        back from JSON will have a content_type of JSON_CONTENT_TYPE.

        :param msg: a Qpid Message object
        :returns: None
        """
        if msg.content_type == JSON_CONTENT_TYPE:
            msg.content = jsonutils.loads(msg.content)
            msg.content_type = 'amqp/map'

    def consume(self):
        """Fetch the message and pass it to the callback object."""
        message = self.receiver.fetch()
        try:
            self._unpack_json_msg(message)
            msg = rpc_common.deserialize_msg(message.content)
            self.callback(msg)
        except Exception:
            LOG.exception(_("Failed to process message... skipping it."))
        finally:
            # TODO(sandy): Need support for optional ack_on_error.
            self.session.acknowledge(message)

    def get_receiver(self):
        return self.receiver

    def get_node_name(self):
        return self.address.split(';')[0]


class DirectConsumer(ConsumerBase):
    """Queue/consumer class for 'direct'."""

    def __init__(self, conf, session, msg_id, callback):
        """Init a 'direct' queue.

        'session' is the amqp session to use
        'msg_id' is the msg_id to listen on
        'callback' is the callback to call when messages are received
        """

        link_opts = {
            "auto-delete": conf.amqp_auto_delete,
            "exclusive": True,
            "durable": conf.amqp_durable_queues,
        }

        if conf.qpid_topology_version == 1:
            node_name = "%s/%s" % (msg_id, msg_id)
            node_opts = {"type": "direct"}
        elif conf.qpid_topology_version == 2:
            node_name = "amq.direct/%s" % msg_id
            node_opts = {}
        else:
            raise_invalid_topology_version()

        super(DirectConsumer, self).__init__(conf, session, callback,
                                             node_name, node_opts, msg_id,
                                             link_opts)


class TopicConsumer(ConsumerBase):
    """Consumer class for 'topic'."""

    def __init__(self, conf, session, topic, callback, name=None,
                 exchange_name=None):
        """Init a 'topic' queue.

        :param session: the amqp session to use
        :param topic: is the topic to listen on
        :paramtype topic: str
        :param callback: the callback to call when messages are received
        :param name: optional queue name, defaults to topic
        """

        exchange_name = exchange_name or rpc_amqp.get_control_exchange(conf)
        link_opts = {
            "auto-delete": conf.amqp_auto_delete,
            "durable": conf.amqp_durable_queues,
        }

        if conf.qpid_topology_version == 1:
            node_name = "%s/%s" % (exchange_name, topic)
        elif conf.qpid_topology_version == 2:
            node_name = "amq.topic/topic/%s/%s" % (exchange_name, topic)
        else:
            raise_invalid_topology_version()

        super(TopicConsumer, self).__init__(conf, session, callback, node_name,
                                            {}, name or topic, link_opts)


class FanoutConsumer(ConsumerBase):
    """Consumer class for 'fanout'."""

    def __init__(self, conf, session, topic, callback):
        """Init a 'fanout' queue.

        'session' is the amqp session to use
        'topic' is the topic to listen on
        'callback' is the callback to call when messages are received
        """
        self.conf = conf

        link_opts = {"exclusive": True}

        if conf.qpid_topology_version == 1:
            node_name = "%s_fanout" % topic
            node_opts = {"durable": False, "type": "fanout"}
            link_name = "%s_fanout_%s" % (topic, uuid.uuid4().hex)
        elif conf.qpid_topology_version == 2:
            node_name = "amq.topic/fanout/%s" % topic
            node_opts = {}
            link_name = ""
        else:
            raise_invalid_topology_version()

        super(FanoutConsumer, self).__init__(conf, session, callback,
                                             node_name, node_opts, link_name,
                                             link_opts)

    def reconnect(self, session):
        topic = self.get_node_name().rpartition('_fanout')[0]
        params = {
            'session': session,
            'topic': topic,
            'callback': self.callback,
        }

        self.__init__(conf=self.conf, **params)

        super(FanoutConsumer, self).reconnect(session)


class Publisher(object):
    """Base Publisher class."""

    def __init__(self, conf, session, node_name, node_opts=None):
        """Init the Publisher class with the exchange_name, routing_key,
        and other options
        """
        self.sender = None
        self.session = session

        if conf.qpid_topology_version == 1:
            addr_opts = {
                "create": "always",
                "node": {
                    "type": "topic",
                    "x-declare": {
                        "durable": False,
                        # auto-delete isn't implemented for exchanges in qpid,
                        # but put in here anyway
                        "auto-delete": True,
                    },
                },
            }
            if node_opts:
                addr_opts["node"]["x-declare"].update(node_opts)

            self.address = "%s ; %s" % (node_name, jsonutils.dumps(addr_opts))
        elif conf.qpid_topology_version == 2:
            self.address = node_name
        else:
            raise_invalid_topology_version()

        self.reconnect(session)

    def reconnect(self, session):
        """Re-establish the Sender after a reconnection."""
        self.sender = session.sender(self.address)

    def _pack_json_msg(self, msg):
        """Qpid cannot serialize dicts containing strings longer than 65535
           characters.  This function dumps the message content to a JSON
           string, which Qpid is able to handle.

        :param msg: May be either a Qpid Message object or a bare dict.
        :returns: A Qpid Message with its content field JSON encoded.
        """
        try:
            msg.content = jsonutils.dumps(msg.content)
        except AttributeError:
            # Need to have a Qpid message so we can set the content_type.
            msg = qpid_messaging.Message(jsonutils.dumps(msg))
        msg.content_type = JSON_CONTENT_TYPE
        return msg

    def send(self, msg):
        """Send a message."""
        try:
            # Check if Qpid can encode the message
            check_msg = msg
            if not hasattr(check_msg, 'content_type'):
                check_msg = qpid_messaging.Message(msg)
            content_type = check_msg.content_type
            enc, dec = qpid_messaging.message.get_codec(content_type)
            enc(check_msg.content)
        except qpid_codec.CodecException:
            # This means the message couldn't be serialized as a dict.
            msg = self._pack_json_msg(msg)
        self.sender.send(msg)


class DirectPublisher(Publisher):
    """Publisher class for 'direct'."""
    def __init__(self, conf, session, msg_id):
        """Init a 'direct' publisher."""

        if conf.qpid_topology_version == 1:
            node_name = msg_id
            node_opts = {"type": "direct"}
        elif conf.qpid_topology_version == 2:
            node_name = "amq.direct/%s" % msg_id
            node_opts = {}
        else:
            raise_invalid_topology_version()

        super(DirectPublisher, self).__init__(conf, session, node_name,
                                              node_opts)


class TopicPublisher(Publisher):
    """Publisher class for 'topic'."""
    def __init__(self, conf, session, topic):
        """init a 'topic' publisher.
        """
        exchange_name = rpc_amqp.get_control_exchange(conf)

        if conf.qpid_topology_version == 1:
            node_name = "%s/%s" % (exchange_name, topic)
        elif conf.qpid_topology_version == 2:
            node_name = "amq.topic/topic/%s/%s" % (exchange_name, topic)
        else:
            raise_invalid_topology_version()

        super(TopicPublisher, self).__init__(conf, session, node_name)


class FanoutPublisher(Publisher):
    """Publisher class for 'fanout'."""
    def __init__(self, conf, session, topic):
        """init a 'fanout' publisher.
        """

        if conf.qpid_topology_version == 1:
            node_name = "%s_fanout" % topic
            node_opts = {"type": "fanout"}
        elif conf.qpid_topology_version == 2:
            node_name = "amq.topic/fanout/%s" % topic
            node_opts = {}
        else:
            raise_invalid_topology_version()

        super(FanoutPublisher, self).__init__(conf, session, node_name,
                                              node_opts)


class NotifyPublisher(Publisher):
    """Publisher class for notifications."""
    def __init__(self, conf, session, topic):
        """init a 'topic' publisher.
        """
        exchange_name = rpc_amqp.get_control_exchange(conf)
        node_opts = {"durable": True}

        if conf.qpid_topology_version == 1:
            node_name = "%s/%s" % (exchange_name, topic)
        elif conf.qpid_topology_version == 2:
            node_name = "amq.topic/topic/%s/%s" % (exchange_name, topic)
        else:
            raise_invalid_topology_version()

        super(NotifyPublisher, self).__init__(conf, session, node_name,
                                              node_opts)


class Connection(object):
    """Connection object."""

    pool = None

    def __init__(self, conf, server_params=None):
        if not qpid_messaging:
            raise ImportError("Failed to import qpid.messaging")

        self.session = None
        self.consumers = {}
        self.consumer_thread = None
        self.proxy_callbacks = []
        self.conf = conf

        if server_params and 'hostname' in server_params:
            # NOTE(russellb) This enables support for cast_to_server.
            server_params['qpid_hosts'] = [
                '%s:%d' % (server_params['hostname'],
                           server_params.get('port', 5672))
            ]

        params = {
            'qpid_hosts': self.conf.qpid_hosts,
            'username': self.conf.qpid_username,
            'password': self.conf.qpid_password,
        }
        params.update(server_params or {})

        self.brokers = params['qpid_hosts']
        self.username = params['username']
        self.password = params['password']
        self.connection_create(self.brokers[0])
        self.reconnect()

    def connection_create(self, broker):
        # Create the connection - this does not open the connection
        self.connection = qpid_messaging.Connection(broker)

        # Check if flags are set and if so set them for the connection
        # before we call open
        self.connection.username = self.username
        self.connection.password = self.password

        self.connection.sasl_mechanisms = self.conf.qpid_sasl_mechanisms
        # Reconnection is done by self.reconnect()
        self.connection.reconnect = False
        self.connection.heartbeat = self.conf.qpid_heartbeat
        self.connection.transport = self.conf.qpid_protocol
        self.connection.tcp_nodelay = self.conf.qpid_tcp_nodelay

    def _register_consumer(self, consumer):
        self.consumers[str(consumer.get_receiver())] = consumer

    def _lookup_consumer(self, receiver):
        return self.consumers[str(receiver)]

    def reconnect(self):
        """Handles reconnecting and re-establishing sessions and queues."""
        attempt = 0
        delay = 1
        while True:
            # Close the session if necessary
            if self.connection.opened():
                try:
                    self.connection.close()
                except qpid_exceptions.ConnectionError:
                    pass

            broker = self.brokers[attempt % len(self.brokers)]
            attempt += 1

            try:
                self.connection_create(broker)
                self.connection.open()
            except qpid_exceptions.ConnectionError as e:
                msg_dict = dict(e=e, delay=delay)
                msg = _("Unable to connect to AMQP server: %(e)s. "
                        "Sleeping %(delay)s seconds") % msg_dict
                LOG.error(msg)
                time.sleep(delay)
                delay = min(2 * delay, 60)
            else:
                LOG.info(_('Connected to AMQP server on %s'), broker)
                break

        self.session = self.connection.session()

        if self.consumers:
            consumers = self.consumers
            self.consumers = {}

            for consumer in consumers.itervalues():
                consumer.reconnect(self.session)
                self._register_consumer(consumer)

            LOG.debug(_("Re-established AMQP queues"))

    def ensure(self, error_callback, method, *args, **kwargs):
        while True:
            try:
                return method(*args, **kwargs)
            except (qpid_exceptions.Empty,
                    qpid_exceptions.ConnectionError) as e:
                if error_callback:
                    error_callback(e)
                self.reconnect()

    def close(self):
        """Close/release this connection."""
        self.cancel_consumer_thread()
        self.wait_on_proxy_callbacks()
        try:
            self.connection.close()
        except Exception:
            # NOTE(dripton) Logging exceptions that happen during cleanup just
            # causes confusion; there's really nothing useful we can do with
            # them.
            pass
        self.connection = None

    def reset(self):
        """Reset a connection so it can be used again."""
        self.cancel_consumer_thread()
        self.wait_on_proxy_callbacks()
        self.session.close()
        self.session = self.connection.session()
        self.consumers = {}

    def declare_consumer(self, consumer_cls, topic, callback):
        """Create a Consumer using the class that was passed in and
        add it to our list of consumers
        """
        def _connect_error(exc):
            log_info = {'topic': topic, 'err_str': str(exc)}
            LOG.error(_("Failed to declare consumer for topic '%(topic)s': "
                      "%(err_str)s") % log_info)

        def _declare_consumer():
            consumer = consumer_cls(self.conf, self.session, topic, callback)
            self._register_consumer(consumer)
            return consumer

        return self.ensure(_connect_error, _declare_consumer)

    def iterconsume(self, limit=None, timeout=None):
        """Return an iterator that will consume from all queues/consumers."""

        def _error_callback(exc):
            if isinstance(exc, qpid_exceptions.Empty):
                LOG.debug(_('Timed out waiting for RPC response: %s') %
                          str(exc))
                raise rpc_common.Timeout()
            else:
                LOG.exception(_('Failed to consume message from queue: %s') %
                              str(exc))

        def _consume():
            nxt_receiver = self.session.next_receiver(timeout=timeout)
            try:
                self._lookup_consumer(nxt_receiver).consume()
            except Exception:
                LOG.exception(_("Error processing message.  Skipping it."))

        for iteration in itertools.count(0):
            if limit and iteration >= limit:
                raise StopIteration
            yield self.ensure(_error_callback, _consume)

    def cancel_consumer_thread(self):
        """Cancel a consumer thread."""
        if self.consumer_thread is not None:
            self.consumer_thread.kill()
            try:
                self.consumer_thread.wait()
            except greenlet.GreenletExit:
                pass
            self.consumer_thread = None

    def wait_on_proxy_callbacks(self):
        """Wait for all proxy callback threads to exit."""
        for proxy_cb in self.proxy_callbacks:
            proxy_cb.wait()

    def publisher_send(self, cls, topic, msg):
        """Send to a publisher based on the publisher class."""

        def _connect_error(exc):
            log_info = {'topic': topic, 'err_str': str(exc)}
            LOG.exception(_("Failed to publish message to topic "
                          "'%(topic)s': %(err_str)s") % log_info)

        def _publisher_send():
            publisher = cls(self.conf, self.session, topic)
            publisher.send(msg)

        return self.ensure(_connect_error, _publisher_send)

    def declare_direct_consumer(self, topic, callback):
        """Create a 'direct' queue.
        In nova's use, this is generally a msg_id queue used for
        responses for call/multicall
        """
        self.declare_consumer(DirectConsumer, topic, callback)

    def declare_topic_consumer(self, topic, callback=None, queue_name=None,
                               exchange_name=None):
        """Create a 'topic' consumer."""
        self.declare_consumer(functools.partial(TopicConsumer,
                                                name=queue_name,
                                                exchange_name=exchange_name,
                                                ),
                              topic, callback)

    def declare_fanout_consumer(self, topic, callback):
        """Create a 'fanout' consumer."""
        self.declare_consumer(FanoutConsumer, topic, callback)

    def direct_send(self, msg_id, msg):
        """Send a 'direct' message."""
        self.publisher_send(DirectPublisher, msg_id, msg)

    def topic_send(self, topic, msg, timeout=None):
        """Send a 'topic' message."""
        #
        # We want to create a message with attributes, e.g. a TTL. We
        # don't really need to keep 'msg' in its JSON format any longer
        # so let's create an actual qpid message here and get some
        # value-add on the go.
        #
        # WARNING: Request timeout happens to be in the same units as
        # qpid's TTL (seconds). If this changes in the future, then this
        # will need to be altered accordingly.
        #
        qpid_message = qpid_messaging.Message(content=msg, ttl=timeout)
        self.publisher_send(TopicPublisher, topic, qpid_message)

    def fanout_send(self, topic, msg):
        """Send a 'fanout' message."""
        self.publisher_send(FanoutPublisher, topic, msg)

    def notify_send(self, topic, msg, **kwargs):
        """Send a notify message on a topic."""
        self.publisher_send(NotifyPublisher, topic, msg)

    def consume(self, limit=None):
        """Consume from all queues/consumers."""
        it = self.iterconsume(limit=limit)
        while True:
            try:
                it.next()
            except StopIteration:
                return

    def consume_in_thread(self):
        """Consumer from all queues/consumers in a greenthread."""
        @excutils.forever_retry_uncaught_exceptions
        def _consumer_thread():
            try:
                self.consume()
            except greenlet.GreenletExit:
                return
        if self.consumer_thread is None:
            self.consumer_thread = eventlet.spawn(_consumer_thread)
        return self.consumer_thread

    def create_consumer(self, topic, proxy, fanout=False):
        """Create a consumer that calls a method in a proxy object."""
        proxy_cb = rpc_amqp.ProxyCallback(
            self.conf, proxy,
            rpc_amqp.get_connection_pool(self.conf, Connection))
        self.proxy_callbacks.append(proxy_cb)

        if fanout:
            consumer = FanoutConsumer(self.conf, self.session, topic, proxy_cb)
        else:
            consumer = TopicConsumer(self.conf, self.session, topic, proxy_cb)

        self._register_consumer(consumer)

        return consumer

    def create_worker(self, topic, proxy, pool_name):
        """Create a worker that calls a method in a proxy object."""
        proxy_cb = rpc_amqp.ProxyCallback(
            self.conf, proxy,
            rpc_amqp.get_connection_pool(self.conf, Connection))
        self.proxy_callbacks.append(proxy_cb)

        consumer = TopicConsumer(self.conf, self.session, topic, proxy_cb,
                                 name=pool_name)

        self._register_consumer(consumer)

        return consumer

    def join_consumer_pool(self, callback, pool_name, topic,
                           exchange_name=None, ack_on_error=True):
        """Register as a member of a group of consumers for a given topic from
        the specified exchange.

        Exactly one member of a given pool will receive each message.

        A message will be delivered to multiple pools, if more than
        one is created.
        """
        callback_wrapper = rpc_amqp.CallbackWrapper(
            conf=self.conf,
            callback=callback,
            connection_pool=rpc_amqp.get_connection_pool(self.conf,
                                                         Connection),
            wait_for_consumers=not ack_on_error
        )
        self.proxy_callbacks.append(callback_wrapper)

        consumer = TopicConsumer(conf=self.conf,
                                 session=self.session,
                                 topic=topic,
                                 callback=callback_wrapper,
                                 name=pool_name,
                                 exchange_name=exchange_name)

        self._register_consumer(consumer)
        return consumer


def create_connection(conf, new=True):
    """Create a connection."""
    return rpc_amqp.create_connection(
        conf, new,
        rpc_amqp.get_connection_pool(conf, Connection))


def multicall(conf, context, topic, msg, timeout=None):
    """Make a call that returns multiple times."""
    return rpc_amqp.multicall(
        conf, context, topic, msg, timeout,
        rpc_amqp.get_connection_pool(conf, Connection))


def call(conf, context, topic, msg, timeout=None):
    """Sends a message on a topic and wait for a response."""
    return rpc_amqp.call(
        conf, context, topic, msg, timeout,
        rpc_amqp.get_connection_pool(conf, Connection))


def cast(conf, context, topic, msg):
    """Sends a message on a topic without waiting for a response."""
    return rpc_amqp.cast(
        conf, context, topic, msg,
        rpc_amqp.get_connection_pool(conf, Connection))


def fanout_cast(conf, context, topic, msg):
    """Sends a message on a fanout exchange without waiting for a response."""
    return rpc_amqp.fanout_cast(
        conf, context, topic, msg,
        rpc_amqp.get_connection_pool(conf, Connection))


def cast_to_server(conf, context, server_params, topic, msg):
    """Sends a message on a topic to a specific server."""
    return rpc_amqp.cast_to_server(
        conf, context, server_params, topic, msg,
        rpc_amqp.get_connection_pool(conf, Connection))


def fanout_cast_to_server(conf, context, server_params, topic, msg):
    """Sends a message on a fanout exchange to a specific server."""
    return rpc_amqp.fanout_cast_to_server(
        conf, context, server_params, topic, msg,
        rpc_amqp.get_connection_pool(conf, Connection))


def notify(conf, context, topic, msg, envelope):
    """Sends a notification event on a topic."""
    return rpc_amqp.notify(conf, context, topic, msg,
                           rpc_amqp.get_connection_pool(conf, Connection),
                           envelope)


def cleanup():
    return rpc_amqp.cleanup(Connection.pool)

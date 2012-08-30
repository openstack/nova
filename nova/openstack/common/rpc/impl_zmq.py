# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 Cloudscaling Group, Inc
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

import pprint
import socket
import string
import sys
import types
import uuid

import eventlet
from eventlet.green import zmq
import greenlet

from nova.openstack.common import cfg
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common.rpc import common as rpc_common


# for convenience, are not modified.
pformat = pprint.pformat
Timeout = eventlet.timeout.Timeout
LOG = rpc_common.LOG
RemoteError = rpc_common.RemoteError
RPCException = rpc_common.RPCException

zmq_opts = [
    cfg.StrOpt('rpc_zmq_bind_address', default='*',
               help='ZeroMQ bind address. Should be a wildcard (*), '
                    'an ethernet interface, or IP. '
                    'The "host" option should point or resolve to this '
                    'address.'),

    # The module.Class to use for matchmaking.
    cfg.StrOpt(
        'rpc_zmq_matchmaker',
        default=('nova.openstack.common.rpc.'
                 'matchmaker.MatchMakerLocalhost'),
        help='MatchMaker driver',
    ),

    # The following port is unassigned by IANA as of 2012-05-21
    cfg.IntOpt('rpc_zmq_port', default=9501,
               help='ZeroMQ receiver listening port'),

    cfg.IntOpt('rpc_zmq_contexts', default=1,
               help='Number of ZeroMQ contexts, defaults to 1'),

    cfg.StrOpt('rpc_zmq_ipc_dir', default='/var/run/openstack',
               help='Directory for holding IPC sockets'),

    cfg.StrOpt('rpc_zmq_host', default=socket.gethostname(),
               help='Name of this node. Must be a valid hostname, FQDN, or '
                    'IP address. Must match "host" option, if running Nova.')
]


# These globals are defined in register_opts(conf),
# a mandatory initialization call
CONF = None
ZMQ_CTX = None  # ZeroMQ Context, must be global.
matchmaker = None  # memoized matchmaker object


def _serialize(data):
    """
    Serialization wrapper
    We prefer using JSON, but it cannot encode all types.
    Error if a developer passes us bad data.
    """
    try:
        return str(jsonutils.dumps(data, ensure_ascii=True))
    except TypeError:
        LOG.error(_("JSON serialization failed."))
        raise


def _deserialize(data):
    """
    Deserialization wrapper
    """
    LOG.debug(_("Deserializing: %s"), data)
    return jsonutils.loads(data)


class ZmqSocket(object):
    """
    A tiny wrapper around ZeroMQ to simplify the send/recv protocol
    and connection management.

    Can be used as a Context (supports the 'with' statement).
    """

    def __init__(self, addr, zmq_type, bind=True, subscribe=None):
        self.sock = ZMQ_CTX.socket(zmq_type)
        self.addr = addr
        self.type = zmq_type
        self.subscriptions = []

        # Support failures on sending/receiving on wrong socket type.
        self.can_recv = zmq_type in (zmq.PULL, zmq.SUB)
        self.can_send = zmq_type in (zmq.PUSH, zmq.PUB)
        self.can_sub = zmq_type in (zmq.SUB, )

        # Support list, str, & None for subscribe arg (cast to list)
        do_sub = {
            list: subscribe,
            str: [subscribe],
            type(None): []
        }[type(subscribe)]

        for f in do_sub:
            self.subscribe(f)

        str_data = {'addr': addr, 'type': self.socket_s(),
                    'subscribe': subscribe, 'bind': bind}

        LOG.debug(_("Connecting to %(addr)s with %(type)s"), str_data)
        LOG.debug(_("-> Subscribed to %(subscribe)s"), str_data)
        LOG.debug(_("-> bind: %(bind)s"), str_data)

        try:
            if bind:
                self.sock.bind(addr)
            else:
                self.sock.connect(addr)
        except Exception:
            raise RPCException(_("Could not open socket."))

    def socket_s(self):
        """Get socket type as string."""
        t_enum = ('PUSH', 'PULL', 'PUB', 'SUB', 'REP', 'REQ', 'ROUTER',
                  'DEALER')
        return dict(map(lambda t: (getattr(zmq, t), t), t_enum))[self.type]

    def subscribe(self, msg_filter):
        """Subscribe."""
        if not self.can_sub:
            raise RPCException("Cannot subscribe on this socket.")
        LOG.debug(_("Subscribing to %s"), msg_filter)

        try:
            self.sock.setsockopt(zmq.SUBSCRIBE, msg_filter)
        except Exception:
            return

        self.subscriptions.append(msg_filter)

    def unsubscribe(self, msg_filter):
        """Unsubscribe."""
        if msg_filter not in self.subscriptions:
            return
        self.sock.setsockopt(zmq.UNSUBSCRIBE, msg_filter)
        self.subscriptions.remove(msg_filter)

    def close(self):
        if self.sock is None or self.sock.closed:
            return

        # We must unsubscribe, or we'll leak descriptors.
        if len(self.subscriptions) > 0:
            for f in self.subscriptions:
                try:
                    self.sock.setsockopt(zmq.UNSUBSCRIBE, f)
                except Exception:
                    pass
            self.subscriptions = []

        # Linger -1 prevents lost/dropped messages
        try:
            self.sock.close(linger=-1)
        except Exception:
            pass
        self.sock = None

    def recv(self):
        if not self.can_recv:
            raise RPCException(_("You cannot recv on this socket."))
        return self.sock.recv_multipart()

    def send(self, data):
        if not self.can_send:
            raise RPCException(_("You cannot send on this socket."))
        self.sock.send_multipart(data)


class ZmqClient(object):
    """Client for ZMQ sockets."""

    def __init__(self, addr, socket_type=zmq.PUSH, bind=False):
        self.outq = ZmqSocket(addr, socket_type, bind=bind)

    def cast(self, msg_id, topic, data):
        self.outq.send([str(msg_id), str(topic), str('cast'),
                        _serialize(data)])

    def close(self):
        self.outq.close()


class RpcContext(rpc_common.CommonRpcContext):
    """Context that supports replying to a rpc.call."""
    def __init__(self, **kwargs):
        self.replies = []
        super(RpcContext, self).__init__(**kwargs)

    def deepcopy(self):
        values = self.to_dict()
        values['replies'] = self.replies
        return self.__class__(**values)

    def reply(self, reply=None, failure=None, ending=False):
        if ending:
            return
        self.replies.append(reply)

    @classmethod
    def marshal(self, ctx):
        ctx_data = ctx.to_dict()
        return _serialize(ctx_data)

    @classmethod
    def unmarshal(self, data):
        return RpcContext.from_dict(_deserialize(data))


class InternalContext(object):
    """Used by ConsumerBase as a private context for - methods."""

    def __init__(self, proxy):
        self.proxy = proxy
        self.msg_waiter = None

    def _get_response(self, ctx, proxy, topic, data):
        """Process a curried message and cast the result to topic."""
        LOG.debug(_("Running func with context: %s"), ctx.to_dict())
        data.setdefault('version', None)
        data.setdefault('args', [])

        try:
            result = proxy.dispatch(
                ctx, data['version'], data['method'], **data['args'])
            return ConsumerBase.normalize_reply(result, ctx.replies)
        except greenlet.GreenletExit:
            # ignore these since they are just from shutdowns
            pass
        except Exception:
            return {'exc':
                    rpc_common.serialize_remote_exception(sys.exc_info())}

    def reply(self, ctx, proxy,
              msg_id=None, context=None, topic=None, msg=None):
        """Reply to a casted call."""
        # Our real method is curried into msg['args']

        child_ctx = RpcContext.unmarshal(msg[0])
        response = ConsumerBase.normalize_reply(
            self._get_response(child_ctx, proxy, topic, msg[1]),
            ctx.replies)

        LOG.debug(_("Sending reply"))
        cast(CONF, ctx, topic, {
            'method': '-process_reply',
            'args': {
                'msg_id': msg_id,
                'response': response
            }
        })


class ConsumerBase(object):
    """Base Consumer."""

    def __init__(self):
        self.private_ctx = InternalContext(None)

    @classmethod
    def normalize_reply(self, result, replies):
        #TODO(ewindisch): re-evaluate and document this method.
        if isinstance(result, types.GeneratorType):
            return list(result)
        elif replies:
            return replies
        else:
            return [result]

    def process(self, style, target, proxy, ctx, data):
        # Method starting with - are
        # processed internally. (non-valid method name)
        method = data['method']

        # Internal method
        # uses internal context for safety.
        if data['method'][0] == '-':
            # For reply / process_reply
            method = method[1:]
            if method == 'reply':
                self.private_ctx.reply(ctx, proxy, **data['args'])
            return

        data.setdefault('version', None)
        data.setdefault('args', [])
        proxy.dispatch(ctx, data['version'],
                       data['method'], **data['args'])


class ZmqBaseReactor(ConsumerBase):
    """
    A consumer class implementing a
    centralized casting broker (PULL-PUSH)
    for RoundRobin requests.
    """

    def __init__(self, conf):
        super(ZmqBaseReactor, self).__init__()

        self.mapping = {}
        self.proxies = {}
        self.threads = []
        self.sockets = []
        self.subscribe = {}

        self.pool = eventlet.greenpool.GreenPool(conf.rpc_thread_pool_size)

    def register(self, proxy, in_addr, zmq_type_in, out_addr=None,
                 zmq_type_out=None, in_bind=True, out_bind=True,
                 subscribe=None):

        LOG.info(_("Registering reactor"))

        if zmq_type_in not in (zmq.PULL, zmq.SUB):
            raise RPCException("Bad input socktype")

        # Items push in.
        inq = ZmqSocket(in_addr, zmq_type_in, bind=in_bind,
                        subscribe=subscribe)

        self.proxies[inq] = proxy
        self.sockets.append(inq)

        LOG.info(_("In reactor registered"))

        if not out_addr:
            return

        if zmq_type_out not in (zmq.PUSH, zmq.PUB):
            raise RPCException("Bad output socktype")

        # Items push out.
        outq = ZmqSocket(out_addr, zmq_type_out, bind=out_bind)

        self.mapping[inq] = outq
        self.mapping[outq] = inq
        self.sockets.append(outq)

        LOG.info(_("Out reactor registered"))

    def consume_in_thread(self):
        def _consume(sock):
            LOG.info(_("Consuming socket"))
            while True:
                self.consume(sock)

        for k in self.proxies.keys():
            self.threads.append(
                self.pool.spawn(_consume, k)
            )

    def wait(self):
        for t in self.threads:
            t.wait()

    def close(self):
        for s in self.sockets:
            s.close()

        for t in self.threads:
            t.kill()


class ZmqProxy(ZmqBaseReactor):
    """
    A consumer class implementing a
    topic-based proxy, forwarding to
    IPC sockets.
    """

    def __init__(self, conf):
        super(ZmqProxy, self).__init__(conf)

        self.topic_proxy = {}
        ipc_dir = CONF.rpc_zmq_ipc_dir

        self.topic_proxy['zmq_replies'] = \
            ZmqSocket("ipc://%s/zmq_topic_zmq_replies" % (ipc_dir, ),
                      zmq.PUB, bind=True)
        self.sockets.append(self.topic_proxy['zmq_replies'])

    def consume(self, sock):
        ipc_dir = CONF.rpc_zmq_ipc_dir

        #TODO(ewindisch): use zero-copy (i.e. references, not copying)
        data = sock.recv()
        msg_id, topic, style, in_msg = data
        topic = topic.split('.', 1)[0]

        LOG.debug(_("CONSUMER GOT %s"), ' '.join(map(pformat, data)))

        # Handle zmq_replies magic
        if topic.startswith('fanout~'):
            sock_type = zmq.PUB
        elif topic.startswith('zmq_replies'):
            sock_type = zmq.PUB
            inside = _deserialize(in_msg)
            msg_id = inside[-1]['args']['msg_id']
            response = inside[-1]['args']['response']
            LOG.debug(_("->response->%s"), response)
            data = [str(msg_id), _serialize(response)]
        else:
            sock_type = zmq.PUSH

        if not topic in self.topic_proxy:
            outq = ZmqSocket("ipc://%s/zmq_topic_%s" % (ipc_dir, topic),
                             sock_type, bind=True)
            self.topic_proxy[topic] = outq
            self.sockets.append(outq)
            LOG.info(_("Created topic proxy: %s"), topic)

            # It takes some time for a pub socket to open,
            # before we can have any faith in doing a send() to it.
            if sock_type == zmq.PUB:
                eventlet.sleep(.5)

        LOG.debug(_("ROUTER RELAY-OUT START %(data)s") % {'data': data})
        self.topic_proxy[topic].send(data)
        LOG.debug(_("ROUTER RELAY-OUT SUCCEEDED %(data)s") % {'data': data})


class ZmqReactor(ZmqBaseReactor):
    """
    A consumer class implementing a
    consumer for messages. Can also be
    used as a 1:1 proxy
    """

    def __init__(self, conf):
        super(ZmqReactor, self).__init__(conf)

    def consume(self, sock):
        #TODO(ewindisch): use zero-copy (i.e. references, not copying)
        data = sock.recv()
        LOG.debug(_("CONSUMER RECEIVED DATA: %s"), data)
        if sock in self.mapping:
            LOG.debug(_("ROUTER RELAY-OUT %(data)s") % {
                'data': data})
            self.mapping[sock].send(data)
            return

        msg_id, topic, style, in_msg = data

        ctx, request = _deserialize(in_msg)
        ctx = RpcContext.unmarshal(ctx)

        proxy = self.proxies[sock]

        self.pool.spawn_n(self.process, style, topic,
                          proxy, ctx, request)


class Connection(rpc_common.Connection):
    """Manages connections and threads."""

    def __init__(self, conf):
        self.reactor = ZmqReactor(conf)

    def create_consumer(self, topic, proxy, fanout=False):
        # Only consume on the base topic name.
        topic = topic.split('.', 1)[0]

        LOG.info(_("Create Consumer for topic (%(topic)s)") %
                 {'topic': topic})

        # Subscription scenarios
        if fanout:
            subscribe = ('', fanout)[type(fanout) == str]
            sock_type = zmq.SUB
            topic = 'fanout~' + topic
        else:
            sock_type = zmq.PULL
            subscribe = None

        # Receive messages from (local) proxy
        inaddr = "ipc://%s/zmq_topic_%s" % \
            (CONF.rpc_zmq_ipc_dir, topic)

        LOG.debug(_("Consumer is a zmq.%s"),
                  ['PULL', 'SUB'][sock_type == zmq.SUB])

        self.reactor.register(proxy, inaddr, sock_type,
                              subscribe=subscribe, in_bind=False)

    def close(self):
        self.reactor.close()

    def wait(self):
        self.reactor.wait()

    def consume_in_thread(self):
        self.reactor.consume_in_thread()


def _cast(addr, context, msg_id, topic, msg, timeout=None):
    timeout_cast = timeout or CONF.rpc_cast_timeout
    payload = [RpcContext.marshal(context), msg]

    with Timeout(timeout_cast, exception=rpc_common.Timeout):
        try:
            conn = ZmqClient(addr)

            # assumes cast can't return an exception
            conn.cast(msg_id, topic, payload)
        except zmq.ZMQError:
            raise RPCException("Cast failed. ZMQ Socket Exception")
        finally:
            if 'conn' in vars():
                conn.close()


def _call(addr, context, msg_id, topic, msg, timeout=None):
    # timeout_response is how long we wait for a response
    timeout = timeout or CONF.rpc_response_timeout

    # The msg_id is used to track replies.
    msg_id = str(uuid.uuid4().hex)

    # Replies always come into the reply service.
    reply_topic = "zmq_replies.%s" % CONF.rpc_zmq_host

    LOG.debug(_("Creating payload"))
    # Curry the original request into a reply method.
    mcontext = RpcContext.marshal(context)
    payload = {
        'method': '-reply',
        'args': {
            'msg_id': msg_id,
            'context': mcontext,
            'topic': reply_topic,
            'msg': [mcontext, msg]
        }
    }

    LOG.debug(_("Creating queue socket for reply waiter"))

    # Messages arriving async.
    # TODO(ewindisch): have reply consumer with dynamic subscription mgmt
    with Timeout(timeout, exception=rpc_common.Timeout):
        try:
            msg_waiter = ZmqSocket(
                "ipc://%s/zmq_topic_zmq_replies" % CONF.rpc_zmq_ipc_dir,
                zmq.SUB, subscribe=msg_id, bind=False
            )

            LOG.debug(_("Sending cast"))
            _cast(addr, context, msg_id, topic, payload)

            LOG.debug(_("Cast sent; Waiting reply"))
            # Blocks until receives reply
            msg = msg_waiter.recv()
            LOG.debug(_("Received message: %s"), msg)
            LOG.debug(_("Unpacking response"))
            responses = _deserialize(msg[-1])
        # ZMQError trumps the Timeout error.
        except zmq.ZMQError:
            raise RPCException("ZMQ Socket Error")
        finally:
            if 'msg_waiter' in vars():
                msg_waiter.close()

    # It seems we don't need to do all of the following,
    # but perhaps it would be useful for multicall?
    # One effect of this is that we're checking all
    # responses for Exceptions.
    for resp in responses:
        if isinstance(resp, types.DictType) and 'exc' in resp:
            raise rpc_common.deserialize_remote_exception(CONF, resp['exc'])

    return responses[-1]


def _multi_send(method, context, topic, msg, timeout=None):
    """
    Wraps the sending of messages,
    dispatches to the matchmaker and sends
    message to all relevant hosts.
    """
    conf = CONF
    LOG.debug(_("%(msg)s") % {'msg': ' '.join(map(pformat, (topic, msg)))})

    queues = matchmaker.queues(topic)
    LOG.debug(_("Sending message(s) to: %s"), queues)

    # Don't stack if we have no matchmaker results
    if len(queues) == 0:
        LOG.warn(_("No matchmaker results. Not casting."))
        # While not strictly a timeout, callers know how to handle
        # this exception and a timeout isn't too big a lie.
        raise rpc_common.Timeout, "No match from matchmaker."

    # This supports brokerless fanout (addresses > 1)
    for queue in queues:
        (_topic, ip_addr) = queue
        _addr = "tcp://%s:%s" % (ip_addr, conf.rpc_zmq_port)

        if method.__name__ == '_cast':
            eventlet.spawn_n(method, _addr, context,
                             _topic, _topic, msg, timeout)
            return
        return method(_addr, context, _topic, _topic, msg, timeout)


def create_connection(conf, new=True):
    return Connection(conf)


def multicall(conf, *args, **kwargs):
    """Multiple calls."""
    return _multi_send(_call, *args, **kwargs)


def call(conf, *args, **kwargs):
    """Send a message, expect a response."""
    data = _multi_send(_call, *args, **kwargs)
    return data[-1]


def cast(conf, *args, **kwargs):
    """Send a message expecting no reply."""
    _multi_send(_cast, *args, **kwargs)


def fanout_cast(conf, context, topic, msg, **kwargs):
    """Send a message to all listening and expect no reply."""
    # NOTE(ewindisch): fanout~ is used because it avoid splitting on .
    # and acts as a non-subtle hint to the matchmaker and ZmqProxy.
    _multi_send(_cast, context, 'fanout~' + str(topic), msg, **kwargs)


def notify(conf, context, topic, msg, **kwargs):
    """
    Send notification event.
    Notifications are sent to topic-priority.
    This differs from the AMQP drivers which send to topic.priority.
    """
    # NOTE(ewindisch): dot-priority in rpc notifier does not
    # work with our assumptions.
    topic.replace('.', '-')
    cast(conf, context, topic, msg, **kwargs)


def cleanup():
    """Clean up resources in use by implementation."""
    global ZMQ_CTX
    global matchmaker
    matchmaker = None
    ZMQ_CTX.term()
    ZMQ_CTX = None


def register_opts(conf):
    """Registration of options for this driver."""
    #NOTE(ewindisch): ZMQ_CTX and matchmaker
    # are initialized here as this is as good
    # an initialization method as any.

    # We memoize through these globals
    global ZMQ_CTX
    global matchmaker
    global CONF

    if not CONF:
        conf.register_opts(zmq_opts)
        CONF = conf
    # Don't re-set, if this method is called twice.
    if not ZMQ_CTX:
        ZMQ_CTX = zmq.Context(conf.rpc_zmq_contexts)
    if not matchmaker:
        # rpc_zmq_matchmaker should be set to a 'module.Class'
        mm_path = conf.rpc_zmq_matchmaker.split('.')
        mm_module = '.'.join(mm_path[:-1])
        mm_class = mm_path[-1]

        # Only initialize a class.
        if mm_path[-1][0] not in string.ascii_uppercase:
            LOG.error(_("Matchmaker could not be loaded.\n"
                      "rpc_zmq_matchmaker is not a class."))
            raise RPCException(_("Error loading Matchmaker."))

        mm_impl = importutils.import_module(mm_module)
        mm_constructor = getattr(mm_impl, mm_class)
        matchmaker = mm_constructor()


register_opts(cfg.CONF)

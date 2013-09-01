# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2011 - 2012, Red Hat, Inc.
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
Shared code between AMQP based openstack.common.rpc implementations.

The code in this module is shared between the rpc implemenations based on AMQP.
Specifically, this includes impl_kombu and impl_qpid.  impl_carrot also uses
AMQP, but is deprecated and predates this code.
"""

import collections
import inspect
import sys
import uuid

from eventlet import greenpool
from eventlet import pools
from eventlet import queue
from eventlet import semaphore
from oslo.config import cfg

from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import local
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common


amqp_opts = [
    cfg.BoolOpt('amqp_durable_queues',
                default=False,
                deprecated_name='rabbit_durable_queues',
                deprecated_group='DEFAULT',
                help='Use durable queues in amqp.'),
    cfg.BoolOpt('amqp_auto_delete',
                default=False,
                help='Auto-delete queues in amqp.'),
]

cfg.CONF.register_opts(amqp_opts)

UNIQUE_ID = '_unique_id'
LOG = logging.getLogger(__name__)


class Pool(pools.Pool):
    """Class that implements a Pool of Connections."""
    def __init__(self, conf, connection_cls, *args, **kwargs):
        self.connection_cls = connection_cls
        self.conf = conf
        kwargs.setdefault("max_size", self.conf.rpc_conn_pool_size)
        kwargs.setdefault("order_as_stack", True)
        super(Pool, self).__init__(*args, **kwargs)
        self.reply_proxy = None

    # TODO(comstud): Timeout connections not used in a while
    def create(self):
        LOG.debug(_('Pool creating new connection'))
        return self.connection_cls(self.conf)

    def empty(self):
        while self.free_items:
            self.get().close()
        # Force a new connection pool to be created.
        # Note that this was added due to failing unit test cases. The issue
        # is the above "while loop" gets all the cached connections from the
        # pool and closes them, but never returns them to the pool, a pool
        # leak. The unit tests hang waiting for an item to be returned to the
        # pool. The unit tests get here via the tearDown() method. In the run
        # time code, it gets here via cleanup() and only appears in service.py
        # just before doing a sys.exit(), so cleanup() only happens once and
        # the leakage is not a problem.
        self.connection_cls.pool = None


_pool_create_sem = semaphore.Semaphore()


def get_connection_pool(conf, connection_cls):
    with _pool_create_sem:
        # Make sure only one thread tries to create the connection pool.
        if not connection_cls.pool:
            connection_cls.pool = Pool(conf, connection_cls)
    return connection_cls.pool


class ConnectionContext(rpc_common.Connection):
    """The class that is actually returned to the create_connection() caller.

    This is essentially a wrapper around Connection that supports 'with'.
    It can also return a new Connection, or one from a pool.

    The function will also catch when an instance of this class is to be
    deleted.  With that we can return Connections to the pool on exceptions
    and so forth without making the caller be responsible for catching them.
    If possible the function makes sure to return a connection to the pool.
    """

    def __init__(self, conf, connection_pool, pooled=True, server_params=None):
        """Create a new connection, or get one from the pool."""
        self.connection = None
        self.conf = conf
        self.connection_pool = connection_pool
        if pooled:
            self.connection = connection_pool.get()
        else:
            self.connection = connection_pool.connection_cls(
                conf,
                server_params=server_params)
        self.pooled = pooled

    def __enter__(self):
        """When with ConnectionContext() is used, return self."""
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
                self.connection_pool.put(self.connection)
            else:
                try:
                    self.connection.close()
                except Exception:
                    pass
            self.connection = None

    def __exit__(self, exc_type, exc_value, tb):
        """End of 'with' statement.  We're done here."""
        self._done()

    def __del__(self):
        """Caller is done with this connection.  Make sure we cleaned up."""
        self._done()

    def close(self):
        """Caller is done with this connection."""
        self._done()

    def create_consumer(self, topic, proxy, fanout=False):
        self.connection.create_consumer(topic, proxy, fanout)

    def create_worker(self, topic, proxy, pool_name):
        self.connection.create_worker(topic, proxy, pool_name)

    def join_consumer_pool(self, callback, pool_name, topic, exchange_name,
                           ack_on_error=True):
        self.connection.join_consumer_pool(callback,
                                           pool_name,
                                           topic,
                                           exchange_name,
                                           ack_on_error)

    def consume_in_thread(self):
        self.connection.consume_in_thread()

    def __getattr__(self, key):
        """Proxy all other calls to the Connection instance."""
        if self.connection:
            return getattr(self.connection, key)
        else:
            raise rpc_common.InvalidRPCConnectionReuse()


class ReplyProxy(ConnectionContext):
    """Connection class for RPC replies / callbacks."""
    def __init__(self, conf, connection_pool):
        self._call_waiters = {}
        self._num_call_waiters = 0
        self._num_call_waiters_wrn_threshhold = 10
        self._reply_q = 'reply_' + uuid.uuid4().hex
        super(ReplyProxy, self).__init__(conf, connection_pool, pooled=False)
        self.declare_direct_consumer(self._reply_q, self._process_data)
        self.consume_in_thread()

    def _process_data(self, message_data):
        msg_id = message_data.pop('_msg_id', None)
        waiter = self._call_waiters.get(msg_id)
        if not waiter:
            LOG.warn(_('No calling threads waiting for msg_id : %(msg_id)s'
                       ', message : %(data)s'), {'msg_id': msg_id,
                                                 'data': message_data})
            LOG.warn(_('_call_waiters: %s') % str(self._call_waiters))
        else:
            waiter.put(message_data)

    def add_call_waiter(self, waiter, msg_id):
        self._num_call_waiters += 1
        if self._num_call_waiters > self._num_call_waiters_wrn_threshhold:
            LOG.warn(_('Number of call waiters is greater than warning '
                       'threshhold: %d. There could be a MulticallProxyWaiter '
                       'leak.') % self._num_call_waiters_wrn_threshhold)
            self._num_call_waiters_wrn_threshhold *= 2
        self._call_waiters[msg_id] = waiter

    def del_call_waiter(self, msg_id):
        self._num_call_waiters -= 1
        del self._call_waiters[msg_id]

    def get_reply_q(self):
        return self._reply_q


def msg_reply(conf, msg_id, reply_q, connection_pool, reply=None,
              failure=None, ending=False, log_failure=True):
    """Sends a reply or an error on the channel signified by msg_id.

    Failure should be a sys.exc_info() tuple.

    """
    with ConnectionContext(conf, connection_pool) as conn:
        if failure:
            failure = rpc_common.serialize_remote_exception(failure,
                                                            log_failure)

        msg = {'result': reply, 'failure': failure}
        if ending:
            msg['ending'] = True
        _add_unique_id(msg)
        # If a reply_q exists, add the msg_id to the reply and pass the
        # reply_q to direct_send() to use it as the response queue.
        # Otherwise use the msg_id for backward compatibilty.
        if reply_q:
            msg['_msg_id'] = msg_id
            conn.direct_send(reply_q, rpc_common.serialize_msg(msg))
        else:
            conn.direct_send(msg_id, rpc_common.serialize_msg(msg))


class RpcContext(rpc_common.CommonRpcContext):
    """Context that supports replying to a rpc.call."""
    def __init__(self, **kwargs):
        self.msg_id = kwargs.pop('msg_id', None)
        self.reply_q = kwargs.pop('reply_q', None)
        self.conf = kwargs.pop('conf')
        super(RpcContext, self).__init__(**kwargs)

    def deepcopy(self):
        values = self.to_dict()
        values['conf'] = self.conf
        values['msg_id'] = self.msg_id
        values['reply_q'] = self.reply_q
        return self.__class__(**values)

    def reply(self, reply=None, failure=None, ending=False,
              connection_pool=None, log_failure=True):
        if self.msg_id:
            msg_reply(self.conf, self.msg_id, self.reply_q, connection_pool,
                      reply, failure, ending, log_failure)
            if ending:
                self.msg_id = None


def unpack_context(conf, msg):
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
    context_dict['reply_q'] = msg.pop('_reply_q', None)
    context_dict['conf'] = conf
    ctx = RpcContext.from_dict(context_dict)
    rpc_common._safe_log(LOG.debug, _('unpacked context: %s'), ctx.to_dict())
    return ctx


def pack_context(msg, context):
    """Pack context into msg.

    Values for message keys need to be less than 255 chars, so we pull
    context out into a bunch of separate keys. If we want to support
    more arguments in rabbit messages, we may want to do the same
    for args at some point.

    """
    if isinstance(context, dict):
        context_d = dict([('_context_%s' % key, value)
                          for (key, value) in context.iteritems()])
    else:
        context_d = dict([('_context_%s' % key, value)
                          for (key, value) in context.to_dict().iteritems()])

    msg.update(context_d)


class _MsgIdCache(object):
    """This class checks any duplicate messages."""

    # NOTE: This value is considered can be a configuration item, but
    #       it is not necessary to change its value in most cases,
    #       so let this value as static for now.
    DUP_MSG_CHECK_SIZE = 16

    def __init__(self, **kwargs):
        self.prev_msgids = collections.deque([],
                                             maxlen=self.DUP_MSG_CHECK_SIZE)

    def check_duplicate_message(self, message_data):
        """AMQP consumers may read same message twice when exceptions occur
           before ack is returned. This method prevents doing it.
        """
        if UNIQUE_ID in message_data:
            msg_id = message_data[UNIQUE_ID]
            if msg_id not in self.prev_msgids:
                self.prev_msgids.append(msg_id)
            else:
                raise rpc_common.DuplicateMessageError(msg_id=msg_id)


def _add_unique_id(msg):
    """Add unique_id for checking duplicate messages."""
    unique_id = uuid.uuid4().hex
    msg.update({UNIQUE_ID: unique_id})
    LOG.debug(_('UNIQUE_ID is %s.') % (unique_id))


class _ThreadPoolWithWait(object):
    """Base class for a delayed invocation manager.

    Used by the Connection class to start up green threads
    to handle incoming messages.
    """

    def __init__(self, conf, connection_pool):
        self.pool = greenpool.GreenPool(conf.rpc_thread_pool_size)
        self.connection_pool = connection_pool
        self.conf = conf

    def wait(self):
        """Wait for all callback threads to exit."""
        self.pool.waitall()


class CallbackWrapper(_ThreadPoolWithWait):
    """Wraps a straight callback.

    Allows it to be invoked in a green thread.
    """

    def __init__(self, conf, callback, connection_pool,
                 wait_for_consumers=False):
        """Initiates CallbackWrapper object.

        :param conf: cfg.CONF instance
        :param callback: a callable (probably a function)
        :param connection_pool: connection pool as returned by
                                get_connection_pool()
        :param wait_for_consumers: wait for all green threads to
                                   complete and raise the last
                                   caught exception, if any.

        """
        super(CallbackWrapper, self).__init__(
            conf=conf,
            connection_pool=connection_pool,
        )
        self.callback = callback
        self.wait_for_consumers = wait_for_consumers
        self.exc_info = None

    def _wrap(self, message_data, **kwargs):
        """Wrap the callback invocation to catch exceptions.
        """
        try:
            self.callback(message_data, **kwargs)
        except Exception:
            self.exc_info = sys.exc_info()

    def __call__(self, message_data):
        self.exc_info = None
        self.pool.spawn_n(self._wrap, message_data)

        if self.wait_for_consumers:
            self.pool.waitall()
            if self.exc_info:
                raise self.exc_info[1], None, self.exc_info[2]


class ProxyCallback(_ThreadPoolWithWait):
    """Calls methods on a proxy object based on method and args."""

    def __init__(self, conf, proxy, connection_pool):
        super(ProxyCallback, self).__init__(
            conf=conf,
            connection_pool=connection_pool,
        )
        self.proxy = proxy
        self.msg_id_cache = _MsgIdCache()

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
        rpc_common._safe_log(LOG.debug, _('received %s'), message_data)
        self.msg_id_cache.check_duplicate_message(message_data)
        ctxt = unpack_context(self.conf, message_data)
        method = message_data.get('method')
        args = message_data.get('args', {})
        version = message_data.get('version')
        namespace = message_data.get('namespace')
        if not method:
            LOG.warn(_('no method for message: %s') % message_data)
            ctxt.reply(_('No method for message: %s') % message_data,
                       connection_pool=self.connection_pool)
            return
        self.pool.spawn_n(self._process_data, ctxt, version, method,
                          namespace, args)

    def _process_data(self, ctxt, version, method, namespace, args):
        """Process a message in a new thread.

        If the proxy object we have has a dispatch method
        (see rpc.dispatcher.RpcDispatcher), pass it the version,
        method, and args and let it dispatch as appropriate.  If not, use
        the old behavior of magically calling the specified method on the
        proxy we have here.
        """
        ctxt.update_store()
        try:
            rval = self.proxy.dispatch(ctxt, version, method, namespace,
                                       **args)
            # Check if the result was a generator
            if inspect.isgenerator(rval):
                for x in rval:
                    ctxt.reply(x, None, connection_pool=self.connection_pool)
            else:
                ctxt.reply(rval, None, connection_pool=self.connection_pool)
            # This final None tells multicall that it is done.
            ctxt.reply(ending=True, connection_pool=self.connection_pool)
        except rpc_common.ClientException as e:
            LOG.debug(_('Expected exception during message handling (%s)') %
                      e._exc_info[1])
            ctxt.reply(None, e._exc_info,
                       connection_pool=self.connection_pool,
                       log_failure=False)
        except Exception:
            # sys.exc_info() is deleted by LOG.exception().
            exc_info = sys.exc_info()
            LOG.error(_('Exception during message handling'),
                      exc_info=exc_info)
            ctxt.reply(None, exc_info, connection_pool=self.connection_pool)


class MulticallProxyWaiter(object):
    def __init__(self, conf, msg_id, timeout, connection_pool):
        self._msg_id = msg_id
        self._timeout = timeout or conf.rpc_response_timeout
        self._reply_proxy = connection_pool.reply_proxy
        self._done = False
        self._got_ending = False
        self._conf = conf
        self._dataqueue = queue.LightQueue()
        # Add this caller to the reply proxy's call_waiters
        self._reply_proxy.add_call_waiter(self, self._msg_id)
        self.msg_id_cache = _MsgIdCache()

    def put(self, data):
        self._dataqueue.put(data)

    def done(self):
        if self._done:
            return
        self._done = True
        # Remove this caller from reply proxy's call_waiters
        self._reply_proxy.del_call_waiter(self._msg_id)

    def _process_data(self, data):
        result = None
        self.msg_id_cache.check_duplicate_message(data)
        if data['failure']:
            failure = data['failure']
            result = rpc_common.deserialize_remote_exception(self._conf,
                                                             failure)
        elif data.get('ending', False):
            self._got_ending = True
        else:
            result = data['result']
        return result

    def __iter__(self):
        """Return a result until we get a reply with an 'ending' flag."""
        if self._done:
            raise StopIteration
        while True:
            try:
                data = self._dataqueue.get(timeout=self._timeout)
                result = self._process_data(data)
            except queue.Empty:
                self.done()
                raise rpc_common.Timeout()
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.done()
            if self._got_ending:
                self.done()
                raise StopIteration
            if isinstance(result, Exception):
                self.done()
                raise result
            yield result


def create_connection(conf, new, connection_pool):
    """Create a connection."""
    return ConnectionContext(conf, connection_pool, pooled=not new)


_reply_proxy_create_sem = semaphore.Semaphore()


def multicall(conf, context, topic, msg, timeout, connection_pool):
    """Make a call that returns multiple times."""
    LOG.debug(_('Making synchronous call on %s ...'), topic)
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug(_('MSG_ID is %s') % (msg_id))
    _add_unique_id(msg)
    pack_context(msg, context)

    with _reply_proxy_create_sem:
        if not connection_pool.reply_proxy:
            connection_pool.reply_proxy = ReplyProxy(conf, connection_pool)
    msg.update({'_reply_q': connection_pool.reply_proxy.get_reply_q()})
    wait_msg = MulticallProxyWaiter(conf, msg_id, timeout, connection_pool)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.topic_send(topic, rpc_common.serialize_msg(msg), timeout)
    return wait_msg


def call(conf, context, topic, msg, timeout, connection_pool):
    """Sends a message on a topic and wait for a response."""
    rv = multicall(conf, context, topic, msg, timeout, connection_pool)
    # NOTE(vish): return the last result from the multicall
    rv = list(rv)
    if not rv:
        return
    return rv[-1]


def cast(conf, context, topic, msg, connection_pool):
    """Sends a message on a topic without waiting for a response."""
    LOG.debug(_('Making asynchronous cast on %s...'), topic)
    _add_unique_id(msg)
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.topic_send(topic, rpc_common.serialize_msg(msg))


def fanout_cast(conf, context, topic, msg, connection_pool):
    """Sends a message on a fanout exchange without waiting for a response."""
    LOG.debug(_('Making asynchronous fanout cast...'))
    _add_unique_id(msg)
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.fanout_send(topic, rpc_common.serialize_msg(msg))


def cast_to_server(conf, context, server_params, topic, msg, connection_pool):
    """Sends a message on a topic to a specific server."""
    _add_unique_id(msg)
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool, pooled=False,
                           server_params=server_params) as conn:
        conn.topic_send(topic, rpc_common.serialize_msg(msg))


def fanout_cast_to_server(conf, context, server_params, topic, msg,
                          connection_pool):
    """Sends a message on a fanout exchange to a specific server."""
    _add_unique_id(msg)
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool, pooled=False,
                           server_params=server_params) as conn:
        conn.fanout_send(topic, rpc_common.serialize_msg(msg))


def notify(conf, context, topic, msg, connection_pool, envelope):
    """Sends a notification event on a topic."""
    LOG.debug(_('Sending %(event_type)s on %(topic)s'),
              dict(event_type=msg.get('event_type'),
                   topic=topic))
    _add_unique_id(msg)
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        if envelope:
            msg = rpc_common.serialize_msg(msg)
        conn.notify_send(topic, msg)


def cleanup(connection_pool):
    if connection_pool:
        connection_pool.empty()


def get_control_exchange(conf):
    return conf.control_exchange

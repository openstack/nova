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
Shared code between AMQP based nova.rpc implementations.

The code in this module is shared between the rpc implemenations based on AMQP.
Specifically, this includes impl_kombu and impl_qpid.  impl_carrot also uses
AMQP, but is deprecated and predates this code.
"""

import inspect
import logging
import sys
import uuid

from eventlet import greenpool
from eventlet import pools
from eventlet import semaphore

from nova.openstack.common import excutils
from nova.openstack.common import local
import nova.rpc.common as rpc_common


LOG = logging.getLogger(__name__)


class Pool(pools.Pool):
    """Class that implements a Pool of Connections."""
    def __init__(self, conf, connection_cls, *args, **kwargs):
        self.connection_cls = connection_cls
        self.conf = conf
        kwargs.setdefault("max_size", self.conf.rpc_conn_pool_size)
        kwargs.setdefault("order_as_stack", True)
        super(Pool, self).__init__(*args, **kwargs)

    # TODO(comstud): Timeout connections not used in a while
    def create(self):
        LOG.debug('Pool creating new connection')
        return self.connection_cls(self.conf)

    def empty(self):
        while self.free_items:
            self.get().close()


_pool_create_sem = semaphore.Semaphore()


def get_connection_pool(conf, connection_cls):
    with _pool_create_sem:
        # Make sure only one thread tries to create the connection pool.
        if not connection_cls.pool:
            connection_cls.pool = Pool(conf, connection_cls)
    return connection_cls.pool


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

    def __init__(self, conf, connection_pool, pooled=True, server_params=None):
        """Create a new connection, or get one from the pool"""
        self.connection = None
        self.conf = conf
        self.connection_pool = connection_pool
        if pooled:
            self.connection = connection_pool.get()
        else:
            self.connection = connection_pool.connection_cls(conf,
                    server_params=server_params)
        self.pooled = pooled

    def __enter__(self):
        """When with ConnectionContext() is used, return self"""
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

    def consume_in_thread(self):
        self.connection.consume_in_thread()

    def __getattr__(self, key):
        """Proxy all other calls to the Connection instance"""
        if self.connection:
            return getattr(self.connection, key)
        else:
            raise rpc_common.InvalidRPCConnectionReuse()


def msg_reply(conf, msg_id, connection_pool, reply=None, failure=None,
              ending=False):
    """Sends a reply or an error on the channel signified by msg_id.

    Failure should be a sys.exc_info() tuple.

    """
    with ConnectionContext(conf, connection_pool) as conn:
        if failure:
            failure = rpc_common.serialize_remote_exception(failure)

        try:
            msg = {'result': reply, 'failure': failure}
        except TypeError:
            msg = {'result': dict((k, repr(v))
                            for k, v in reply.__dict__.iteritems()),
                    'failure': failure}
        if ending:
            msg['ending'] = True
        conn.direct_send(msg_id, msg)


class RpcContext(rpc_common.CommonRpcContext):
    """Context that supports replying to a rpc.call"""
    def __init__(self, **kwargs):
        self.msg_id = kwargs.pop('msg_id', None)
        self.conf = kwargs.pop('conf')
        super(RpcContext, self).__init__(**kwargs)

    def reply(self, reply=None, failure=None, ending=False,
              connection_pool=None):
        if self.msg_id:
            msg_reply(self.conf, self.msg_id, connection_pool, reply, failure,
                      ending)
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
    context_d = dict([('_context_%s' % key, value)
                      for (key, value) in context.to_dict().iteritems()])
    msg.update(context_d)


class ProxyCallback(object):
    """Calls methods on a proxy object based on method and args."""

    def __init__(self, conf, proxy, connection_pool):
        self.proxy = proxy
        self.pool = greenpool.GreenPool(conf.rpc_thread_pool_size)
        self.connection_pool = connection_pool
        self.conf = conf

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
        ctxt = unpack_context(self.conf, message_data)
        method = message_data.get('method')
        args = message_data.get('args', {})
        version = message_data.get('version', None)
        if not method:
            LOG.warn(_('no method for message: %s') % message_data)
            ctxt.reply(_('No method for message: %s') % message_data,
                       connection_pool=self.connection_pool)
            return
        self.pool.spawn_n(self._process_data, ctxt, version, method, args)

    def _process_data(self, ctxt, version, method, args):
        """Process a message in a new thread.

        If the proxy object we have has a dispatch method
        (see rpc.dispatcher.RpcDispatcher), pass it the version,
        method, and args and let it dispatch as appropriate.  If not, use
        the old behavior of magically calling the specified method on the
        proxy we have here.
        """
        ctxt.update_store()
        try:
            rval = self.proxy.dispatch(ctxt, version, method, **args)
            # Check if the result was a generator
            if inspect.isgenerator(rval):
                for x in rval:
                    ctxt.reply(x, None, connection_pool=self.connection_pool)
            else:
                ctxt.reply(rval, None, connection_pool=self.connection_pool)
            # This final None tells multicall that it is done.
            ctxt.reply(ending=True, connection_pool=self.connection_pool)
        except Exception as e:
            LOG.exception('Exception during message handling')
            ctxt.reply(None, sys.exc_info(),
                       connection_pool=self.connection_pool)


class MulticallWaiter(object):
    def __init__(self, conf, connection, timeout):
        self._connection = connection
        self._iterator = connection.iterconsume(
                                timeout=timeout or conf.rpc_response_timeout)
        self._result = None
        self._done = False
        self._got_ending = False
        self._conf = conf

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
            failure = data['failure']
            self._result = rpc_common.deserialize_remote_exception(self._conf,
                    failure)

        elif data.get('ending', False):
            self._got_ending = True
        else:
            self._result = data['result']

    def __iter__(self):
        """Return a result until we get a 'None' response from consumer"""
        if self._done:
            raise StopIteration
        while True:
            try:
                self._iterator.next()
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.done()
            if self._got_ending:
                self.done()
                raise StopIteration
            result = self._result
            if isinstance(result, Exception):
                self.done()
                raise result
            yield result


def create_connection(conf, new, connection_pool):
    """Create a connection"""
    return ConnectionContext(conf, connection_pool, pooled=not new)


def multicall(conf, context, topic, msg, timeout, connection_pool):
    """Make a call that returns multiple times."""
    # Can't use 'with' for multicall, as it returns an iterator
    # that will continue to use the connection.  When it's done,
    # connection.close() will get called which will put it back into
    # the pool
    LOG.debug(_('Making asynchronous call on %s ...'), topic)
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug(_('MSG_ID is %s') % (msg_id))
    pack_context(msg, context)

    conn = ConnectionContext(conf, connection_pool)
    wait_msg = MulticallWaiter(conf, conn, timeout)
    conn.declare_direct_consumer(msg_id, wait_msg)
    conn.topic_send(topic, msg)
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
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.topic_send(topic, msg)


def fanout_cast(conf, context, topic, msg, connection_pool):
    """Sends a message on a fanout exchange without waiting for a response."""
    LOG.debug(_('Making asynchronous fanout cast...'))
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.fanout_send(topic, msg)


def cast_to_server(conf, context, server_params, topic, msg, connection_pool):
    """Sends a message on a topic to a specific server."""
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool, pooled=False,
            server_params=server_params) as conn:
        conn.topic_send(topic, msg)


def fanout_cast_to_server(conf, context, server_params, topic, msg,
        connection_pool):
    """Sends a message on a fanout exchange to a specific server."""
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool, pooled=False,
            server_params=server_params) as conn:
        conn.fanout_send(topic, msg)


def notify(conf, context, topic, msg, connection_pool):
    """Sends a notification event on a topic."""
    event_type = msg.get('event_type')
    LOG.debug(_('Sending %(event_type)s on %(topic)s'), locals())
    pack_context(msg, context)
    with ConnectionContext(conf, connection_pool) as conn:
        conn.notify_send(topic, msg)


def cleanup(connection_pool):
    if connection_pool:
        connection_pool.empty()

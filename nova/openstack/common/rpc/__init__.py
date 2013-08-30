# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2011 Red Hat, Inc.
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
A remote procedure call (rpc) abstraction.

For some wrappers that add message versioning to rpc, see:
    rpc.dispatcher
    rpc.proxy
"""

import inspect

from oslo.config import cfg

from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import importutils
from nova.openstack.common import local
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


rpc_opts = [
    cfg.StrOpt('rpc_backend',
               default='%s.impl_kombu' % __package__,
               help="The messaging module to use, defaults to kombu."),
    cfg.IntOpt('rpc_thread_pool_size',
               default=64,
               help='Size of RPC thread pool'),
    cfg.IntOpt('rpc_conn_pool_size',
               default=30,
               help='Size of RPC connection pool'),
    cfg.IntOpt('rpc_response_timeout',
               default=60,
               help='Seconds to wait for a response from call or multicall'),
    cfg.IntOpt('rpc_cast_timeout',
               default=30,
               help='Seconds to wait before a cast expires (TTL). '
                    'Only supported by impl_zmq.'),
    cfg.ListOpt('allowed_rpc_exception_modules',
                default=['nova.exception',
                         'cinder.exception',
                         'exceptions',
                         ],
                help='Modules of exceptions that are permitted to be recreated'
                     'upon receiving exception data from an rpc call.'),
    cfg.BoolOpt('fake_rabbit',
                default=False,
                help='If passed, use a fake RabbitMQ provider'),
    cfg.StrOpt('control_exchange',
               default='openstack',
               help='AMQP exchange to connect to if using RabbitMQ or Qpid'),
]

CONF = cfg.CONF
CONF.register_opts(rpc_opts)


def set_defaults(control_exchange):
    cfg.set_defaults(rpc_opts,
                     control_exchange=control_exchange)


def create_connection(new=True):
    """Create a connection to the message bus used for rpc.

    For some example usage of creating a connection and some consumers on that
    connection, see nova.service.

    :param new: Whether or not to create a new connection.  A new connection
                will be created by default.  If new is False, the
                implementation is free to return an existing connection from a
                pool.

    :returns: An instance of openstack.common.rpc.common.Connection
    """
    return _get_impl().create_connection(CONF, new=new)


def _check_for_lock():
    if not CONF.debug:
        return None

    if ((hasattr(local.strong_store, 'locks_held')
         and local.strong_store.locks_held)):
        stack = ' :: '.join([frame[3] for frame in inspect.stack()])
        LOG.warn(_('A RPC is being made while holding a lock. The locks '
                   'currently held are %(locks)s. This is probably a bug. '
                   'Please report it. Include the following: [%(stack)s].'),
                 {'locks': local.strong_store.locks_held,
                  'stack': stack})
        return True

    return False


def call(context, topic, msg, timeout=None, check_for_lock=False):
    """Invoke a remote method that returns something.

    :param context: Information that identifies the user that has made this
                    request.
    :param topic: The topic to send the rpc message to.  This correlates to the
                  topic argument of
                  openstack.common.rpc.common.Connection.create_consumer()
                  and only applies when the consumer was created with
                  fanout=False.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }
    :param timeout: int, number of seconds to use for a response timeout.
                    If set, this overrides the rpc_response_timeout option.
    :param check_for_lock: if True, a warning is emitted if a RPC call is made
                    with a lock held.

    :returns: A dict from the remote method.

    :raises: openstack.common.rpc.common.Timeout if a complete response
             is not received before the timeout is reached.
    """
    if check_for_lock:
        _check_for_lock()
    return _get_impl().call(CONF, context, topic, msg, timeout)


def cast(context, topic, msg):
    """Invoke a remote method that does not return anything.

    :param context: Information that identifies the user that has made this
                    request.
    :param topic: The topic to send the rpc message to.  This correlates to the
                  topic argument of
                  openstack.common.rpc.common.Connection.create_consumer()
                  and only applies when the consumer was created with
                  fanout=False.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }

    :returns: None
    """
    return _get_impl().cast(CONF, context, topic, msg)


def fanout_cast(context, topic, msg):
    """Broadcast a remote method invocation with no return.

    This method will get invoked on all consumers that were set up with this
    topic name and fanout=True.

    :param context: Information that identifies the user that has made this
                    request.
    :param topic: The topic to send the rpc message to.  This correlates to the
                  topic argument of
                  openstack.common.rpc.common.Connection.create_consumer()
                  and only applies when the consumer was created with
                  fanout=True.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }

    :returns: None
    """
    return _get_impl().fanout_cast(CONF, context, topic, msg)


def multicall(context, topic, msg, timeout=None, check_for_lock=False):
    """Invoke a remote method and get back an iterator.

    In this case, the remote method will be returning multiple values in
    separate messages, so the return values can be processed as the come in via
    an iterator.

    :param context: Information that identifies the user that has made this
                    request.
    :param topic: The topic to send the rpc message to.  This correlates to the
                  topic argument of
                  openstack.common.rpc.common.Connection.create_consumer()
                  and only applies when the consumer was created with
                  fanout=False.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }
    :param timeout: int, number of seconds to use for a response timeout.
                    If set, this overrides the rpc_response_timeout option.
    :param check_for_lock: if True, a warning is emitted if a RPC call is made
                    with a lock held.

    :returns: An iterator.  The iterator will yield a tuple (N, X) where N is
              an index that starts at 0 and increases by one for each value
              returned and X is the Nth value that was returned by the remote
              method.

    :raises: openstack.common.rpc.common.Timeout if a complete response
             is not received before the timeout is reached.
    """
    if check_for_lock:
        _check_for_lock()
    return _get_impl().multicall(CONF, context, topic, msg, timeout)


def notify(context, topic, msg, envelope=False):
    """Send notification event.

    :param context: Information that identifies the user that has made this
                    request.
    :param topic: The topic to send the notification to.
    :param msg: This is a dict of content of event.
    :param envelope: Set to True to enable message envelope for notifications.

    :returns: None
    """
    return _get_impl().notify(cfg.CONF, context, topic, msg, envelope)


def cleanup():
    """Clean up resoruces in use by implementation.

    Clean up any resources that have been allocated by the RPC implementation.
    This is typically open connections to a messaging service.  This function
    would get called before an application using this API exits to allow
    connections to get torn down cleanly.

    :returns: None
    """
    return _get_impl().cleanup()


def cast_to_server(context, server_params, topic, msg):
    """Invoke a remote method that does not return anything.

    :param context: Information that identifies the user that has made this
                    request.
    :param server_params: Connection information
    :param topic: The topic to send the notification to.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }

    :returns: None
    """
    return _get_impl().cast_to_server(CONF, context, server_params, topic,
                                      msg)


def fanout_cast_to_server(context, server_params, topic, msg):
    """Broadcast to a remote method invocation with no return.

    :param context: Information that identifies the user that has made this
                    request.
    :param server_params: Connection information
    :param topic: The topic to send the notification to.
    :param msg: This is a dict in the form { "method" : "method_to_invoke",
                                             "args" : dict_of_kwargs }

    :returns: None
    """
    return _get_impl().fanout_cast_to_server(CONF, context, server_params,
                                             topic, msg)


def queue_get_for(context, topic, host):
    """Get a queue name for a given topic + host.

    This function only works if this naming convention is followed on the
    consumer side, as well.  For example, in nova, every instance of the
    nova-foo service calls create_consumer() for two topics:

        foo
        foo.<host>

    Messages sent to the 'foo' topic are distributed to exactly one instance of
    the nova-foo service.  The services are chosen in a round-robin fashion.
    Messages sent to the 'foo.<host>' topic are sent to the nova-foo service on
    <host>.
    """
    return '%s.%s' % (topic, host) if host else topic


_RPCIMPL = None


def _get_impl():
    """Delay import of rpc_backend until configuration is loaded."""
    global _RPCIMPL
    if _RPCIMPL is None:
        try:
            _RPCIMPL = importutils.import_module(CONF.rpc_backend)
        except ImportError:
            # For backwards compatibility with older oslo.config.
            impl = CONF.rpc_backend.replace('nova.rpc',
                                            'nova.openstack.common.rpc')
            _RPCIMPL = importutils.import_module(impl)
    return _RPCIMPL

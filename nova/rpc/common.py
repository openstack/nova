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

import copy

from nova.common import cfg
from nova import exception
from nova import flags
from nova import log as logging


LOG = logging.getLogger('nova.rpc')

rpc_opts = [
    cfg.IntOpt('rpc_thread_pool_size',
               default=1024,
               help='Size of RPC thread pool'),
    cfg.IntOpt('rpc_conn_pool_size',
               default=30,
               help='Size of RPC connection pool'),
    cfg.IntOpt('rpc_response_timeout',
               default=3600,
               help='Seconds to wait for a response from call or multicall'),
    ]

flags.FLAGS.add_options(rpc_opts)


class RemoteError(exception.NovaException):
    """Signifies that a remote class has raised an exception.

    Contains a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevant info.

    """
    message = _("Remote error: %(exc_type)s %(value)s\n%(traceback)s.")

    def __init__(self, exc_type=None, value=None, traceback=None):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__(exc_type=exc_type,
                                          value=value,
                                          traceback=traceback)


class Timeout(exception.NovaException):
    """Signifies that a timeout has occurred.

    This exception is raised if the rpc_response_timeout is reached while
    waiting for a response from the remote side.
    """
    message = _("Timeout while waiting on RPC response.")


class Connection(object):
    """A connection, returned by rpc.create_connection().

    This class represents a connection to the message bus used for rpc.
    An instance of this class should never be created by users of the rpc API.
    Use rpc.create_connection() instead.
    """
    def close(self):
        """Close the connection.

        This method must be called when the connection will no longer be used.
        It will ensure that any resources associated with the connection, such
        as a network connection, and cleaned up.
        """
        raise NotImplementedError()

    def create_consumer(self, topic, proxy, fanout=False):
        """Create a consumer on this connection.

        A consumer is associated with a message queue on the backend message
        bus.  The consumer will read messages from the queue, unpack them, and
        dispatch them to the proxy object.  The contents of the message pulled
        off of the queue will determine which method gets called on the proxy
        object.

        :param topic: This is a name associated with what to consume from.
                      Multiple instances of a service may consume from the same
                      topic. For example, all instances of nova-compute consume
                      from a queue called "compute".  In that case, the
                      messages will get distributed amongst the consumers in a
                      round-robin fashion if fanout=False.  If fanout=True,
                      every consumer associated with this topic will get a
                      copy of every message.
        :param proxy: The object that will handle all incoming messages.
        :param fanout: Whether or not this is a fanout topic.  See the
                       documentation for the topic parameter for some
                       additional comments on this.
        """
        raise NotImplementedError()

    def consume_in_thread(self):
        """Spawn a thread to handle incoming messages.

        Spawn a thread that will be responsible for handling all incoming
        messages for consumers that were set up on this connection.

        Message dispatching inside of this is expected to be implemented in a
        non-blocking manner.  An example implementation would be having this
        thread pull messages in for all of the consumers, but utilize a thread
        pool for dispatching the messages to the proxy objects.
        """
        raise NotImplementedError()


def _safe_log(log_func, msg, msg_data):
    """Sanitizes the msg_data field before logging."""
    SANITIZE = {
                'set_admin_password': ('new_pass',),
                'run_instance': ('admin_password',),
               }
    method = msg_data['method']
    if method in SANITIZE:
        msg_data = copy.deepcopy(msg_data)
        args_to_sanitize = SANITIZE[method]
        for arg in args_to_sanitize:
            try:
                msg_data['args'][arg] = "<SANITIZED>"
            except KeyError:
                pass

    return log_func(msg, msg_data)

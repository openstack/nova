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
import sys
import traceback

from oslo.config import cfg
import six

from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import local
from nova.openstack.common import log as logging


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


'''RPC Envelope Version.

This version number applies to the top level structure of messages sent out.
It does *not* apply to the message payload, which must be versioned
independently.  For example, when using rpc APIs, a version number is applied
for changes to the API being exposed over rpc.  This version number is handled
in the rpc proxy and dispatcher modules.

This version number applies to the message envelope that is used in the
serialization done inside the rpc layer.  See serialize_msg() and
deserialize_msg().

The current message format (version 2.0) is very simple.  It is:

    {
        'oslo.version': <RPC Envelope Version as a String>,
        'oslo.message': <Application Message Payload, JSON encoded>
    }

Message format version '1.0' is just considered to be the messages we sent
without a message envelope.

So, the current message envelope just includes the envelope version.  It may
eventually contain additional information, such as a signature for the message
payload.

We will JSON encode the application message payload.  The message envelope,
which includes the JSON encoded application message body, will be passed down
to the messaging libraries as a dict.
'''
_RPC_ENVELOPE_VERSION = '2.0'

_VERSION_KEY = 'oslo.version'
_MESSAGE_KEY = 'oslo.message'

_REMOTE_POSTFIX = '_Remote'


class RPCException(Exception):
    msg_fmt = _("An unknown RPC related exception occurred.")

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if not message:
            try:
                message = self.msg_fmt % kwargs

            except Exception:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))
                # at least get the core message out if something happened
                message = self.msg_fmt

        super(RPCException, self).__init__(message)


class RemoteError(RPCException):
    """Signifies that a remote class has raised an exception.

    Contains a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevant info.

    """
    msg_fmt = _("Remote error: %(exc_type)s %(value)s\n%(traceback)s.")

    def __init__(self, exc_type=None, value=None, traceback=None):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__(exc_type=exc_type,
                                          value=value,
                                          traceback=traceback)


class Timeout(RPCException):
    """Signifies that a timeout has occurred.

    This exception is raised if the rpc_response_timeout is reached while
    waiting for a response from the remote side.
    """
    msg_fmt = _('Timeout while waiting on RPC response - '
                'topic: "%(topic)s", RPC method: "%(method)s" '
                'info: "%(info)s"')

    def __init__(self, info=None, topic=None, method=None):
        """Initiates Timeout object.

        :param info: Extra info to convey to the user
        :param topic: The topic that the rpc call was sent to
        :param rpc_method_name: The name of the rpc method being
                                called
        """
        self.info = info
        self.topic = topic
        self.method = method
        super(Timeout, self).__init__(
            None,
            info=info or _('<unknown>'),
            topic=topic or _('<unknown>'),
            method=method or _('<unknown>'))


class DuplicateMessageError(RPCException):
    msg_fmt = _("Found duplicate message(%(msg_id)s). Skipping it.")


class InvalidRPCConnectionReuse(RPCException):
    msg_fmt = _("Invalid reuse of an RPC connection.")


class UnsupportedRpcVersion(RPCException):
    msg_fmt = _("Specified RPC version, %(version)s, not supported by "
                "this endpoint.")


class UnsupportedRpcEnvelopeVersion(RPCException):
    msg_fmt = _("Specified RPC envelope version, %(version)s, "
                "not supported by this endpoint.")


class RpcVersionCapError(RPCException):
    msg_fmt = _("Specified RPC version cap, %(version_cap)s, is too low")


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

    def create_worker(self, topic, proxy, pool_name):
        """Create a worker on this connection.

        A worker is like a regular consumer of messages directed to a
        topic, except that it is part of a set of such consumers (the
        "pool") which may run in parallel. Every pool of workers will
        receive a given message, but only one worker in the pool will
        be asked to process it. Load is distributed across the members
        of the pool in round-robin fashion.

        :param topic: This is a name associated with what to consume from.
                      Multiple instances of a service may consume from the same
                      topic.
        :param proxy: The object that will handle all incoming messages.
        :param pool_name: String containing the name of the pool of workers
        """
        raise NotImplementedError()

    def join_consumer_pool(self, callback, pool_name, topic, exchange_name):
        """Register as a member of a group of consumers.

        Uses given topic from the specified exchange.
        Exactly one member of a given pool will receive each message.

        A message will be delivered to multiple pools, if more than
        one is created.

        :param callback: Callable to be invoked for each message.
        :type callback: callable accepting one argument
        :param pool_name: The name of the consumer pool.
        :type pool_name: str
        :param topic: The routing topic for desired messages.
        :type topic: str
        :param exchange_name: The name of the message exchange where
                              the client should attach. Defaults to
                              the configured exchange.
        :type exchange_name: str
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
    SANITIZE = ['_context_auth_token', 'auth_token', 'new_pass']

    def _fix_passwords(d):
        """Sanitizes the password fields in the dictionary."""
        for k in d.iterkeys():
            if k.lower().find('password') != -1:
                d[k] = '<SANITIZED>'
            elif k.lower() in SANITIZE:
                d[k] = '<SANITIZED>'
            elif isinstance(d[k], dict):
                _fix_passwords(d[k])
        return d

    return log_func(msg, _fix_passwords(copy.deepcopy(msg_data)))


def serialize_remote_exception(failure_info, log_failure=True):
    """Prepares exception data to be sent over rpc.

    Failure_info should be a sys.exc_info() tuple.

    """
    tb = traceback.format_exception(*failure_info)
    failure = failure_info[1]
    if log_failure:
        LOG.error(_("Returning exception %s to caller"),
                  six.text_type(failure))
        LOG.error(tb)

    kwargs = {}
    if hasattr(failure, 'kwargs'):
        kwargs = failure.kwargs

    # NOTE(matiu): With cells, it's possible to re-raise remote, remote
    # exceptions. Lets turn it back into the original exception type.
    cls_name = str(failure.__class__.__name__)
    mod_name = str(failure.__class__.__module__)
    if (cls_name.endswith(_REMOTE_POSTFIX) and
            mod_name.endswith(_REMOTE_POSTFIX)):
        cls_name = cls_name[:-len(_REMOTE_POSTFIX)]
        mod_name = mod_name[:-len(_REMOTE_POSTFIX)]

    data = {
        'class': cls_name,
        'module': mod_name,
        'message': six.text_type(failure),
        'tb': tb,
        'args': failure.args,
        'kwargs': kwargs
    }

    json_data = jsonutils.dumps(data)

    return json_data


def deserialize_remote_exception(conf, data):
    failure = jsonutils.loads(str(data))

    trace = failure.get('tb', [])
    message = failure.get('message', "") + "\n" + "\n".join(trace)
    name = failure.get('class')
    module = failure.get('module')

    # NOTE(ameade): We DO NOT want to allow just any module to be imported, in
    # order to prevent arbitrary code execution.
    if module not in conf.allowed_rpc_exception_modules:
        return RemoteError(name, failure.get('message'), trace)

    try:
        mod = importutils.import_module(module)
        klass = getattr(mod, name)
        if not issubclass(klass, Exception):
            raise TypeError("Can only deserialize Exceptions")

        failure = klass(*failure.get('args', []), **failure.get('kwargs', {}))
    except (AttributeError, TypeError, ImportError):
        return RemoteError(name, failure.get('message'), trace)

    ex_type = type(failure)
    str_override = lambda self: message
    new_ex_type = type(ex_type.__name__ + _REMOTE_POSTFIX, (ex_type,),
                       {'__str__': str_override, '__unicode__': str_override})
    new_ex_type.__module__ = '%s%s' % (module, _REMOTE_POSTFIX)
    try:
        # NOTE(ameade): Dynamically create a new exception type and swap it in
        # as the new type for the exception. This only works on user defined
        # Exceptions and not core python exceptions. This is important because
        # we cannot necessarily change an exception message so we must override
        # the __str__ method.
        failure.__class__ = new_ex_type
    except TypeError:
        # NOTE(ameade): If a core exception then just add the traceback to the
        # first exception argument.
        failure.args = (message,) + failure.args[1:]
    return failure


class CommonRpcContext(object):
    def __init__(self, **kwargs):
        self.values = kwargs

    def __getattr__(self, key):
        try:
            return self.values[key]
        except KeyError:
            raise AttributeError(key)

    def to_dict(self):
        return copy.deepcopy(self.values)

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    def deepcopy(self):
        return self.from_dict(self.to_dict())

    def update_store(self):
        local.store.context = self

    def elevated(self, read_deleted=None, overwrite=False):
        """Return a version of this context with admin flag set."""
        # TODO(russellb) This method is a bit of a nova-ism.  It makes
        # some assumptions about the data in the request context sent
        # across rpc, while the rest of this class does not.  We could get
        # rid of this if we changed the nova code that uses this to
        # convert the RpcContext back to its native RequestContext doing
        # something like nova.context.RequestContext.from_dict(ctxt.to_dict())

        context = self.deepcopy()
        context.values['is_admin'] = True

        context.values.setdefault('roles', [])

        if 'admin' not in context.values['roles']:
            context.values['roles'].append('admin')

        if read_deleted is not None:
            context.values['read_deleted'] = read_deleted

        return context


class ClientException(Exception):
    """Encapsulates actual exception expected to be hit by a RPC proxy object.

    Merely instantiating it records the current exception information, which
    will be passed back to the RPC client without exceptional logging.
    """
    def __init__(self):
        self._exc_info = sys.exc_info()


def catch_client_exception(exceptions, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if type(e) in exceptions:
            raise ClientException()
        else:
            raise


def client_exceptions(*exceptions):
    """Decorator for manager methods that raise expected exceptions.

    Marking a Manager method with this decorator allows the declaration
    of expected exceptions that the RPC layer should not consider fatal,
    and not log as if they were generated in a real error scenario. Note
    that this will cause listed exceptions to be wrapped in a
    ClientException, which is used internally by the RPC layer.
    """
    def outer(func):
        def inner(*args, **kwargs):
            return catch_client_exception(exceptions, func, *args, **kwargs)
        return inner
    return outer


def version_is_compatible(imp_version, version):
    """Determine whether versions are compatible.

    :param imp_version: The version implemented
    :param version: The version requested by an incoming message.
    """
    version_parts = version.split('.')
    imp_version_parts = imp_version.split('.')
    try:
        rev = version_parts[2]
    except IndexError:
        rev = 0
    try:
        imp_rev = imp_version_parts[2]
    except IndexError:
        imp_rev = 0

    if int(version_parts[0]) != int(imp_version_parts[0]):  # Major
        return False
    if int(version_parts[1]) > int(imp_version_parts[1]):  # Minor
        return False
    if (int(version_parts[1]) == int(imp_version_parts[1]) and
            int(rev) > int(imp_rev)):  # Revision
        return False
    return True


def serialize_msg(raw_msg):
    # NOTE(russellb) See the docstring for _RPC_ENVELOPE_VERSION for more
    # information about this format.
    msg = {_VERSION_KEY: _RPC_ENVELOPE_VERSION,
           _MESSAGE_KEY: jsonutils.dumps(raw_msg)}

    return msg


def deserialize_msg(msg):
    # NOTE(russellb): Hang on to your hats, this road is about to
    # get a little bumpy.
    #
    # Robustness Principle:
    #    "Be strict in what you send, liberal in what you accept."
    #
    # At this point we have to do a bit of guessing about what it
    # is we just received.  Here is the set of possibilities:
    #
    # 1) We received a dict.  This could be 2 things:
    #
    #   a) Inspect it to see if it looks like a standard message envelope.
    #      If so, great!
    #
    #   b) If it doesn't look like a standard message envelope, it could either
    #      be a notification, or a message from before we added a message
    #      envelope (referred to as version 1.0).
    #      Just return the message as-is.
    #
    # 2) It's any other non-dict type.  Just return it and hope for the best.
    #    This case covers return values from rpc.call() from before message
    #    envelopes were used.  (messages to call a method were always a dict)

    if not isinstance(msg, dict):
        # See #2 above.
        return msg

    base_envelope_keys = (_VERSION_KEY, _MESSAGE_KEY)
    if not all(map(lambda key: key in msg, base_envelope_keys)):
        #  See #1.b above.
        return msg

    # At this point we think we have the message envelope
    # format we were expecting. (#1.a above)

    if not version_is_compatible(_RPC_ENVELOPE_VERSION, msg[_VERSION_KEY]):
        raise UnsupportedRpcEnvelopeVersion(version=msg[_VERSION_KEY])

    raw_msg = jsonutils.loads(msg[_MESSAGE_KEY])

    return raw_msg

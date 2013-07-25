# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012-2013 Red Hat, Inc.
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
A helper class for proxy objects to remote APIs.

For more information about rpc API version numbers, see:
    rpc/dispatcher.py
"""


from nova.openstack.common import rpc
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common.rpc import serializer as rpc_serializer


class RpcProxy(object):
    """A helper class for rpc clients.

    This class is a wrapper around the RPC client API.  It allows you to
    specify the topic and API version in a single place.  This is intended to
    be used as a base class for a class that implements the client side of an
    rpc API.
    """

    # The default namespace, which can be overriden in a subclass.
    RPC_API_NAMESPACE = None

    def __init__(self, topic, default_version, version_cap=None,
                 serializer=None):
        """Initialize an RpcProxy.

        :param topic: The topic to use for all messages.
        :param default_version: The default API version to request in all
               outgoing messages.  This can be overridden on a per-message
               basis.
        :param version_cap: Optionally cap the maximum version used for sent
               messages.
        :param serializer: Optionaly (de-)serialize entities with a
               provided helper.
        """
        self.topic = topic
        self.default_version = default_version
        self.version_cap = version_cap
        if serializer is None:
            serializer = rpc_serializer.NoOpSerializer()
        self.serializer = serializer
        super(RpcProxy, self).__init__()

    def _set_version(self, msg, vers):
        """Helper method to set the version in a message.

        :param msg: The message having a version added to it.
        :param vers: The version number to add to the message.
        """
        v = vers if vers else self.default_version
        if (self.version_cap and not
                rpc_common.version_is_compatible(self.version_cap, v)):
            raise rpc_common.RpcVersionCapError(version_cap=self.version_cap)
        msg['version'] = v

    def _get_topic(self, topic):
        """Return the topic to use for a message."""
        return topic if topic else self.topic

    def can_send_version(self, version):
        """Check to see if a version is compatible with the version cap."""
        return (not self.version_cap or
                rpc_common.version_is_compatible(self.version_cap, version))

    @staticmethod
    def make_namespaced_msg(method, namespace, **kwargs):
        return {'method': method, 'namespace': namespace, 'args': kwargs}

    def make_msg(self, method, **kwargs):
        return self.make_namespaced_msg(method, self.RPC_API_NAMESPACE,
                                        **kwargs)

    def _serialize_msg_args(self, context, kwargs):
        """Helper method called to serialize message arguments.

        This calls our serializer on each argument, returning a new
        set of args that have been serialized.

        :param context: The request context
        :param kwargs: The arguments to serialize
        :returns: A new set of serialized arguments
        """
        new_kwargs = dict()
        for argname, arg in kwargs.iteritems():
            new_kwargs[argname] = self.serializer.serialize_entity(context,
                                                                   arg)
        return new_kwargs

    def call(self, context, msg, topic=None, version=None, timeout=None):
        """rpc.call() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.
        :param timeout: (Optional) A timeout to use when waiting for the
               response.  If no timeout is specified, a default timeout will be
               used that is usually sufficient.

        :returns: The return value from the remote method.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        real_topic = self._get_topic(topic)
        try:
            result = rpc.call(context, real_topic, msg, timeout)
            return self.serializer.deserialize_entity(context, result)
        except rpc.common.Timeout as exc:
            raise rpc.common.Timeout(
                exc.info, real_topic, msg.get('method'))

    def multicall(self, context, msg, topic=None, version=None, timeout=None):
        """rpc.multicall() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.
        :param timeout: (Optional) A timeout to use when waiting for the
               response.  If no timeout is specified, a default timeout will be
               used that is usually sufficient.

        :returns: An iterator that lets you process each of the returned values
                  from the remote method as they arrive.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        real_topic = self._get_topic(topic)
        try:
            result = rpc.multicall(context, real_topic, msg, timeout)
            return self.serializer.deserialize_entity(context, result)
        except rpc.common.Timeout as exc:
            raise rpc.common.Timeout(
                exc.info, real_topic, msg.get('method'))

    def cast(self, context, msg, topic=None, version=None):
        """rpc.cast() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: None.  rpc.cast() does not wait on any return value from the
                  remote method.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        rpc.cast(context, self._get_topic(topic), msg)

    def fanout_cast(self, context, msg, topic=None, version=None):
        """rpc.fanout_cast() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: None.  rpc.fanout_cast() does not wait on any return value
                  from the remote method.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        rpc.fanout_cast(context, self._get_topic(topic), msg)

    def cast_to_server(self, context, server_params, msg, topic=None,
                       version=None):
        """rpc.cast_to_server() a remote method.

        :param context: The request context
        :param server_params: Server parameters.  See rpc.cast_to_server() for
               details.
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: None.  rpc.cast_to_server() does not wait on any
                  return values.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        rpc.cast_to_server(context, server_params, self._get_topic(topic), msg)

    def fanout_cast_to_server(self, context, server_params, msg, topic=None,
                              version=None):
        """rpc.fanout_cast_to_server() a remote method.

        :param context: The request context
        :param server_params: Server parameters.  See rpc.cast_to_server() for
               details.
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: None.  rpc.fanout_cast_to_server() does not wait on any
                  return values.
        """
        self._set_version(msg, version)
        msg['args'] = self._serialize_msg_args(context, msg['args'])
        rpc.fanout_cast_to_server(context, server_params,
                                  self._get_topic(topic), msg)

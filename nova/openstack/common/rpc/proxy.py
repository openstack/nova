# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
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


class RpcProxy(object):
    """A helper class for rpc clients.

    This class is a wrapper around the RPC client API.  It allows you to
    specify the topic and API version in a single place.  This is intended to
    be used as a base class for a class that implements the client side of an
    rpc API.
    """

    def __init__(self, topic, default_version):
        """Initialize an RpcProxy.

        :param topic: The topic to use for all messages.
        :param default_version: The default API version to request in all
               outgoing messages.  This can be overridden on a per-message
               basis.
        """
        self.topic = topic
        self.default_version = default_version
        super(RpcProxy, self).__init__()

    def _set_version(self, msg, vers):
        """Helper method to set the version in a message.

        :param msg: The message having a version added to it.
        :param vers: The version number to add to the message.
        """
        msg['version'] = vers if vers else self.default_version

    def _get_topic(self, topic):
        """Return the topic to use for a message."""
        return topic if topic else self.topic

    @staticmethod
    def make_msg(method, **kwargs):
        return {'method': method, 'args': kwargs}

    def call(self, context, msg, topic=None, version=None, timeout=None):
        """rpc.call() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param timeout: (Optional) A timeout to use when waiting for the
               response.  If no timeout is specified, a default timeout will be
               used that is usually sufficient.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: The return value from the remote method.
        """
        self._set_version(msg, version)
        return rpc.call(context, self._get_topic(topic), msg, timeout)

    def multicall(self, context, msg, topic=None, version=None, timeout=None):
        """rpc.multicall() a remote method.

        :param context: The request context
        :param msg: The message to send, including the method and args.
        :param topic: Override the topic for this message.
        :param timeout: (Optional) A timeout to use when waiting for the
               response.  If no timeout is specified, a default timeout will be
               used that is usually sufficient.
        :param version: (Optional) Override the requested API version in this
               message.

        :returns: An iterator that lets you process each of the returned values
                  from the remote method as they arrive.
        """
        self._set_version(msg, version)
        return rpc.multicall(context, self._get_topic(topic), msg, timeout)

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
        rpc.fanout_cast_to_server(context, server_params,
                                  self._get_topic(topic), msg)

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
Code for rpc message dispatching.

Messages that come in have a version number associated with them.  RPC API
version numbers are in the form:

    Major.Minor

For a given message with version X.Y, the receiver must be marked as able to
handle messages of version A.B, where:

    A = X

    B >= Y

The Major version number would be incremented for an almost completely new API.
The Minor version number would be incremented for backwards compatible changes
to an existing API.  A backwards compatible change could be something like
adding a new method, adding an argument to an existing method (but not
requiring it), or changing the type for an existing argument (but still
handling the old type as well).

The conversion over to a versioned API must be done on both the client side and
server side of the API at the same time.  However, as the code stands today,
there can be both versioned and unversioned APIs implemented in the same code
base.

EXAMPLES
========

Nova was the first project to use versioned rpc APIs.  Consider the compute rpc
API as an example.  The client side is in nova/compute/rpcapi.py and the server
side is in nova/compute/manager.py.


Example 1) Adding a new method.
-------------------------------

Adding a new method is a backwards compatible change.  It should be added to
nova/compute/manager.py, and RPC_API_VERSION should be bumped from X.Y to
X.Y+1.  On the client side, the new method in nova/compute/rpcapi.py should
have a specific version specified to indicate the minimum API version that must
be implemented for the method to be supported.  For example::

    def get_host_uptime(self, ctxt, host):
        topic = _compute_topic(self.topic, ctxt, host, None)
        return self.call(ctxt, self.make_msg('get_host_uptime'), topic,
                version='1.1')

In this case, version '1.1' is the first version that supported the
get_host_uptime() method.


Example 2) Adding a new parameter.
----------------------------------

Adding a new parameter to an rpc method can be made backwards compatible.  The
RPC_API_VERSION on the server side (nova/compute/manager.py) should be bumped.
The implementation of the method must not expect the parameter to be present.::

    def some_remote_method(self, arg1, arg2, newarg=None):
        # The code needs to deal with newarg=None for cases
        # where an older client sends a message without it.
        pass

On the client side, the same changes should be made as in example 1.  The
minimum version that supports the new parameter should be specified.
"""

from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common.rpc import serializer as rpc_serializer


class RpcDispatcher(object):
    """Dispatch rpc messages according to the requested API version.

    This class can be used as the top level 'manager' for a service.  It
    contains a list of underlying managers that have an API_VERSION attribute.
    """

    def __init__(self, callbacks, serializer=None):
        """Initialize the rpc dispatcher.

        :param callbacks: List of proxy objects that are an instance
                          of a class with rpc methods exposed.  Each proxy
                          object should have an RPC_API_VERSION attribute.
        :param serializer: The Serializer object that will be used to
                           deserialize arguments before the method call and
                           to serialize the result after it returns.
        """
        self.callbacks = callbacks
        if serializer is None:
            serializer = rpc_serializer.NoOpSerializer()
        self.serializer = serializer
        super(RpcDispatcher, self).__init__()

    def _deserialize_args(self, context, kwargs):
        """Helper method called to deserialize args before dispatch.

        This calls our serializer on each argument, returning a new set of
        args that have been deserialized.

        :param context: The request context
        :param kwargs: The arguments to be deserialized
        :returns: A new set of deserialized args
        """
        new_kwargs = dict()
        for argname, arg in kwargs.iteritems():
            new_kwargs[argname] = self.serializer.deserialize_entity(context,
                                                                     arg)
        return new_kwargs

    def dispatch(self, ctxt, version, method, namespace, **kwargs):
        """Dispatch a message based on a requested version.

        :param ctxt: The request context
        :param version: The requested API version from the incoming message
        :param method: The method requested to be called by the incoming
                       message.
        :param namespace: The namespace for the requested method.  If None,
                          the dispatcher will look for a method on a callback
                          object with no namespace set.
        :param kwargs: A dict of keyword arguments to be passed to the method.

        :returns: Whatever is returned by the underlying method that gets
                  called.
        """
        if not version:
            version = '1.0'

        had_compatible = False
        for proxyobj in self.callbacks:
            # Check for namespace compatibility
            try:
                cb_namespace = proxyobj.RPC_API_NAMESPACE
            except AttributeError:
                cb_namespace = None

            if namespace != cb_namespace:
                continue

            # Check for version compatibility
            try:
                rpc_api_version = proxyobj.RPC_API_VERSION
            except AttributeError:
                rpc_api_version = '1.0'

            is_compatible = rpc_common.version_is_compatible(rpc_api_version,
                                                             version)
            had_compatible = had_compatible or is_compatible

            if not hasattr(proxyobj, method):
                continue
            if is_compatible:
                kwargs = self._deserialize_args(ctxt, kwargs)
                result = getattr(proxyobj, method)(ctxt, **kwargs)
                return self.serializer.serialize_entity(ctxt, result)

        if had_compatible:
            raise AttributeError("No such RPC function '%s'" % method)
        else:
            raise rpc_common.UnsupportedRpcVersion(version=version)

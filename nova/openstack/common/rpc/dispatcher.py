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
"""

from nova.openstack.common.rpc import common as rpc_common


class RpcDispatcher(object):
    """Dispatch rpc messages according to the requested API version.

    This class can be used as the top level 'manager' for a service.  It
    contains a list of underlying managers that have an API_VERSION attribute.
    """

    def __init__(self, callbacks):
        """Initialize the rpc dispatcher.

        :param callbacks: List of proxy objects that are an instance
                          of a class with rpc methods exposed.  Each proxy
                          object should have an RPC_API_VERSION attribute.
        """
        self.callbacks = callbacks
        super(RpcDispatcher, self).__init__()

    @staticmethod
    def _is_compatible(mversion, version):
        """Determine whether versions are compatible.

        :param mversion: The API version implemented by a callback.
        :param version: The API version requested by an incoming message.
        """
        version_parts = version.split('.')
        mversion_parts = mversion.split('.')
        if int(version_parts[0]) != int(mversion_parts[0]):  # Major
            return False
        if int(version_parts[1]) > int(mversion_parts[1]):  # Minor
            return False
        return True

    def dispatch(self, ctxt, version, method, **kwargs):
        """Dispatch a message based on a requested version.

        :param ctxt: The request context
        :param version: The requested API version from the incoming message
        :param method: The method requested to be called by the incoming
                       message.
        :param kwargs: A dict of keyword arguments to be passed to the method.

        :returns: Whatever is returned by the underlying method that gets
                  called.
        """
        if not version:
            version = '1.0'

        for proxyobj in self.callbacks:
            if hasattr(proxyobj, 'RPC_API_VERSION'):
                rpc_api_version = proxyobj.RPC_API_VERSION
            else:
                rpc_api_version = '1.0'
            if not hasattr(proxyobj, method):
                continue
            if self._is_compatible(rpc_api_version, version):
                return getattr(proxyobj, method)(ctxt, **kwargs)

        raise rpc_common.UnsupportedRpcVersion(version=version)

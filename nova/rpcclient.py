# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat, Inc.
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
A temporary helper which emulates oslo.messaging.rpc.RPCClient.

The most tedious part of porting to oslo.messaging is porting the code which
sub-classes RpcProxy to use RPCClient instead.

This helper method allows us to do that tedious porting as a standalone commit
so that the commit which switches us to oslo.messaging is smaller and easier
to review. This file will be removed as part of that commit.
"""

from nova.openstack.common.rpc import proxy


class RPCClient(object):

    def __init__(self, proxy, namespace=None, server_params=None):
        super(RPCClient, self).__init__()
        self.proxy = proxy
        self.namespace = namespace
        self.server_params = server_params
        self.kwargs = {}
        self.fanout = None

    def prepare(self, **kwargs):
        # Clone ourselves
        ret = self.__class__(self.proxy, self.namespace, self.server_params)
        ret.kwargs.update(self.kwargs)
        ret.fanout = self.fanout

        # Update according to supplied kwargs
        ret.kwargs.update(kwargs)
        server = ret.kwargs.pop('server', None)
        if server:
            ret.kwargs['topic'] = '%s.%s' % (self.proxy.topic, server)
        fanout = ret.kwargs.pop('fanout', None)
        if fanout:
            ret.fanout = True

        return ret

    def _invoke(self, cast_or_call, ctxt, method, **kwargs):
        try:
            msg = self.proxy.make_namespaced_msg(method,
                                                 self.namespace,
                                                 **kwargs)
            return cast_or_call(ctxt, msg, **self.kwargs)
        finally:
            self.kwargs = {}
            self.fanout = None

    def cast(self, ctxt, method, **kwargs):
        if self.server_params:
            def cast_to_server(ctxt, msg, **kwargs):
                if self.fanout:
                    return self.proxy.fanout_cast_to_server(
                        ctxt, self.server_params, msg, **kwargs)
                else:
                    return self.proxy.cast_to_server(
                        ctxt, self.server_params, msg, **kwargs)

            caster = cast_to_server
        else:
            caster = self.proxy.fanout_cast if self.fanout else self.proxy.cast

        self._invoke(caster, ctxt, method, **kwargs)

    def call(self, ctxt, method, **kwargs):
        return self._invoke(self.proxy.call, ctxt, method, **kwargs)

    def can_send_version(self, version):
        return self.proxy.can_send_version(version)


class RpcProxy(proxy.RpcProxy):

    def get_client(self, namespace=None, server_params=None):
        return RPCClient(self,
                         namespace=namespace,
                         server_params=server_params)

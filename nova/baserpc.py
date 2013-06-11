#
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
#

"""
Base RPC client and server common to all services.
"""

from oslo.config import cfg

from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
import nova.openstack.common.rpc.proxy as rpc_proxy


CONF = cfg.CONF
rpcapi_cap_opt = cfg.StrOpt('baseapi',
        default=None,
        help='Set a version cap for messages sent to the base api in any '
             'service')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')

_NAMESPACE = 'baseapi'


class BaseAPI(rpc_proxy.RpcProxy):
    """Client side of the base rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Add get_backdoor_port
    """

    #
    # NOTE(russellb): This is the default minimum version that the server
    # (manager) side must implement unless otherwise specified using a version
    # argument to self.call()/cast()/etc. here.  It should be left as X.0 where
    # X is the current major API version (1.0, 2.0, ...).  For more information
    # about rpc API versioning, see the docs in
    # openstack/common/rpc/dispatcher.py.
    #
    BASE_RPC_API_VERSION = '1.0'

    VERSION_ALIASES = {
        # baseapi was added in havana
    }

    def __init__(self, topic):
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.baseapi,
                                               CONF.upgrade_levels.baseapi)
        super(BaseAPI, self).__init__(topic=topic,
                default_version=self.BASE_RPC_API_VERSION,
                version_cap=version_cap)
        self.namespace = _NAMESPACE

    def ping(self, context, arg, timeout=None):
        arg_p = jsonutils.to_primitive(arg)
        msg = self.make_namespaced_msg('ping', self.namespace, arg=arg_p)
        return self.call(context, msg, timeout=timeout)

    def get_backdoor_port(self, context, host):
        msg = self.make_namespaced_msg('get_backdoor_port', self.namespace)
        return self.call(context, msg,
                         topic=rpc.queue_get_for(context, self.topic, host),
                         version='1.1')


class BaseRPCAPI(object):
    """Server side of the base RPC API."""

    RPC_API_NAMESPACE = _NAMESPACE
    RPC_API_VERSION = '1.1'

    def __init__(self, service_name, backdoor_port):
        self.service_name = service_name
        self.backdoor_port = backdoor_port

    def ping(self, context, arg):
        resp = {'service': self.service_name, 'arg': arg}
        return jsonutils.to_primitive(resp)

    def get_backdoor_port(self, context):
        return self.backdoor_port

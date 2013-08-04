# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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
Client side of the consoleauth RPC API.
"""

from oslo.config import cfg

from nova import rpcclient

CONF = cfg.CONF

rpcapi_cap_opt = cfg.StrOpt('consoleauth',
        help='Set a version cap for messages sent to consoleauth services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')


class ConsoleAuthAPI(rpcclient.RpcProxy):
    '''Client side of the consoleauth rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Added get_backdoor_port()
        1.2 - Added instance_uuid to authorize_console, and
              delete_tokens_for_instance

        ... Grizzly supports message version 1.2.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 1.2.
    '''

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
        'grizzly': '1.2',
    }

    def __init__(self):
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.consoleauth,
                                               CONF.upgrade_levels.consoleauth)
        super(ConsoleAuthAPI, self).__init__(
                topic=CONF.consoleauth_topic,
                default_version=self.BASE_RPC_API_VERSION,
                version_cap=version_cap)
        self.client = self.get_client()

    def authorize_console(self, ctxt, token, console_type, host, port,
                          internal_access_path, instance_uuid=None):
        # The remote side doesn't return anything, but we want to block
        # until it completes.
        cctxt = self.client.prepare(version='1.2')
        return cctxt.call(ctxt,
                          'authorize_console',
                          token=token, console_type=console_type,
                          host=host, port=port,
                          internal_access_path=internal_access_path,
                          instance_uuid=instance_uuid)

    def check_token(self, ctxt, token):
        return self.client.call(ctxt, 'check_token', token=token)

    def delete_tokens_for_instance(self, ctxt, instance_uuid):
        cctxt = self.client.prepare(version='1.2')
        return cctxt.cast(ctxt,
                          'delete_tokens_for_instance',
                          instance_uuid=instance_uuid)

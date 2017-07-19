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
Client side of the consoleauth RPC API.
"""

import oslo_messaging as messaging

import nova.conf
from nova import profiler
from nova import rpc

CONF = nova.conf.CONF
RPC_TOPIC = 'consoleauth'


@profiler.trace_cls("rpc")
class ConsoleAuthAPI(object):
    '''Client side of the consoleauth rpc API.

    API version history:

        * 1.0 - Initial version.
        * 1.1 - Added get_backdoor_port()
        * 1.2 - Added instance_uuid to authorize_console, and
                delete_tokens_for_instance

        ... Grizzly and Havana support message version 1.2.  So, any changes
        to existing methods in 2.x after that point should be done such that
        they can handle the version_cap being set to 1.2.

        * 2.0 - Major API rev for Icehouse

        ... Icehouse and Juno support message version 2.0.  So, any changes to
        existing methods in 2.x after that point should be done such that they
        can handle the version_cap being set to 2.0.

        * 2.1 - Added access_url to authorize_console

        ... Kilo, Liberty, Mitaka, Newton, and Ocata support message version
        2.1. So, any changes to existing methods in 2.x after that point should
        be done such that they can handle the version_cap being set to 2.1.

    '''

    VERSION_ALIASES = {
        'grizzly': '1.2',
        'havana': '1.2',
        'icehouse': '2.0',
        'juno': '2.0',
        'kilo': '2.1',
        'liberty': '2.1',
        'mitaka': '2.1',
        'newton': '2.1',
        'ocata': '2.1',
    }

    def __init__(self):
        super(ConsoleAuthAPI, self).__init__()
        target = messaging.Target(topic=RPC_TOPIC, version='2.1')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.consoleauth,
                                               CONF.upgrade_levels.consoleauth)
        self.client = rpc.get_client(target, version_cap=version_cap)

    def authorize_console(self, ctxt, token, console_type, host, port,
                          internal_access_path, instance_uuid,
                          access_url):
        # The remote side doesn't return anything, but we want to block
        # until it completes.'
        msg_args = dict(token=token, console_type=console_type,
                        host=host, port=port,
                        internal_access_path=internal_access_path,
                        instance_uuid=instance_uuid,
                        access_url=access_url)
        version = '2.1'
        if not self.client.can_send_version('2.1'):
            version = '2.0'
            del msg_args['access_url']

        cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'authorize_console', **msg_args)

    def check_token(self, ctxt, token):
        cctxt = self.client.prepare()
        return cctxt.call(ctxt, 'check_token', token=token)

    def delete_tokens_for_instance(self, ctxt, instance_uuid):
        cctxt = self.client.prepare()
        return cctxt.cast(ctxt,
                          'delete_tokens_for_instance',
                          instance_uuid=instance_uuid)

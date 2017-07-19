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
Client side of the console RPC API.
"""

import oslo_messaging as messaging

import nova.conf
from nova import profiler
from nova import rpc

CONF = nova.conf.CONF
RPC_TOPIC = "console"


@profiler.trace_cls("rpc")
class ConsoleAPI(object):
    '''Client side of the console rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Added get_backdoor_port()

        ... Grizzly and Havana support message version 1.1.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.1.

        2.0 - Major API rev for Icehouse

        ... Icehouse, Juno, Kilo, Liberty, Mitaka, Newton, and Ocata support
        message version 2.0. So, any changes to existing methods in 2.x after
        that point should be done such that they can handle the version_cap
        being set to 2.0.

    '''

    VERSION_ALIASES = {
        'grizzly': '1.1',
        'havana': '1.1',
        'icehouse': '2.0',
        'juno': '2.0',
        'kilo': '2.0',
        'liberty': '2.0',
        'mitaka': '2.0',
        'newton': '2.0',
        'ocata': '2.0',
    }

    def __init__(self, topic=None, server=None):
        super(ConsoleAPI, self).__init__()
        topic = topic if topic else RPC_TOPIC
        target = messaging.Target(topic=topic, server=server, version='2.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.console,
                                               CONF.upgrade_levels.console)
        self.client = rpc.get_client(target, version_cap=version_cap)

    def add_console(self, ctxt, instance_id):
        cctxt = self.client.prepare()
        cctxt.cast(ctxt, 'add_console', instance_id=instance_id)

    def remove_console(self, ctxt, console_id):
        cctxt = self.client.prepare()
        cctxt.cast(ctxt, 'remove_console', console_id=console_id)

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
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
Websocket proxy that is compatible with OpenStack Nova
SPICE HTML5 consoles. Leverages websockify.py by Joel Martin
"""

from __future__ import print_function

import os
import sys

from oslo.config import cfg

from nova import config
from nova.console import websocketproxy

opts = [
    cfg.StrOpt('spicehtml5proxy_host',
               default='0.0.0.0',
               help='Host on which to listen for incoming requests'),
    cfg.IntOpt('spicehtml5proxy_port',
               default=6082,
               help='Port on which to listen for incoming requests'),
    ]

CONF = cfg.CONF
CONF.register_cli_opts(opts)
CONF.import_opt('record', 'nova.cmd.novnc')
CONF.import_opt('daemon', 'nova.cmd.novnc')
CONF.import_opt('ssl_only', 'nova.cmd.novnc')
CONF.import_opt('source_is_ipv6', 'nova.cmd.novnc')
CONF.import_opt('cert', 'nova.cmd.novnc')
CONF.import_opt('key', 'nova.cmd.novnc')
CONF.import_opt('web', 'nova.cmd.novnc')


def main():
    # Setup flags
    config.parse_args(sys.argv)

    if CONF.ssl_only and not os.path.exists(CONF.cert):
        print("SSL only and %s not found." % CONF.cert)
        return(-1)

    # Check to see if spice html/js/css files are present
    if not os.path.exists(CONF.web):
        print("Can not find spice html/js/css files at %s." % CONF.web)
        return(-1)

    # Create and start the NovaWebSockets proxy
    server = websocketproxy.NovaWebSocketProxy(
                                   listen_host=CONF.spicehtml5proxy_host,
                                   listen_port=CONF.spicehtml5proxy_port,
                                   source_is_ipv6=CONF.source_is_ipv6,
                                   verbose=CONF.verbose,
                                   cert=CONF.cert,
                                   key=CONF.key,
                                   ssl_only=CONF.ssl_only,
                                   daemon=CONF.daemon,
                                   record=CONF.record,
                                   web=CONF.web,
                                   target_host='ignore',
                                   target_port='ignore',
                                   wrap_mode='exit',
                                   wrap_cmd=None)
    server.start_server()

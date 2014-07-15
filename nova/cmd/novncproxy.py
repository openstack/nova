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
noVNC consoles. Leverages websockify.py by Joel Martin
"""

from __future__ import print_function

import os
import sys

from oslo.config import cfg

from nova import config
from nova.console import websocketproxy
from nova.openstack.common import log as logging
from nova.openstack.common.report import guru_meditation_report as gmr
from nova import version


opts = [
    cfg.StrOpt('novncproxy_host',
               default='0.0.0.0',
               help='Host on which to listen for incoming requests'),
    cfg.IntOpt('novncproxy_port',
               default=6080,
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
    CONF.set_default('web', '/usr/share/novnc')
    config.parse_args(sys.argv)
    logging.setup("nova")

    if CONF.ssl_only and not os.path.exists(CONF.cert):
        print("SSL only and %s not found" % CONF.cert)
        return(-1)

    # Check to see if novnc html/js/css files are present
    if not os.path.exists(CONF.web):
        print("Can not find novnc html/js/css files at %s." % CONF.web)
        return(-1)

    logging.setup("nova")

    gmr.TextGuruMeditation.setup_autorun(version)

    # Create and start the NovaWebSockets proxy
    server = websocketproxy.NovaWebSocketProxy(
                listen_host=CONF.novncproxy_host,
                listen_port=CONF.novncproxy_port,
                source_is_ipv6=CONF.source_is_ipv6,
                verbose=CONF.verbose,
                cert=CONF.cert,
                key=CONF.key,
                ssl_only=CONF.ssl_only,
                daemon=CONF.daemon,
                record=CONF.record,
                traffic=CONF.verbose and not CONF.daemon,
                web=CONF.web,
                file_only=True,
                RequestHandlerClass=websocketproxy.NovaProxyRequestHandler)
    server.start_server()

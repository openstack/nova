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

from oslo_config import cfg

from nova.cmd import baseproxy


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


def main():
    # set default web flag option
    CONF.set_default('web', '/usr/share/novnc')

    baseproxy.proxy(
        host=CONF.novncproxy_host,
        port=CONF.novncproxy_port)

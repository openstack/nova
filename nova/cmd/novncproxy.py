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

import sys


from nova.cmd import baseproxy
import nova.conf
from nova.conf import vnc
from nova import config
from nova.console.securityproxy import rfb


CONF = nova.conf.CONF
vnc.register_cli_opts(CONF)


def main():
    # set default web flag option
    CONF.set_default('web', '/usr/share/novnc')
    config.parse_args(sys.argv)

    # TODO(stephenfin): Always enable the security proxy once we support RFB
    # version 3.3, as used in XenServer.
    security_proxy = None
    if CONF.compute_driver != 'xenapi.XenAPIDriver':
        security_proxy = rfb.RFBSecurityProxy()

    baseproxy.proxy(
        host=CONF.vnc.novncproxy_host,
        port=CONF.vnc.novncproxy_port,
        security_proxy=security_proxy)

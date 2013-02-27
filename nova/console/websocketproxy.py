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

'''
Websocket proxy that is compatible with OpenStack Nova.
Leverages websockify.py by Joel Martin
'''

import Cookie
import socket

import websockify

from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class NovaWebSocketProxy(websockify.WebSocketProxy):
    def __init__(self, *args, **kwargs):
        websockify.WebSocketProxy.__init__(self, unix_target=None,
                                           target_cfg=None,
                                           ssl_target=None, *args, **kwargs)

    def new_client(self):
        """
        Called after a new WebSocket connection has been established.
        """
        cookie = Cookie.SimpleCookie()
        cookie.load(self.headers.getheader('cookie'))
        token = cookie['token'].value
        ctxt = context.get_admin_context()
        rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        connect_info = rpcapi.check_token(ctxt, token=token)

        if not connect_info:
            LOG.audit("Invalid Token: %s", token)
            raise Exception(_("Invalid Token"))

        host = connect_info['host']
        port = int(connect_info['port'])

        # Connect to the target
        self.msg("connecting to: %s:%s" % (host, port))
        LOG.audit("connecting to: %s:%s" % (host, port))
        tsock = self.socket(host, port, connect=True)

        # Handshake as necessary
        if connect_info.get('internal_access_path'):
            tsock.send("CONNECT %s HTTP/1.1\r\n\r\n" %
                        connect_info['internal_access_path'])
            while True:
                data = tsock.recv(4096, socket.MSG_PEEK)
                if data.find("\r\n\r\n") != -1:
                    if not data.split("\r\n")[0].find("200"):
                        LOG.audit("Invalid Connection Info %s", token)
                        raise Exception(_("Invalid Connection Info"))
                    tsock.recv(len(data))
                    break

        if self.verbose and not self.daemon:
            print(self.traffic_legend)

        # Start proxying
        try:
            self.do_proxy(tsock)
        except Exception:
            if tsock:
                tsock.shutdown(socket.SHUT_RDWR)
                tsock.close()
                self.vmsg("%s:%s: Target closed" % (host, port))
                LOG.audit("%s:%s: Target closed" % (host, port))
            raise

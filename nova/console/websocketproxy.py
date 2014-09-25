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
import urlparse

import websockify

from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context
from nova.i18n import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class NovaProxyRequestHandlerBase(object):
    def new_websocket_client(self):
        """Called after a new WebSocket connection has been established."""
        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        from eventlet import hubs
        hubs.use_hub()

        # The nova expected behavior is to have token
        # passed to the method GET of the request
        query = urlparse.urlparse(self.path).query
        token = urlparse.parse_qs(query).get("token", [""]).pop()
        if not token:
            # NoVNC uses it's own convention that forward token
            # from the request to a cookie header, we should check
            # also for this behavior
            hcookie = self.headers.getheader('cookie')
            if hcookie:
                cookie = Cookie.SimpleCookie()
                cookie.load(hcookie)
                if 'token' in cookie:
                    token = cookie['token'].value

        ctxt = context.get_admin_context()
        rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        connect_info = rpcapi.check_token(ctxt, token=token)

        if not connect_info:
            raise Exception(_("Invalid Token"))

        self.msg(_('connect info: %s'), str(connect_info))
        host = connect_info['host']
        port = int(connect_info['port'])

        # Connect to the target
        self.msg(_("connecting to: %(host)s:%(port)s") % {'host': host,
                                                          'port': port})
        tsock = self.socket(host, port, connect=True)

        # Handshake as necessary
        if connect_info.get('internal_access_path'):
            tsock.send("CONNECT %s HTTP/1.1\r\n\r\n" %
                        connect_info['internal_access_path'])
            while True:
                data = tsock.recv(4096, socket.MSG_PEEK)
                if data.find("\r\n\r\n") != -1:
                    if not data.split("\r\n")[0].find("200"):
                        raise Exception(_("Invalid Connection Info"))
                    tsock.recv(len(data))
                    break

        # Start proxying
        try:
            self.do_proxy(tsock)
        except Exception:
            if tsock:
                tsock.shutdown(socket.SHUT_RDWR)
                tsock.close()
                self.vmsg(_("%(host)s:%(port)s: Target closed") %
                          {'host': host, 'port': port})
            raise


# TODO(sross): when the websockify version is bumped to be >=0.6,
#              remove the if-else statement and make the if branch
#              contents the only code.
if getattr(websockify, 'ProxyRequestHandler', None) is not None:
    class NovaProxyRequestHandler(NovaProxyRequestHandlerBase,
                                  websockify.ProxyRequestHandler):
        def __init__(self, *args, **kwargs):
            websockify.ProxyRequestHandler.__init__(self, *args, **kwargs)

        def socket(self, *args, **kwargs):
            return websockify.WebSocketServer.socket(*args, **kwargs)

    class NovaWebSocketProxy(websockify.WebSocketProxy):
        @staticmethod
        def get_logger():
            return LOG

else:
    import sys

    class NovaWebSocketProxy(NovaProxyRequestHandlerBase,
                             websockify.WebSocketProxy):
        def __init__(self, *args, **kwargs):
            del kwargs['traffic']
            del kwargs['RequestHandlerClass']
            websockify.WebSocketProxy.__init__(self, *args,
                                               target_host='ignore',
                                               target_port='ignore',
                                               unix_target=None,
                                               target_cfg=None,
                                               ssl_target=None,
                                               **kwargs)

        def new_client(self):
            self.new_websocket_client()

        def msg(self, *args, **kwargs):
            LOG.info(*args, **kwargs)

        def vmsg(self, *args, **kwargs):
            LOG.debug(*args, **kwargs)

        def warn(self, *args, **kwargs):
            LOG.warn(*args, **kwargs)

        def print_traffic(self, token="."):
            if self.traffic:
                sys.stdout.write(token)
                sys.stdout.flush()

    class NovaProxyRequestHandler(object):
        pass

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
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from oslo.config import cfg

CONF = cfg.CONF
CONF.import_opt('novncproxy_base_url', 'nova.vnc')
CONF.import_opt('html5proxy_base_url', 'nova.spice', group='spice')
CONF.import_opt('vnc_enabled', 'nova.vnc')
CONF.import_opt('enabled', 'nova.spice', group='spice')

LOG = logging.getLogger(__name__)


class NovaWebSocketProxy(websockify.WebSocketProxy):
    def __init__(self, *args, **kwargs):
        websockify.WebSocketProxy.__init__(self, unix_target=None,
                                           target_cfg=None,
                                           ssl_target=None, *args, **kwargs)

    def verify_origin_proto(self, console_type, origin_proto):
        if console_type == 'novnc':
            expected_proto = \
                urlparse.urlparse(CONF.novncproxy_base_url).scheme
        elif console_type == 'spice-html5':
            expected_proto = \
                urlparse.urlparse(CONF.spice.html5proxy_base_url).scheme
        else:
            detail = _("Invalid Console Type for WebSocketProxy: '%s'") % \
                        console_type
            LOG.audit(detail)
            raise exception.ValidationError(detail=detail)
        return origin_proto == expected_proto

    def new_client(self):
        """Called after a new WebSocket connection has been established."""
        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        from eventlet import hubs
        hubs.use_hub()

        cookie = Cookie.SimpleCookie()
        cookie.load(self.headers.getheader('cookie'))
        token = cookie['token'].value
        ctxt = context.get_admin_context()
        rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        connect_info = rpcapi.check_token(ctxt, token=token)

        if not connect_info:
            LOG.audit("Invalid Token: %s", token)
            raise Exception(_("Invalid Token"))

        # Verify Origin
        expected_origin_hostname = self.headers.getheader('Host')
        if ':' in expected_origin_hostname:
            e = expected_origin_hostname
            expected_origin_hostname = e.split(':')[0]
        origin_url = self.headers.getheader('Origin')
        # missing origin header indicates non-browser client which is OK
        if origin_url is not None:
            origin = urlparse.urlparse(origin_url)
            origin_hostname = origin.hostname
            origin_scheme = origin.scheme
            if origin_hostname == '' or origin_scheme == '':
                detail = _("Origin header not valid.")
                raise exception.ValidationError(detail=detail)
            if expected_origin_hostname != origin_hostname:
                detail = _("Origin header does not match this host.")
                raise exception.ValidationError(detail=detail)
            if not self.verify_origin_proto(connect_info['console_type'],
                                              origin.scheme):
                detail = _("Origin header protocol does not match this host.")
                raise exception.ValidationError(detail=detail)

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

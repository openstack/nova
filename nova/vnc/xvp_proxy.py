#!/usr/bin/env python
# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Eventlet WSGI Services to proxy VNC for XCP protocol."""

import socket

import eventlet
import eventlet.green
import eventlet.greenio
import eventlet.wsgi
from oslo_log import log as logging
import webob

import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova import utils
from nova import version
from nova import wsgi


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF


class XCPVNCProxy(object):
    """Class to use the xvp auth protocol to proxy instance vnc consoles."""

    def one_way_proxy(self, source, dest):
        """Proxy tcp connection from source to dest."""
        while True:
            try:
                d = source.recv(32384)
            except Exception:
                d = None

            # If recv fails, send a write shutdown the other direction
            if d is None or len(d) == 0:
                dest.shutdown(socket.SHUT_WR)
                break
            # If send fails, terminate proxy in both directions
            try:
                # sendall raises an exception on write error, unlike send
                dest.sendall(d)
            except Exception:
                source.close()
                dest.close()
                break

    def handshake(self, req, connect_info, sockets):
        """Execute hypervisor-specific vnc auth handshaking (if needed)."""
        host = connect_info.host
        port = connect_info.port

        server = eventlet.connect((host, port))

        # Handshake as necessary
        if 'internal_access_path' in connect_info:
            path = connect_info.internal_access_path
            server.sendall('CONNECT %s HTTP/1.1\r\n\r\n' % path)

            data = ""
            while True:
                b = server.recv(1)
                if b:
                    data += b
                    if data.find("\r\n\r\n") != -1:
                        if not data.split("\r\n")[0].find("200"):
                            LOG.info("Error in handshake format: %s", data)
                            return
                        break

                if not b or len(data) > 4096:
                    LOG.info("Error in handshake: %s", data)
                    return

        client = req.environ['eventlet.input'].get_socket()
        client.sendall("HTTP/1.1 200 OK\r\n\r\n")
        sockets['client'] = client
        sockets['server'] = server

    def proxy_connection(self, req, connect_info, start_response):
        """Spawn bi-directional vnc proxy."""
        sockets = {}
        t0 = utils.spawn(self.handshake, req, connect_info, sockets)
        t0.wait()

        if not sockets.get('client') or not sockets.get('server'):
            LOG.info("Invalid request: %s", req)
            start_response('400 Invalid Request',
                           [('content-type', 'text/html')])
            return "Invalid Request"

        client = sockets['client']
        server = sockets['server']

        t1 = utils.spawn(self.one_way_proxy, client, server)
        t2 = utils.spawn(self.one_way_proxy, server, client)
        t1.wait()
        t2.wait()

        # Make sure our sockets are closed
        server.close()
        client.close()

    def __call__(self, environ, start_response):
        try:
            req = webob.Request(environ)
            LOG.info("Request: %s", req)
            token = req.params.get('token')
            if not token:
                LOG.info("Request made with missing token: %s", req)
                start_response('400 Invalid Request',
                               [('content-type', 'text/html')])
                return "Invalid Request"

            ctxt = context.get_admin_context()

            try:
                connect_info = objects.ConsoleAuthToken.validate(ctxt, token)
            except exception.InvalidToken:
                LOG.info("Request made with invalid token: %s", req)
                start_response('401 Not Authorized',
                               [('content-type', 'text/html')])
                return "Not Authorized"

            return self.proxy_connection(req, connect_info, start_response)
        except Exception as e:
            LOG.info("Unexpected error: %s", e)


class SafeHttpProtocol(eventlet.wsgi.HttpProtocol):
    """HttpProtocol wrapper to suppress IOErrors.

       The proxy code above always shuts down client connections, so we catch
       the IOError that raises when the SocketServer tries to flush the
       connection.
    """
    def finish(self):
        try:
            eventlet.green.BaseHTTPServer.BaseHTTPRequestHandler.finish(self)
        except IOError:
            pass
        eventlet.greenio.shutdown_safe(self.connection)
        self.connection.close()


def get_wsgi_server():
    LOG.info("Starting nova-xvpvncproxy node (version %s)",
             version.version_string_with_package())

    LOG.warning('The nova-xvpvncproxy service is deprecated as it is Xen '
                'specific and has effectively been replaced by noVNC '
                'and the nova-novncproxy service.')

    return wsgi.Server("XCP VNC Proxy",
                       XCPVNCProxy(),
                       protocol=SafeHttpProtocol,
                       host=CONF.vnc.xvpvncproxy_host,
                       port=CONF.vnc.xvpvncproxy_port)

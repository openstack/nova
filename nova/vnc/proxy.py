#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

"""Eventlet WSGI Services to proxy VNC.  No nova deps."""

import base64
import os

import eventlet
from eventlet import wsgi
from eventlet import websocket

import webob


WS_ENDPOINT = '/data'


class WebsocketVNCProxy(object):
    """Class to proxy from websocket to vnc server."""

    def __init__(self, wwwroot):
        self.wwwroot = wwwroot
        self.whitelist = {}
        for root, dirs, files in os.walk(wwwroot):
            hidden_dirs = []
            for d in dirs:
                if d.startswith('.'):
                    hidden_dirs.append(d)
            for d in hidden_dirs:
                dirs.remove(d)
            for name in files:
                if not str(name).startswith('.'):
                    filename = os.path.join(root, name)
                    self.whitelist[filename] = True

    def get_whitelist(self):
        return self.whitelist.keys()

    def sock2ws(self, source, dest):
        try:
            while True:
                d = source.recv(32384)
                if d == '':
                    break
                d = base64.b64encode(d)
                dest.send(d)
        except Exception:
            source.close()
            dest.close()

    def ws2sock(self, source, dest):
        try:
            while True:
                d = source.wait()
                if d is None:
                    break
                d = base64.b64decode(d)
                dest.sendall(d)
        except Exception:
            source.close()
            dest.close()

    def proxy_connection(self, environ, start_response):
        @websocket.WebSocketWSGI
        def _handle(client):
            server = eventlet.connect((client.environ['vnc_host'],
                                       client.environ['vnc_port']))
            t1 = eventlet.spawn(self.ws2sock, client, server)
            t2 = eventlet.spawn(self.sock2ws, server, client)
            t1.wait()
            t2.wait()
        _handle(environ, start_response)

    def __call__(self, environ, start_response):
        req = webob.Request(environ)
        if req.path == WS_ENDPOINT:
            return self.proxy_connection(environ, start_response)
        else:
            if req.path == '/':
                fname = '/vnc_auto.html'
            else:
                fname = req.path

            fname = (self.wwwroot + fname).replace('//', '/')
            if not fname in self.whitelist:
                start_response('404 Not Found',
                               [('content-type', 'text/html')])
                return "Not Found"

            base, ext = os.path.splitext(fname)
            if ext == '.js':
                mimetype = 'application/javascript'
            elif ext == '.css':
                mimetype = 'text/css'
            elif ext in ['.svg', '.jpg', '.png', '.gif']:
                mimetype = 'image'
            else:
                mimetype = 'text/html'

            start_response('200 OK', [('content-type', mimetype)])
            return open(os.path.join(fname)).read()


class DebugMiddleware(object):
    """Debug middleware.  Skip auth, get vnc connect info from query string."""

    def __init__(self, app):
        self.app = app

    @webob.dec.wsgify
    def __call__(self, req):
        if req.path == WS_ENDPOINT:
            req.environ['vnc_host'] = req.params.get('host')
            req.environ['vnc_port'] = int(req.params.get('port'))
        return req.get_response(self.app)

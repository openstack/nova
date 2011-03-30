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

"""Auth Components for VNC Console."""

import time
import urlparse
import webob

from webob import Request

from nova import context
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils
from nova import wsgi
from nova import vnc


LOG = logging.getLogger('nova.vnc-proxy')
FLAGS = flags.FLAGS


class VNCNovaAuthMiddleware(object):
    """Implementation of Middleware to Handle Nova Auth."""

    def __init__(self, app):
        self.app = app
        self.token_cache = {}
        utils.LoopingCall(self.delete_expired_cache_items).start(1)

    @webob.dec.wsgify
    def __call__(self, req):
        token = req.params.get('token')

        if not token:
            referrer = req.environ.get('HTTP_REFERER')
            auth_params = urlparse.parse_qs(urlparse.urlparse(referrer).query)
            if 'token' in auth_params:
                token = auth_params['token'][0]

        connection_info = self.get_token_info(token)
        if not connection_info:
            LOG.audit(_("Unauthorized Access: (%s)"), req.environ)
            return webob.exc.HTTPForbidden(detail='Unauthorized')

        if req.path == vnc.proxy.WS_ENDPOINT:
            req.environ['vnc_host'] = connection_info['host']
            req.environ['vnc_port'] = int(connection_info['port'])

        return req.get_response(self.app)

    def get_token_info(self, token):
        if token in self.token_cache:
            return self.token_cache[token]

        rval = rpc.call(context.get_admin_context(),
                        FLAGS.vncproxy_topic,
                        {"method": "check_token", "args": {'token': token}})
        if rval:
            self.token_cache[token] = rval
        return rval

    def delete_expired_cache_items(self):
        now = time.time()
        to_delete = []
        for k, v in self.token_cache.items():
            if now - v['last_activity_at'] > FLAGS.vnc_token_ttl:
                to_delete.append(k)

        for k in to_delete:
            del self.token_cache[k]


class LoggingMiddleware(object):
    """Middleware for basic vnc-specific request logging."""

    def __init__(self, app):
        self.app = app

    @webob.dec.wsgify
    def __call__(self, req):
        if req.path == vnc.proxy.WS_ENDPOINT:
            LOG.info(_("Received Websocket Request: %s"), req.url)
        else:
            LOG.info(_("Received Request: %s"), req.url)

        return req.get_response(self.app)


class VNCProxyAuthManager(manager.Manager):
    """Manages token based authentication."""

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        super(VNCProxyAuthManager, self).__init__(*args, **kwargs)
        self.tokens = {}
        utils.LoopingCall(self._delete_expired_tokens).start(1)

    def authorize_vnc_console(self, context, token, host, port):
        self.tokens[token] = {'host': host,
                              'port': port,
                              'last_activity_at': time.time()}
        token_dict = self.tokens[token]
        LOG.audit(_("Received Token: %(token)s, %(token_dict)s)"), locals())

    def check_token(self, context, token):
        token_valid = token in self.tokens
        LOG.audit(_("Checking Token: %(token)s, %(token_valid)s)"), locals())
        if token_valid:
            return self.tokens[token]

    def _delete_expired_tokens(self):
        now = time.time()
        to_delete = []
        for k, v in self.tokens.items():
            if now - v['last_activity_at'] > FLAGS.vnc_token_ttl:
                to_delete.append(k)

        for k in to_delete:
            LOG.audit(_("Deleting Expired Token: %s)"), k)
            del self.tokens[k]

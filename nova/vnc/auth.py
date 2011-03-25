#!/usr/bin/env python
# pylint: disable-msg=C0103
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova import wsgi
from nova import vnc


LOG = logging.getLogger('nova.vnc-proxy')
FLAGS = flags.FLAGS


class NovaAuthMiddleware(object):
    """Implementation of Middleware to Handle Nova Auth."""

    def __init__(self, app):
        self.app = app
        self.register_listeners()

    @webob.dec.wsgify
    def __call__(self, req):
        token = req.params.get('token')

        if not token:
            referrer = req.environ.get('HTTP_REFERER')
            auth_params = urlparse.parse_qs(urlparse.urlparse(referrer).query)
            if 'token' in auth_params:
                token = auth_params['token'][0]

        if not token in self.tokens:
            LOG.audit(_("Unauthorized Access: (%s)"), req.environ)
            return webob.exc.HTTPForbidden(detail='Unauthorized')

        if req.path == vnc.proxy.WS_ENDPOINT:
            req.environ['vnc_host'] = self.tokens[token]['args']['host']
            req.environ['vnc_port'] = int(self.tokens[token]['args']['port'])

        return req.get_response(self.app)

    def register_listeners(self):
        middleware = self
        middleware.tokens = {}

        class Proxy():
            @staticmethod
            def authorize_vnc_console(context, **kwargs):
                data = kwargs
                token = kwargs['token']
                LOG.audit(_("Received Token: %s)"), token)
                middleware.tokens[token] = \
                  {'args': kwargs, 'last_activity_at': time.time()}

        def delete_expired_tokens():
            now = time.time()
            to_delete = []
            for k, v in middleware.tokens.items():
                if now - v['last_activity_at'] > FLAGS.vnc_token_ttl:
                    to_delete.append(k)

            for k in to_delete:
                LOG.audit(_("Deleting Token: %s)"), k)
                del middleware.tokens[k]

        conn = rpc.Connection.instance(new=True)
        consumer = rpc.TopicAdapterConsumer(
                       connection=conn,
                       proxy=Proxy,
                       topic=FLAGS.vnc_console_proxy_topic)

        utils.LoopingCall(consumer.fetch,
                          enable_callbacks=True).start(0.1)
        utils.LoopingCall(delete_expired_tokens).start(1)


class LoggingMiddleware(object):
    def __init__(self, app):
        self.app = app

    @webob.dec.wsgify
    def __call__(self, req):
        if req.path == vnc.proxy.WS_ENDPOINT:
            LOG.info(_("Received Websocket Request: %s"), req.url)
        else:
            LOG.info(_("Received Request: %s"), req.url)

        return req.get_response(self.app)

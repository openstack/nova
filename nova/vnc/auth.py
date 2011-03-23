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

"""Auth Components for VNC Console"""

import time
from webob import Request
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils
from nova import wsgi


class NovaAuthMiddleware(object):
    """Implementation of Middleware to Handle Nova Auth"""

    def __init__(self, app):
        self.app = app
        self.register_listeners()

    def __call__(self, environ, start_response):
        req = Request(environ)

        if req.path == '/data':
            token = req.params.get('token')
            if not token in self.tokens:
                start_response('403 Forbidden',
                                [('content-type', 'text/html')])
                return 'Not Authorized'

            environ['vnc_host'] = self.tokens[token]['args']['host']
            environ['vnc_port'] = int(self.tokens[token]['args']['port'])

        resp = req.get_response(self.app)
        return resp(environ, start_response)

    def register_listeners(self):
        middleware = self
        middleware.tokens = {}

        class Callback:
            def __call__(self, data, message):
                if data['method'] == 'authorize_vnc_console':
                    middleware.tokens[data['args']['token']] = \
                      {'args': data['args'], 'last_activity_at': time.time()}

        def delete_expired_tokens():
            now = time.time()
            to_delete = []
            for k, v in middleware.tokens.items():
                if now - v['last_activity_at'] > 600:
                    to_delete.append(k)

            for k in to_delete:
                del middleware.tokens[k]

        conn = rpc.Connection.instance(new=True)
        consumer = rpc.TopicConsumer(
                        connection=conn,
                        topic=FLAGS.vnc_console_proxy_topic)
        consumer.register_callback(Callback())

        utils.LoopingCall(consumer.fetch, auto_ack=True,
                          enable_callbacks=True).start(0.1)
        utils.LoopingCall(delete_expired_tokens).start(1)

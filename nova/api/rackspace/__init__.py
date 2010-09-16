# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
WSGI middleware for Rackspace API controllers.
"""

import json
import time

import routes
import webob.dec
import webob.exc
import webob

from nova import flags
from nova import utils
from nova import wsgi
from nova.api.rackspace import flavors
from nova.api.rackspace import images
from nova.api.rackspace import servers
from nova.api.rackspace import sharedipgroups
from nova.auth import manager


FLAGS = flags.FLAGS
flags.DEFINE_string('nova_api_auth', 'nova.api.rackspace.auth.FakeAuth', 
    'The auth mechanism to use for the Rackspace API implemenation')

class API(wsgi.Middleware):
    """WSGI entry point for all Rackspace API requests."""

    def __init__(self):
        app = AuthMiddleware(APIRouter())
        super(API, self).__init__(app)


class AuthMiddleware(wsgi.Middleware):
    """Authorize the rackspace API request or return an HTTP Forbidden."""

    def __init__(self, application):
        self.auth_driver = utils.import_class(FLAGS.nova_api_auth)()
        super(AuthMiddleware, self).__init__(application)

    @webob.dec.wsgify
    def __call__(self, req):
        if not req.headers.has_key("X-Auth-Token"):
            return self.authenticate(req)

        user = self.auth_driver.authorize_token(req.headers["X-Auth-Token"])

        if not user:
            return webob.exc.HTTPUnauthorized()
        context = {'user':user}
        req.environ['nova.context'] = context
        return self.application

    def authenticate(self, req):
        # Unless the request is explicitly made against /<version>/ don't
        # honor it
        path_info = req.environ['wsgiorg.routing_args'][1]['path_info']
        if path_info:
            return webob.exc.HTTPUnauthorized()

        if req.headers.has_key("X-Auth-User") and \
                req.headers.has_key("X-Auth-Key"):
            username, key = req.headers['X-Auth-User'], req.headers['X-Auth-Key']
            token, user = self.auth_driver.authorize_user(username, key)
            if user and token:
                res = webob.Response()
                res.headers['X-Auth-Token'] = token
                res.headers['X-Server-Management-Url'] = \
                    user['server_management_url']
                res.headers['X-Storage-Url'] = user['storage_url']
                res.headers['X-CDN-Management-Url'] = user['cdn_management_url']
                res.content_type = 'text/plain'
                res.status = '204'
                return res
            else:
                return webob.exc.HTTPUnauthorized()
        return webob.exc.HTTPUnauthorized()

class APIRouter(wsgi.Router):
    """
    Routes requests on the Rackspace API to the appropriate controller
    and method.
    """

    def __init__(self):
        mapper = routes.Mapper()
        mapper.resource("server", "servers", controller=servers.Controller())
        mapper.resource("image", "images", controller=images.Controller(),
                        collection={'detail': 'GET'})
        mapper.resource("flavor", "flavors", controller=flavors.Controller(),
                        collection={'detail': 'GET'})
        mapper.resource("sharedipgroup", "sharedipgroups",
                        controller=sharedipgroups.Controller())
        super(APIRouter, self).__init__(mapper)

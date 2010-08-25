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

from nova import flags
from nova import wsgi
from nova.api.rackspace import flavors
from nova.api.rackspace import images
from nova.api.rackspace import servers
from nova.api.rackspace import sharedipgroups
from nova.auth import manager


class API(wsgi.Middleware):
    """WSGI entry point for all Rackspace API requests."""

    def __init__(self):
        app = AuthMiddleware(APIRouter())
        super(API, self).__init__(app)


class AuthMiddleware(wsgi.Middleware):
    """Authorize the rackspace API request or return an HTTP Forbidden."""

    #TODO(gundlach): isn't this the old Nova API's auth?  Should it be replaced
    #with correct RS API auth?

    @webob.dec.wsgify
    def __call__(self, req):
        context = {}
        if "HTTP_X_AUTH_TOKEN" in req.environ:
            context['user'] = manager.AuthManager().get_user_from_access_key(
                              req.environ['HTTP_X_AUTH_TOKEN'])
            if context['user']:
                context['project'] = manager.AuthManager().get_project(
                                     context['user'].name)
        if "user" not in context:
            return webob.exc.HTTPForbidden()
        req.environ['nova.context'] = context
        return self.application


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

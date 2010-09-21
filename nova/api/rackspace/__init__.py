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
from nova.api.rackspace import ratelimiting
from nova.api.rackspace import servers
from nova.api.rackspace import sharedipgroups
from nova.auth import manager


class API(wsgi.Middleware):
    """WSGI entry point for all Rackspace API requests."""

    def __init__(self):
        app = AuthMiddleware(RateLimitingMiddleware(APIRouter()))
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


class RateLimitingMiddleware(wsgi.Middleware):
    """Rate limit incoming requests according to the OpenStack rate limits."""

    def __init__(self, application, service_host=None):
        """Create a rate limiting middleware that wraps the given application.

        By default, rate counters are stored in memory.  If service_host is
        specified, the middleware instead relies on the ratelimiting.WSGIApp
        at the given host+port to keep rate counters.
        """
        super(RateLimitingMiddleware, self).__init__(application)
        if not service_host:
            #TODO(gundlach): These limits were based on limitations of Cloud 
            #Servers.  We should revisit them in Nova.
            self.limiter = ratelimiting.Limiter(limits={
                    'DELETE': (100, ratelimiting.PER_MINUTE),
                    'PUT': (10, ratelimiting.PER_MINUTE),
                    'POST': (10, ratelimiting.PER_MINUTE),
                    'POST servers': (50, ratelimiting.PER_DAY),
                    'GET changes-since': (3, ratelimiting.PER_MINUTE),
                })
        else:
            self.limiter = ratelimiting.WSGIAppProxy(service_host)

    @webob.dec.wsgify
    def __call__(self, req):
        """Rate limit the request.
        
        If the request should be rate limited, return a 413 status with a 
        Retry-After header giving the time when the request would succeed.
        """
        username = req.headers['X-Auth-User']
        action_name = self.get_action_name(req)
        if not action_name: # not rate limited
            return self.application
        delay = self.get_delay(action_name, username)
        if delay:
            # TODO(gundlach): Get the retry-after format correct.
            raise webob.exc.HTTPRequestEntityTooLarge(headers={
                    'Retry-After': time.time() + delay})
        return self.application

    def get_delay(self, action_name, username):
        """Return the delay for the given action and username, or None if
        the action would not be rate limited.
        """
        if action_name == 'POST servers':
            # "POST servers" is a POST, so it counts against "POST" too.
            # Attempt the "POST" first, lest we are rate limited by "POST" but
            # use up a precious "POST servers" call.
            delay = self.limiter.perform("POST", username=username)
            if delay:
                return delay
        return self.limiter.perform(action_name, username=username)

    def get_action_name(self, req):
        """Return the action name for this request."""
        if req.method == 'GET' and 'changes-since' in req.GET:
            return 'GET changes-since'
        if req.method == 'POST' and req.path_info.startswith('/servers'):
            return 'POST servers'
        if req.method in ['PUT', 'POST', 'DELETE']:
            return req.method
        return None


class APIRouter(wsgi.Router):
    """
    Routes requests on the Rackspace API to the appropriate controller
    and method.
    """

    def __init__(self):
        mapper = routes.Mapper()
        mapper.resource("server", "servers", controller=servers.Controller()
                        collection={'detail': 'GET'})
        mapper.resource("image", "images", controller=images.Controller(),
                        collection={'detail': 'GET'})
        mapper.resource("flavor", "flavors", controller=flavors.Controller(),
                        collection={'detail': 'GET'})
        mapper.resource("sharedipgroup", "sharedipgroups",
                        controller=sharedipgroups.Controller())
        super(APIRouter, self).__init__(mapper)

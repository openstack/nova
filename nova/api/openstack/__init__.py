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
WSGI middleware for OpenStack API controllers.
"""

import json
import time

import logging
import routes
import webob.dec
import webob.exc
import webob

from nova import flags
from nova import utils
from nova import wsgi
from nova.api.openstack import faults
from nova.api.openstack import backup_schedules
from nova.api.openstack import flavors
from nova.api.openstack import images
from nova.api.openstack import ratelimiting
from nova.api.openstack import servers
from nova.api.openstack import sharedipgroups
from nova.auth import manager


FLAGS = flags.FLAGS
flags.DEFINE_string('nova_api_auth',
    'nova.api.openstack.auth.BasicApiAuthManager',
    'The auth mechanism to use for the OpenStack API implemenation')

flags.DEFINE_list('nova_api_permitted_operations',
    [],
    'A comma-separated list of permitted api operations. Empty for all.')

class API(wsgi.Middleware):
    """WSGI entry point for all OpenStack API requests."""

    def __init__(self):
        app = AuthMiddleware(RateLimitingMiddleware(APIRouter()))
        super(API, self).__init__(app)

    @webob.dec.wsgify
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            logging.warn("Caught error: %s" % str(ex))
            exc = webob.exc.HTTPInternalServerError(explanation=str(ex))
            return faults.Fault(exc)


class AuthMiddleware(wsgi.Middleware):
    """Authorize the openstack API request or return an HTTP Forbidden."""

    def __init__(self, application):
        self.auth_driver = utils.import_class(FLAGS.nova_api_auth)()
        super(AuthMiddleware, self).__init__(application)

    @webob.dec.wsgify
    def __call__(self, req):
        if 'X-Auth-Token' not in req.headers:
            return self.auth_driver.authenticate(req)

        user = self.auth_driver.authorize_token(req.headers["X-Auth-Token"])

        if not user:
            return faults.Fault(webob.exc.HTTPUnauthorized())

        if 'nova.context' not in req.environ:
            req.environ['nova.context'] = {}
        req.environ['nova.context']['user'] = user
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
        user_id = req.environ['nova.context']['user']['id']
        action_name = self.get_action_name(req)
        if not action_name:
            # Not rate limited
            return self.application
        delay = self.get_delay(action_name, user_id)
        if delay:
            # TODO(gundlach): Get the retry-after format correct.
            exc = webob.exc.HTTPRequestEntityTooLarge(
                    explanation='Too many requests.',
                    headers={'Retry-After': time.time() + delay})
            raise faults.Fault(exc)
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
    Routes requests on the OpenStack API to the appropriate controller
    and method.
    """

    def __init__(self):
        mapper = routes.Mapper()
        commands = {
            "server" : dict(plural='servers',
                           controller=servers.Controller(),
                           collection={'detail': 'GET'},
                           member={'action': 'POST'}),
            "backup_schedule" : dict(plural='backup_schedules',
                                    controller=backup_schedules.Controller(),
                                    parent_resource=dict(member_name='server',
                                        collection_name='servers')),
            "image" : dict(plural='images',
                          controller=images.Controller(),
                          collection={'detail': 'GET'}),
            "flavor" : dict(plural='flavors', 
                           controller=flavors.Controller(),
                           collection={'detail': 'GET'}),
            "sharedipgroup" : dict(plural="sharedipgroups",
                                  controller=sharedipgroups.Controller()),
        }

        permitted = commands.keys()
        if len(FLAGS.nova_api_permitted_operations) > 0:
            permitted = FLAGS.nova_api_permitted_operations
        logging.debug("Permitted operation set: %s" % (permitted,))
        for command in permitted:
            options = commands.get(command, None)
            if not options:
                logging.warning("Unknown option in nova_api_permitted_operations: '%s' (skipping)" % (command,))
                continue
            collection = options['plural']
            del options['plural']
            mapper.resource(command, collection, **options)

        super(APIRouter, self).__init__(mapper)


def limited(items, req):
    """Return a slice of items according to requested offset and limit.

    items - a sliceable
    req - wobob.Request possibly containing offset and limit GET variables.
          offset is where to start in the list, and limit is the maximum number
          of items to return.

    If limit is not specified, 0, or > 1000, defaults to 1000.
    """
    offset = int(req.GET.get('offset', 0))
    limit = int(req.GET.get('limit', 0))
    if not limit:
        limit = 1000
    limit = min(1000, limit)
    range_end = offset + limit
    return items[offset:range_end]

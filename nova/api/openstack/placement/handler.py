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
"""Handlers for placement API.

Individual handlers are associated with URL paths in the
ROUTE_DECLARATIONS dictionary. At the top level each key is a Routes
compliant path. The value of that key is a dictionary mapping
individual HTTP request methods to a Python function representing a
simple WSGI application for satisfying that request.

The ``make_map`` method processes ROUTE_DECLARATIONS to create a
Routes.Mapper, including automatic handlers to respond with a
405 when a request is made against a valid URL with an invalid
method.
"""

import routes
import webob

from nova.api.openstack.placement.handlers import root
from nova.api.openstack.placement import util


# URLs and Handlers
ROUTE_DECLARATIONS = {
    '/': {
        'GET': root.home,
    },
}


def dispatch(environ, start_response, mapper):
    """Find a matching route for the current request.

    If no match is found, raise a 404 response.
    If there is a matching route, but no matching handler
    for the given method, raise a 405.
    """
    result = mapper.match(environ=environ)
    if result is None:
        raise webob.exc.HTTPNotFound(
            json_formatter=util.json_error_formatter)
    # We can't reach this code without action being present.
    handler = result.pop('action')
    environ['wsgiorg.routing_args'] = ((), result)
    return handler(environ, start_response)


def handle_405(environ, start_response):
    """Return a 405 response as required.

    If _methods are in routing_args, send an allow header listing
    the methods that are possible on the provided URL.
    """
    _methods = util.wsgi_path_item(environ, '_methods')
    headers = {}
    if _methods:
        headers['allow'] = _methods
    raise webob.exc.HTTPMethodNotAllowed(
        'The method specified is not allowed for this resource.',
        headers=headers, json_formatter=util.json_error_formatter)


def make_map(declarations):
    """Process route declarations to create a Route Mapper."""
    mapper = routes.Mapper()
    for route, targets in declarations.items():
        allowed_methods = []
        for method in targets:
            mapper.connect(route, action=targets[method],
                           conditions=dict(method=[method]))
            allowed_methods.append(method)
        allowed_methods = ', '.join(allowed_methods)
        mapper.connect(route, action=handle_405, _methods=allowed_methods)
    return mapper


class PlacementHandler(object):
    """Serve Placement API.

    Dispatch to handlers defined in ROUTE_DECLARATIONS.
    """

    def __init__(self, **local_config):
        # NOTE(cdent): Local config currently unused.
        self._map = make_map(ROUTE_DECLARATIONS)

    def __call__(self, environ, start_response):
        # All requests but '/' require admin.
        # TODO(cdent): We'll eventually want our own auth context,
        # but using nova's is convenient for now.
        if environ['PATH_INFO'] != '/':
            context = environ['placement.context']
            # TODO(cdent): Using is_admin everywhere (except /) is
            # insufficiently flexible for future use case but is
            # convenient for initial exploration. We will need to
            # determine how to manage authorization/policy and
            # implement that, probably per handler. Also this is
            # just the wrong way to do things, but policy not
            # integrated yet.
            if 'admin' not in context.to_policy_values()['roles']:
                raise webob.exc.HTTPForbidden(
                    'admin required',
                    json_formatter=util.json_error_formatter)
        return dispatch(environ, start_response, self._map)

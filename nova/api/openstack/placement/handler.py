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

from oslo_log import log as logging

from nova.api.openstack.placement.handlers import aggregate
from nova.api.openstack.placement.handlers import allocation
from nova.api.openstack.placement.handlers import allocation_candidate
from nova.api.openstack.placement.handlers import inventory
from nova.api.openstack.placement.handlers import resource_class
from nova.api.openstack.placement.handlers import resource_provider
from nova.api.openstack.placement.handlers import root
from nova.api.openstack.placement.handlers import trait
from nova.api.openstack.placement.handlers import usage
from nova.api.openstack.placement import policy
from nova.api.openstack.placement import util
from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)

# URLs and Handlers
# NOTE(cdent): When adding URLs here, do not use regex patterns in
# the path parameters (e.g. {uuid:[0-9a-zA-Z-]+}) as that will lead
# to 404s that are controlled outside of the individual resources
# and thus do not include specific information on the why of the 404.
ROUTE_DECLARATIONS = {
    '/': {
        'GET': root.home,
    },
    # NOTE(cdent): This allows '/placement/' and '/placement' to
    # both work as the root of the service, which we probably want
    # for those situations where the service is mounted under a
    # prefix (as it is in devstack). While weird, an empty string is
    # a legit key in a dictionary and matches as desired in Routes.
    '': {
        'GET': root.home,
    },
    '/resource_classes': {
        'GET': resource_class.list_resource_classes,
        'POST': resource_class.create_resource_class
    },
    '/resource_classes/{name}': {
        'GET': resource_class.get_resource_class,
        'PUT': resource_class.update_resource_class,
        'DELETE': resource_class.delete_resource_class,
    },
    '/resource_providers': {
        'GET': resource_provider.list_resource_providers,
        'POST': resource_provider.create_resource_provider
    },
    '/resource_providers/{uuid}': {
        'GET': resource_provider.get_resource_provider,
        'DELETE': resource_provider.delete_resource_provider,
        'PUT': resource_provider.update_resource_provider
    },
    '/resource_providers/{uuid}/inventories': {
        'GET': inventory.get_inventories,
        'POST': inventory.create_inventory,
        'PUT': inventory.set_inventories,
        'DELETE': inventory.delete_inventories
    },
    '/resource_providers/{uuid}/inventories/{resource_class}': {
        'GET': inventory.get_inventory,
        'PUT': inventory.update_inventory,
        'DELETE': inventory.delete_inventory
    },
    '/resource_providers/{uuid}/usages': {
        'GET': usage.list_usages
    },
    '/resource_providers/{uuid}/aggregates': {
        'GET': aggregate.get_aggregates,
        'PUT': aggregate.set_aggregates
    },
    '/resource_providers/{uuid}/allocations': {
        'GET': allocation.list_for_resource_provider,
    },
    '/allocations/{consumer_uuid}': {
        'GET': allocation.list_for_consumer,
        'PUT': allocation.set_allocations,
        'DELETE': allocation.delete_allocations,
    },
    '/allocation_candidates': {
        'GET': allocation_candidate.list_allocation_candidates,
    },
    '/traits': {
        'GET': trait.list_traits,
    },
    '/traits/{name}': {
        'GET': trait.get_trait,
        'PUT': trait.put_trait,
        'DELETE': trait.delete_trait,
    },
    '/resource_providers/{uuid}/traits': {
        'GET': trait.list_traits_for_resource_provider,
        'PUT': trait.update_traits_for_resource_provider,
        'DELETE': trait.delete_traits_for_resource_provider
    },
    '/usages': {
        'GET': usage.get_total_usages,
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
    """Return a 405 response when method is not allowed.

    If _methods are in routing_args, send an allow header listing
    the methods that are possible on the provided URL.
    """
    _methods = util.wsgi_path_item(environ, '_methods')
    headers = {}
    if _methods:
        # Ensure allow header is a python 2 or 3 native string (thus
        # not unicode in python 2 but stay a string in python 3)
        # In the process done by Routes to save the allowed methods
        # to its routing table they become unicode in py2.
        headers['allow'] = str(_methods)
    # Use Exception class as WSGI Application. We don't want to raise here.
    response = webob.exc.HTTPMethodNotAllowed(
        _('The method specified is not allowed for this resource.'),
        headers=headers, json_formatter=util.json_error_formatter)
    return response(environ, start_response)


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
        if environ['PATH_INFO'] != '/':
            context = environ['placement.context']
            # TODO(cdent): Using is_admin everywhere (except /) is
            # insufficiently flexible for future use case but is
            # convenient for initial exploration.
            if not policy.placement_authorize(context, 'placement'):
                raise webob.exc.HTTPForbidden(
                    _('admin required'),
                    json_formatter=util.json_error_formatter)
        # Check that an incoming request with a content-length header
        # that is an integer > 0 and not empty, also has a content-type
        # header that is not empty. If not raise a 400.
        clen = environ.get('CONTENT_LENGTH')
        try:
            if clen and (int(clen) > 0) and not environ.get('CONTENT_TYPE'):
                raise webob.exc.HTTPBadRequest(
                   _('content-type header required when content-length > 0'),
                   json_formatter=util.json_error_formatter)
        except ValueError as exc:
            raise webob.exc.HTTPBadRequest(
                _('content-length header must be an integer'),
                json_formatter=util.json_error_formatter)
        try:
            return dispatch(environ, start_response, self._map)
        # Trap the NotFound exceptions raised by the objects used
        # with the API and transform them into webob.exc.HTTPNotFound.
        except exception.NotFound as exc:
            raise webob.exc.HTTPNotFound(
                exc, json_formatter=util.json_error_formatter)
        # Trap the HTTPNotFound that can be raised by dispatch()
        # when no route is found. The exception is passed through to
        # the FaultWrap middleware without causing an alarming log
        # message.
        except webob.exc.HTTPNotFound:
            raise
        except Exception as exc:
            LOG.exception("Uncaught exception")
            raise

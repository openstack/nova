#   Copyright 2023 SAP SE
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
from webob import exc

from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova.policies import sap_admin_api as sap_policies


# list of endpoints registered with _register_endpoint below
# This variable is used to validate called endpoints and to be able to list
# available endpoints.
_ENDPOINTS = {'GET': [], 'POST': []}


def _register_endpoint(method):
    """Decorator to register a method as endpoint for a HTTP method"""
    def decorator(fn):
        _ENDPOINTS[method].append(fn.__name__)
        return fn

    return decorator


class SAPAdminApiController(wsgi.Controller):
    """Controller class containing custom API endpoints for SAP

    Add a method and register it with _register_endpoint() to make it available
    in the API.
    """

    def __init__(self):
        super().__init__()
        self.compute_api = compute.API()

    @_register_endpoint('GET')
    def endpoints(self, req):
        """Return the available API endpoints"""
        context = req.environ['nova.context']
        context.can(sap_policies.POLICY_ROOT % 'endpoints:list', target={})
        return {'endpoints': _ENDPOINTS}

    @wsgi.expected_errors(404)
    def get(self, req, action):
        if action not in _ENDPOINTS['GET']:
            raise exc.HTTPNotFound(explanation='Unknown action')

        return getattr(self, action)(req)

    @wsgi.expected_errors(404)
    def post(self, req, action, body):
        if action not in _ENDPOINTS['POST']:
            raise exc.HTTPNotFound(explanation='Unknown action')

        return getattr(self, action)(req, body)

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

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import sap_admin_api
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.policies import sap_admin_api as sap_policies
from nova.quota import QUOTAS


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

    @wsgi.response(202)
    @wsgi.expected_errors(404)
    @_register_endpoint('POST')
    def clear_quota_resources_cache(self, req, body):
        """Clears the cache used by the SAPQuotaEngine"""
        context = req.environ['nova.context']
        context.can(sap_policies.POLICY_ROOT % 'clear-quota-resources-cache')

        # if we're not running with our custom quota engine for some reason
        if not hasattr(QUOTAS, 'clear_cache'):
            txt = 'Quota engine does not support cache clearing'
            raise exc.HTTPNotFound(explanation=txt)

        QUOTAS.clear_cache()

    @wsgi.response(202)
    @validation.schema(sap_admin_api.in_cluster_vmotion)
    @_register_endpoint('POST')
    def in_cluster_vmotion(self, req, body):
        """Call nova-compute to vMotion a VM inside a cluster

        vMotion will target the given host MoRef
        """
        context = req.environ['nova.context']
        server_id = body['instance_uuid']
        host_moref_value = body['host']
        instance = common.get_instance(self.compute_api, context, server_id)
        context.can(sap_policies.POLICY_ROOT % 'in-cluster-vmotion',
                    target={'project_id': instance.project_id})

        try:
            self.compute_api.in_cluster_vmotion(context, instance,
                                                host_moref_value)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(
                state_error, 'in_cluster_vmotion', server_id)

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

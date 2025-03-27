# Copyright 2011 OpenStack Foundation
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

from nova.api.openstack import api_version_request
from nova.api.openstack.compute.schemas import limits
from nova.api.openstack.compute.views import limits as limits_views
from nova.api.openstack import wsgi
from nova.api import validation
from nova.policies import limits as limits_policies
from nova import quota


QUOTAS = quota.QUOTAS

# This is a list of limits which needs to filter out from the API response.
# This is due to the deprecation of network related proxy APIs, the related
# limit should be removed from the API also.
FILTERED_LIMITS_2_36 = ['floating_ips', 'security_groups',
                        'security_group_rules']

FILTERED_LIMITS_2_57 = list(FILTERED_LIMITS_2_36)
FILTERED_LIMITS_2_57.extend(['injected_files', 'injected_file_content_bytes'])


class LimitsController(wsgi.Controller):
    """Controller for accessing limits in the OpenStack API."""

    @wsgi.expected_errors(())
    @validation.query_schema(limits.limits_query_schema, '2.1', '2.56')
    @validation.query_schema(limits.limits_query_schema, '2.57', '2.74')
    @validation.query_schema(limits.limits_query_schema_275, '2.75')
    def index(self, req):
        filtered_limits = []
        if api_version_request.is_supported(req, '2.57'):
            filtered_limits = FILTERED_LIMITS_2_57
        elif api_version_request.is_supported(req, '2.36'):
            filtered_limits = FILTERED_LIMITS_2_36

        max_image_meta = True
        if api_version_request.is_supported(req, '2.39'):
            max_image_meta = False

        return self._index(req, filtered_limits=filtered_limits,
                           max_image_meta=max_image_meta)

    def _index(self, req, filtered_limits=None, max_image_meta=True):
        """Return all global limit information."""
        context = req.environ['nova.context']
        context.can(limits_policies.BASE_POLICY_NAME, target={})
        project_id = context.project_id
        if 'tenant_id' in req.GET:
            project_id = req.GET.get('tenant_id')
            context.can(limits_policies.OTHER_PROJECT_LIMIT_POLICY_NAME)

        quotas = QUOTAS.get_project_quotas(context, project_id, usages=True)
        builder = limits_views.ViewBuilder()
        return builder.build(req, quotas, filtered_limits=filtered_limits,
                             max_image_meta=max_image_meta)

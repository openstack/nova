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

from nova.api.openstack.api_version_request \
    import MAX_IMAGE_META_PROXY_API_VERSION
from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack.api_version_request \
    import MIN_WITHOUT_IMAGE_META_PROXY_API_VERSION
from nova.api.openstack.api_version_request \
    import MIN_WITHOUT_PROXY_API_SUPPORT_VERSION
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

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(limits.limits_query_schema)
    def index(self, req):
        return self._index(req)

    @wsgi.Controller.api_version(MIN_WITHOUT_PROXY_API_SUPPORT_VERSION,  # noqa
                                 MAX_IMAGE_META_PROXY_API_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(limits.limits_query_schema)
    def index(self, req):  # noqa
        return self._index(req, FILTERED_LIMITS_2_36)

    @wsgi.Controller.api_version(  # noqa
        MIN_WITHOUT_IMAGE_META_PROXY_API_VERSION, '2.56')
    @wsgi.expected_errors(())
    @validation.query_schema(limits.limits_query_schema)
    def index(self, req):  # noqa
        return self._index(req, FILTERED_LIMITS_2_36, max_image_meta=False)

    @wsgi.Controller.api_version('2.57')  # noqa
    @wsgi.expected_errors(())
    @validation.query_schema(limits.limits_query_schema_275, '2.75')
    @validation.query_schema(limits.limits_query_schema, '2.57', '2.74')
    def index(self, req):  # noqa
        return self._index(req, FILTERED_LIMITS_2_57, max_image_meta=False)

    def _index(self, req, filtered_limits=None, max_image_meta=True):
        """Return all global limit information."""
        context = req.environ['nova.context']
        context.can(limits_policies.BASE_POLICY_NAME, target={})
        project_id = context.project_id
        if 'tenant_id' in req.GET:
            project_id = req.GET.get('tenant_id')
            context.can(limits_policies.OTHER_PROJECT_LIMIT_POLICY_NAME,
                        target={'project_id': project_id})

        quotas = QUOTAS.get_project_quotas(context, project_id,
                                           usages=True)
        builder = limits_views.ViewBuilder()
        return builder.build(req, quotas, filtered_limits=filtered_limits,
                             max_image_meta=max_image_meta)

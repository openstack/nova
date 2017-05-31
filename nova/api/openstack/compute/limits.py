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
from nova.api.openstack.compute.views import limits as limits_views
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.policies import limits as limits_policies
from nova import quota


QUOTAS = quota.QUOTAS


class LimitsController(wsgi.Controller):
    """Controller for accessing limits in the OpenStack API."""

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @extensions.expected_errors(())
    def index(self, req):
        return self._index(req)

    @wsgi.Controller.api_version(MIN_WITHOUT_PROXY_API_SUPPORT_VERSION,  # noqa
                                 MAX_IMAGE_META_PROXY_API_VERSION)  # noqa
    @extensions.expected_errors(())
    def index(self, req):
        return self._index(req, filter_result=True)

    @wsgi.Controller.api_version(  # noqa
        MIN_WITHOUT_IMAGE_META_PROXY_API_VERSION)  # noqa
    @extensions.expected_errors(())
    def index(self, req):
        return self._index(req, filter_result=True, max_image_meta=False)

    def _index(self, req, filter_result=False, max_image_meta=True):
        """Return all global limit information."""
        context = req.environ['nova.context']
        context.can(limits_policies.BASE_POLICY_NAME)
        project_id = req.params.get('tenant_id', context.project_id)
        quotas = QUOTAS.get_project_quotas(context, project_id,
                                           usages=False)
        abs_limits = {k: v['limit'] for k, v in quotas.items()}

        builder = limits_views.ViewBuilder()
        return builder.build(abs_limits, filter_result=filter_result,
                             max_image_meta=max_image_meta)

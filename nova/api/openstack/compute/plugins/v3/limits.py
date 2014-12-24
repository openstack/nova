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


from nova.api.openstack.compute.views import limits as limits_views
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import quota


QUOTAS = quota.QUOTAS
ALIAS = 'limits'


class LimitsController(wsgi.Controller):
    """Controller for accessing limits in the OpenStack API."""

    @extensions.expected_errors(())
    def index(self, req):
        """Return all global and rate limit information."""
        context = req.environ['nova.context']
        project_id = req.params.get('tenant_id', context.project_id)
        quotas = QUOTAS.get_project_quotas(context, project_id,
                                           usages=False)
        abs_limits = {k: v['limit'] for k, v in quotas.items()}
        rate_limits = req.environ.get("nova.limits", [])

        builder = self._get_view_builder(req)
        return builder.build(rate_limits, abs_limits)

    def _get_view_builder(self, req):
        return limits_views.ViewBuilderV3()


class Limits(extensions.V3APIExtensionBase):
    """Limits support."""

    name = "Limits"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resource = [extensions.ResourceExtension(ALIAS,
                                                 LimitsController())]
        return resource

    def get_controller_extensions(self):
        return []

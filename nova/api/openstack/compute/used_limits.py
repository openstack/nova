# Copyright 2012 OpenStack Foundation
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
from nova.api.openstack.api_version_request \
    import MIN_WITHOUT_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import wsgi
from nova.policies import used_limits as ul_policies
from nova import quota


QUOTAS = quota.QUOTAS


class UsedLimitsController(wsgi.Controller):

    @wsgi.extends
    @wsgi.expected_errors(())
    def index(self, req, resp_obj):
        context = req.environ['nova.context']
        project_id = self._project_id(context, req)
        quotas = QUOTAS.get_project_quotas(context, project_id, usages=True)
        if api_version_request.is_supported(
                req, min_version=MIN_WITHOUT_PROXY_API_SUPPORT_VERSION):
            quota_map = {
                'totalRAMUsed': 'ram',
                'totalCoresUsed': 'cores',
                'totalInstancesUsed': 'instances',
                'totalServerGroupsUsed': 'server_groups',
            }
        else:
            quota_map = {
                'totalRAMUsed': 'ram',
                'totalCoresUsed': 'cores',
                'totalInstancesUsed': 'instances',
                'totalFloatingIpsUsed': 'floating_ips',
                'totalSecurityGroupsUsed': 'security_groups',
                'totalServerGroupsUsed': 'server_groups',
            }

        used_limits = {}
        for display_name, key in quota_map.items():
            if key in quotas:
                used_limits[display_name] = quotas[key]['in_use']

        resp_obj.obj['limits']['absolute'].update(used_limits)

    def _project_id(self, context, req):
        if 'tenant_id' in req.GET:
            tenant_id = req.GET.get('tenant_id')
            target = {
                'project_id': tenant_id,
                'user_id': context.user_id
                }
            context.can(ul_policies.BASE_POLICY_NAME, target)
            return tenant_id
        return context.project_id

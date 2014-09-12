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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import quota


QUOTAS = quota.QUOTAS


ALIAS = "os-used-limits"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class UsedLimitsController(wsgi.Controller):

    @staticmethod
    def _reserved(req):
        try:
            return int(req.GET['reserved'])
        except (ValueError, KeyError):
            return False

    @wsgi.extends
    @extensions.expected_errors(())
    def index(self, req, resp_obj):
        context = req.environ['nova.context']
        project_id = self._project_id(context, req)
        quotas = QUOTAS.get_project_quotas(context, project_id, usages=True)
        quota_map = {
            'totalRAMUsed': 'ram',
            'totalCoresUsed': 'cores',
            'totalInstancesUsed': 'instances',
            'totalFloatingIpsUsed': 'floating_ips',
            'totalSecurityGroupsUsed': 'security_groups',
            'totalServerGroupsUsed': 'server_groups',
        }
        used_limits = {}
        for display_name, key in quota_map.iteritems():
            if key in quotas:
                reserved = (quotas[key]['reserved']
                            if self._reserved(req) else 0)
                used_limits[display_name] = quotas[key]['in_use'] + reserved

        resp_obj.obj['limits']['absolute'].update(used_limits)

    def _project_id(self, context, req):
        if 'tenant_id' in req.GET:
            tenant_id = req.GET.get('tenant_id')
            target = {
                'project_id': tenant_id,
                'user_id': context.user_id
                }
            authorize(context, target=target)
            return tenant_id
        return context.project_id


class UsedLimits(extensions.V3APIExtensionBase):
    """Provide data on limited resources that are being used."""

    name = "UsedLimits"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = UsedLimitsController()
        limits_ext = extensions.ControllerExtension(self, 'limits',
                                                    controller=controller)
        return [limits_ext]

    def get_resources(self):
        return []

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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
#    under the License

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.openstack.common import log as logging
from nova import quota


LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS


XMLNS = "http://docs.openstack.org/compute/ext/used_limits/api/v1.1"
ALIAS = "os-used-limits"
authorize = extensions.soft_extension_authorizer('compute', 'used_limits')


class UsedLimitsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('limits', selector='limits')
        root.set('{%s}usedLimits' % XMLNS, '%s:usedLimits' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS})


class UsedLimitsController(wsgi.Controller):

    @wsgi.extends
    def index(self, req, resp_obj):
        resp_obj.attach(xml=UsedLimitsTemplate())
        context = req.environ['nova.context']
        quotas = QUOTAS.get_project_quotas(context, context.project_id,
                                           usages=True)
        quota_map = {
            'totalRAMUsed': 'ram',
            'totalCoresUsed': 'cores',
            'totalInstancesUsed': 'instances',
            'totalVolumesUsed': 'volumes',
            'totalVolumeGigabytesUsed': 'gigabytes',
            'totalFloatingIpsUsed': 'floating_ips',
            'totalSecurityGroupsUsed': 'security_groups',
        }
        used_limits = {}
        for display_name, quota in quota_map.iteritems():
            if quota in quotas:
                used_limits[display_name] = quotas[quota]['in_use']

        resp_obj.obj['limits']['absolute'].update(used_limits)


class Used_limits(extensions.ExtensionDescriptor):
    """Provide data on limited resources that are being used."""

    name = "UsedLimits"
    alias = ALIAS
    namespace = XMLNS
    updated = "2012-07-13T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = UsedLimitsController()
        limits_ext = extensions.ControllerExtension(self, 'limits',
                                                    controller=controller)
        return [limits_ext]

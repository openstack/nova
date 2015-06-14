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


class ExtendedLimitsController(wsgi.Controller):

    @wsgi.extends
    def index(self, req, resp_obj):

        context = req.environ['nova.context']
        quotas = QUOTAS.get_project_quotas(context, context.project_id,
                                           usages=False)
        abs = resp_obj.obj.get('limits', {}).get('absolute', {})
        abs['maxServerGroups'] = quotas.get('server_groups').get('limit')
        abs['maxServerGroupMembers'] =\
            quotas.get('server_group_members').get('limit')


class Server_group_quotas(extensions.ExtensionDescriptor):
    """Adds quota support to server groups."""

    name = "ServerGroupQuotas"
    alias = "os-server-group-quotas"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "server-group-quotas/api/v2")
    updated = "2014-07-25T00:00:00Z"

    def get_controller_extensions(self):
        extension_list = [extensions.ControllerExtension(self,
                                     'limits',
                                     ExtendedLimitsController()),
                     ]
        return extension_list

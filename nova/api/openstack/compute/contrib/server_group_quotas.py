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
from nova.api.openstack import xmlutil
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


class ExtendedQuotaSetsController(wsgi.Controller):

    @wsgi.extends
    def show(self, req, id, resp_obj):
        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedQuotaSetsTemplate())

    @wsgi.extends
    def update(self, req, id, body, resp_obj):
        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedQuotaSetsTemplate())

    @wsgi.extends
    def defaults(self, req, id, resp_obj):
        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedQuotaSetsTemplate())


class ExtendedQuotaSetsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        elem = xmlutil.SubTemplateElement(root, 'server_groups')
        elem.text = 'server_groups'
        elem = xmlutil.SubTemplateElement(root, 'server_group_members')
        elem.text = 'server_group_members'
        return xmlutil.SlaveTemplate(root, 1)


class ExtendedQuotaClassSetsController(wsgi.Controller):

    @wsgi.extends
    def show(self, req, id, resp_obj):
        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedQuotaClassSetsTemplate())

    @wsgi.extends
    def update(self, req, id, body, resp_obj):
        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedQuotaClassSetsTemplate())


class ExtendedQuotaClassSetsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_class_set',
                                       selector='quota_class_set')
        elem = xmlutil.SubTemplateElement(root, 'server_groups')
        elem.text = 'server_groups'
        elem = xmlutil.SubTemplateElement(root, 'server_group_members')
        elem.text = 'server_group_members'
        return xmlutil.SlaveTemplate(root, 1)


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
                          extensions.ControllerExtension(self,
                                     'os-quota-sets',
                                     ExtendedQuotaSetsController()),
                          extensions.ControllerExtension(self,
                                     'os-quota-class-sets',
                                     ExtendedQuotaClassSetsController()),
                     ]
        return extension_list

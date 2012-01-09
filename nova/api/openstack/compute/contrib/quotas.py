# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import webob

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova import db
from nova import exception
from nova import quota


quota_resources = ['metadata_items', 'injected_file_content_bytes',
        'volumes', 'gigabytes', 'ram', 'floating_ips', 'instances',
        'injected_files', 'cores']


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in quota_resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(object):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict"""

        result = dict(id=str(project_id))

        for resource in quota_resources:
            result[resource] = quota_set[resource]

        return dict(quota_set=result)

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        try:
            db.sqlalchemy.api.authorize_project_context(context, id)
            return self._format_quota_set(id,
                                        quota.get_project_quotas(context, id))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        project_id = id
        for key in body['quota_set'].keys():
            if key in quota_resources:
                value = int(body['quota_set'][key])
                try:
                    db.quota_update(context, project_id, key, value)
                except exception.ProjectQuotaNotFound:
                    db.quota_create(context, project_id, key, value)
                except exception.AdminRequired:
                    raise webob.exc.HTTPForbidden()
        return {'quota_set': quota.get_project_quotas(context, project_id)}

    def defaults(self, req, id):
        return self._format_quota_set(id, quota._get_default_quotas())


class Quotas(extensions.ExtensionDescriptor):
    """Quotas management support"""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/compute/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                            QuotaSetsController(),
                                            member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources

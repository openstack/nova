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

from nova import db
from nova import exception
from nova import quota
from nova.api.openstack import extensions


class QuotaSetsController(object):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict"""

        return {'quota_set': {
            'id': str(project_id),
            'metadata_items': quota_set['metadata_items'],
            'injected_file_content_bytes':
             quota_set['injected_file_content_bytes'],
            'volumes': quota_set['volumes'],
            'gigabytes': quota_set['gigabytes'],
            'ram': quota_set['ram'],
            'floating_ips': quota_set['floating_ips'],
            'instances': quota_set['instances'],
            'injected_files': quota_set['injected_files'],
            'cores': quota_set['cores'],
        }}

    def show(self, req, id):
        context = req.environ['nova.context']
        try:
            db.sqlalchemy.api.authorize_project_context(context, id)
            return self._format_quota_set(id,
                                        quota.get_project_quotas(context, id))
        except exception.NotAuthorized:
            return webob.Response(status_int=403)

    def update(self, req, id, body):
        context = req.environ['nova.context']
        project_id = id
        resources = ['metadata_items', 'injected_file_content_bytes',
                'volumes', 'gigabytes', 'ram', 'floating_ips', 'instances',
                'injected_files', 'cores']
        for key in body['quota_set'].keys():
            if key in resources:
                value = int(body['quota_set'][key])
                try:
                    db.quota_update(context, project_id, key, value)
                except exception.ProjectQuotaNotFound:
                    db.quota_create(context, project_id, key, value)
                except exception.AdminRequired:
                    return webob.Response(status_int=403)
        return {'quota_set': quota.get_project_quotas(context, project_id)}

    def defaults(self, req, id):
        return self._format_quota_set(id, quota._get_default_quotas())


class Quotas(extensions.ExtensionDescriptor):

    def get_name(self):
        return "Quotas"

    def get_alias(self):
        return "os-quota-sets"

    def get_description(self):
        return "Quotas management support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/quotas-sets/api/v1.1"

    def get_updated(self):
        return "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                            QuotaSetsController(),
                                            member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources

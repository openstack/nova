# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
import nova.context
from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova import quota


QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)


authorize_update = extensions.extension_authorizer('compute', 'quotas:update')
authorize_show = extensions.extension_authorizer('compute', 'quotas:show')


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(object):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        result = dict(id=str(project_id))

        for resource in QUOTAS.resources:
            result[resource] = quota_set[resource]

        return dict(quota_set=result)

    def _validate_quota_limit(self, limit):
        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = _("Quota limit must be -1 or greater.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, usages=False):
        values = QUOTAS.get_project_quotas(context, id, usages=usages)

        if usages:
            return values
        else:
            return dict((k, v['limit']) for k, v in values.items())

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        try:
            nova.context.authorize_project_context(context, id)
            return self._format_quota_set(id, self._get_quotas(context, id))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize_update(context)
        project_id = id

        bad_keys = []
        for key in body['quota_set'].keys():
            if (key not in QUOTAS and
                    key != 'tenant_id' and
                    key != 'id'):
                bad_keys.append(key)

        if len(bad_keys) > 0:
            msg = _("Bad key(s) %s in quota_set") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        for key in body['quota_set'].keys():
            try:
                value = int(body['quota_set'][key])
            except (ValueError, TypeError):
                LOG.warn(_("Quota for %s should be integer.") % key)
                # NOTE(hzzhoushaoyu): Do not prevent valid value to be
                # updated. If raise BadRequest, some may be updated and
                # others may be not.
                continue
            self._validate_quota_limit(value)
            try:
                db.quota_update(context, project_id, key, value)
            except exception.ProjectQuotaNotFound:
                db.quota_create(context, project_id, key, value)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()
        return {'quota_set': self._get_quotas(context, id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        return self._format_quota_set(id, QUOTAS.get_defaults(context))


class Quotas(extensions.ExtensionDescriptor):
    """Quotas management support."""

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

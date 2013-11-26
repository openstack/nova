# Copyright 2012 OpenStack Foundation
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
from nova.openstack.common.gettextutils import _
from nova import quota


QUOTAS = quota.QUOTAS

ALIAS = "os-quota-class-sets"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class QuotaClassTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_class_set',
                                       selector='quota_class_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaClassSetsController(wsgi.Controller):

    def _format_quota_set(self, quota_class, quota_set):
        """Convert the quota object to a result dict."""

        result = dict(id=str(quota_class))

        for resource in QUOTAS.resources:
            result[resource] = quota_set[resource]

        return dict(quota_class_set=result)

    @extensions.expected_errors(403)
    @wsgi.serializers(xml=QuotaClassTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        try:
            nova.context.authorize_quota_class_context(context, id)
            return self._format_quota_set(id,
                                          QUOTAS.get_class_quotas(context, id))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @extensions.expected_errors((400, 403))
    @wsgi.serializers(xml=QuotaClassTemplate)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        quota_class = id
        if not self.is_valid_body(body, 'quota_class_set'):
            raise webob.exc.HTTPBadRequest("The request body invalid")
        quota_class_set = body['quota_class_set']
        for key in quota_class_set.keys():
            if key in QUOTAS:
                try:
                    value = int(quota_class_set[key])
                except ValueError:
                    msg = _("The value %(val)s of %(key)s isn't an "
                            "integer") % {'val': body['quota_class_set'][key],
                                          'key': key}
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                try:
                    db.quota_class_update(context, quota_class, key, value)
                except exception.QuotaClassNotFound:
                    db.quota_class_create(context, quota_class, key, value)
                except exception.AdminRequired:
                    raise webob.exc.HTTPForbidden()
        return self._format_quota_set(
            quota_class,
            QUOTAS.get_class_quotas(context, quota_class))


class QuotaClasses(extensions.V3APIExtensionBase):
    """Quota classes management support."""

    name = "QuotaClasses"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "quota-class-sets/api/v3")
    version = 1

    def get_resources(self):
        resources = [
            extensions.ResourceExtension(ALIAS, QuotaClassSetsController())]
        return resources

    def get_controller_extensions(self):
        return []

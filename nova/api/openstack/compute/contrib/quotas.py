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

import urlparse
import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova.db.sqlalchemy import api as sqlalchemy_api
from nova import exception
from nova import quota
from nova import utils


QUOTAS = quota.QUOTAS


def authorize_action(context, action_name):
    action = 'quotas:%s' % action_name
    extensions.extension_authorizer('compute', action)(context)


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
        """Convert the quota object to a result dict"""

        result = dict(id=str(project_id))

        for resource in QUOTAS.resources:
            result[resource] = quota_set[resource]

        return dict(quota_set=result)

    def _validate_quota_limit(self, limit, remain, quota):
        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = _("Quota limit must be -1 or greater.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Quota limit must be less than the remains of the project.
        if remain != -1 and remain < limit - quota:
            msg = _("Quota limit exceed the remains of the project.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, user_id=None, remaining=False,
                    usages=False):
        # Get the remaining quotas for a project.
        if remaining:
            values = QUOTAS.get_remaining_quotas(context, id)
            return values

        if user_id:
            # If user_id, return quotas for the given user.
            values = QUOTAS.get_user_quotas(context, user_id, id,
                                            usages=usages)
        else:
            values = QUOTAS.get_project_quotas(context, id, usages=usages)

        if usages:
            return values
        else:
            return dict((k, v['limit']) for k, v in values.items())

    def _request_params(self, req):
        qs = req.environ.get('QUERY_STRING', '')
        return urlparse.parse_qs(qs)

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_action(context, 'show')
        params = self._request_params(req)
        remaining = False
        if 'remaining' in params:
            remaining = utils.bool_from_str(params["remaining"][0])
        user_id = None
        if 'user_id' in params:
            user_id = params["user_id"][0]
        try:
            sqlalchemy_api.authorize_project_context(context, id)
            return self._format_quota_set(id,
                        self._get_quotas(context, id, user_id, remaining))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        params = self._request_params(req)
        project_id = id
        user_id = None
        remains = {}
        quotas = {}
        if 'user_id' in params:
            # Project admins are able to modify per-user quotas.
            authorize_action(context, 'update_for_user')
            user_id = params["user_id"][0]
            remains = self._get_quotas(context, project_id, remaining=True)
            quotas = db.quota_get_all_by_user(context, user_id, project_id)
        else:
            # Only admins are able to modify per-project quotas.
            authorize_action(context, 'update_for_project')

        for key in body['quota_set'].keys():
            if key in QUOTAS:
                value = int(body['quota_set'][key])
                try:
                    if user_id:
                        self._validate_quota_limit(value, remains.get(key, 0),
                                                   quotas.get(key, 0))
                        db.quota_update_for_user(context, user_id,
                                                 project_id, key, value)
                    else:
                        self._validate_quota_limit(value, remains.get(key, -1),
                                                   quotas.get(key, 0))
                        db.quota_update(context, project_id, key, value)
                except exception.ProjectQuotaNotFound:
                    db.quota_create(context, project_id, key, value)
                except exception.UserQuotaNotFound:
                    db.quota_create_for_user(context, user_id,
                                             project_id, key, value)
                except exception.AdminRequired:
                    raise webob.exc.HTTPForbidden()
        return {'quota_set': self._get_quotas(context, id, user_id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_action(context, 'show')
        return self._format_quota_set(id, QUOTAS.get_defaults(context))


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

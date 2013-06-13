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

import urlparse
import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
import nova.context
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova import quota


QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
NON_QUOTA_KEYS = ['tenant_id', 'id', 'force']


authorize_update = extensions.extension_authorizer('compute', 'quotas:update')
authorize_show = extensions.extension_authorizer('compute', 'quotas:show')
authorize_delete = extensions.extension_authorizer('compute', 'quotas:delete')


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(object):

    def __init__(self, ext_mgr):
        self.ext_mgr = ext_mgr

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        result = dict(id=str(project_id))

        for resource in QUOTAS.resources:
            result[resource] = quota_set[resource]

        return dict(quota_set=result)

    def _validate_quota_limit(self, limit, minimum, maximum):
        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = _("Quota limit must be -1 or greater.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if ((limit < minimum) and
           (maximum != -1 or (maximum == -1 and limit != -1))):
            msg = _("Quota limit must greater than %s.") % minimum
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if maximum != -1 and limit > maximum:
            msg = _("Quota limit must less than %s.") % maximum
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, user_id=None, usages=False):
        if user_id:
            values = QUOTAS.get_user_quotas(context, id, user_id,
                                            usages=usages)
        else:
            values = QUOTAS.get_project_quotas(context, id, usages=usages)

        if usages:
            return values
        else:
            return dict((k, v['limit']) for k, v in values.items())

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = None
        if self.ext_mgr.is_loaded('os-user-quotas'):
            user_id = params.get('user_id', [None])[0]
        try:
            nova.context.authorize_project_context(context, id)
            return self._format_quota_set(id,
                    self._get_quotas(context, id, user_id=user_id))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize_update(context)
        project_id = id

        bad_keys = []

        # By default, we can force update the quota if the extended
        # is not loaded
        force_update = True
        extended_loaded = False
        if self.ext_mgr.is_loaded('os-extended-quotas'):
            # force optional has been enabled, the default value of
            # force_update need to be changed to False
            extended_loaded = True
            force_update = False

        user_id = None
        if self.ext_mgr.is_loaded('os-user-quotas'):
            # Update user quotas only if the extended is loaded
            params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
            user_id = params.get('user_id', [None])[0]

        try:
            settable_quotas = QUOTAS.get_settable_quotas(context, project_id,
                                                         user_id=user_id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        for key, value in body['quota_set'].items():
            if (key not in QUOTAS and
                    key not in NON_QUOTA_KEYS):
                bad_keys.append(key)
                continue
            if key == 'force' and extended_loaded:
                # only check the force optional when the extended has
                # been loaded
                force_update = strutils.bool_from_string(value)
            elif key not in NON_QUOTA_KEYS and value:
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    msg = _("Quota '%(value)s' for %(key)s should be "
                            "integer.") % {'value': value, 'key': key}
                    LOG.warn(msg)
                    raise webob.exc.HTTPBadRequest(explanation=msg)

        LOG.debug(_("force update quotas: %s") % force_update)

        if len(bad_keys) > 0:
            msg = _("Bad key(s) %s in quota_set") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            quotas = self._get_quotas(context, id, user_id=user_id,
                                      usages=True)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        for key, value in body['quota_set'].items():
            if key in NON_QUOTA_KEYS or not value:
                continue
            # validate whether already used and reserved exceeds the new
            # quota, this check will be ignored if admin want to force
            # update
            value = int(value)
            if force_update is not True and value >= 0:
                quota_value = quotas.get(key)
                if quota_value and quota_value['limit'] >= 0:
                    quota_used = (quota_value['in_use'] +
                                  quota_value['reserved'])
                    LOG.debug(_("Quota %(key)s used: %(quota_used)s, "
                                "value: %(value)s."),
                              {'key': key, 'quota_used': quota_used,
                               'value': value})
                    if quota_used > value:
                        msg = (_("Quota value %(value)s for %(key)s are "
                                "greater than already used and reserved "
                                "%(quota_used)s") %
                                {'value': value, 'key': key,
                                 'quota_used': quota_used})
                        raise webob.exc.HTTPBadRequest(explanation=msg)

            minimum = settable_quotas[key]['minimum']
            maximum = settable_quotas[key]['maximum']
            self._validate_quota_limit(value, minimum, maximum)
            try:
                db.quota_create(context, project_id, key, value,
                                user_id=user_id)
            except exception.QuotaExists:
                db.quota_update(context, project_id, key, value,
                                user_id=user_id)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()
        return {'quota_set': self._get_quotas(context, id, user_id=user_id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        return self._format_quota_set(id, QUOTAS.get_defaults(context))

    def delete(self, req, id):
        if self.ext_mgr.is_loaded('os-extended-quotas'):
            context = req.environ['nova.context']
            authorize_delete(context)
            params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
            user_id = params.get('user_id', [None])[0]
            if user_id and not self.ext_mgr.is_loaded('os-user-quotas'):
                raise webob.exc.HTTPNotFound()
            try:
                nova.context.authorize_project_context(context, id)
                if user_id:
                    QUOTAS.destroy_all_by_project_and_user(context,
                                                           id, user_id)
                else:
                    QUOTAS.destroy_all_by_project(context, id)
                return webob.Response(status_int=202)
            except exception.NotAuthorized:
                raise webob.exc.HTTPForbidden()
        raise webob.exc.HTTPNotFound()


class Quotas(extensions.ExtensionDescriptor):
    """Quotas management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/compute/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                            QuotaSetsController(self.ext_mgr),
                                            member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources

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

import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.context
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova import quota
from nova import utils


ALIAS = "os-quota-sets"
QUOTAS = quota.QUOTAS
LOG = logging.getLogger(__name__)
FILTERED_QUOTAS = ['injected_files', 'injected_file_content_bytes',
                   'injected_file_path_bytes']
authorize_update = extensions.extension_authorizer('compute',
                                                   'v3:%s:update' % ALIAS)
authorize_show = extensions.extension_authorizer('compute',
                                                 'v3:%s:show' % ALIAS)
authorize_delete = extensions.extension_authorizer('compute',
                                                   'v3:%s:delete' % ALIAS)
authorize_detail = extensions.extension_authorizer('compute',
                                                   'v3:%s:detail' % ALIAS)


class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""
        quota_set.update(id=project_id)
        return dict(quota_set=quota_set)

    def _validate_quota_limit(self, limit, minimum, maximum):
        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = _("Quota limit must be -1 or greater.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if ((limit < minimum) and
           (maximum != -1 or (maximum == -1 and limit != -1))):
            msg = _("Quota limit must be greater than %s.") % minimum
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if maximum != -1 and limit > maximum:
            msg = _("Quota limit must be less than %s.") % maximum
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, user_id=None, usages=False):
        if user_id:
            values = QUOTAS.get_user_quotas(context, id, user_id,
                                            usages=usages)
        else:
            values = QUOTAS.get_project_quotas(context, id, usages=usages)
        values = dict((k, v) for k, v in values.items() if k not in
                      FILTERED_QUOTAS)

        if usages:
            return values
        else:
            return dict((k, v['limit']) for k, v in values.items())

    @extensions.expected_errors(403)
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]
        try:
            nova.context.authorize_project_context(context, id)
            return self._format_quota_set(id,
                    self._get_quotas(context, id, user_id=user_id))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @extensions.expected_errors(403)
    def detail(self, req, id):
        context = req.environ['nova.context']
        authorize_detail(context)
        user_id = req.GET.get('user_id', None)
        try:
            nova.context.authorize_project_context(context, id)
            return self._format_quota_set(id, self._get_quotas(context, id,
                                                               user_id=user_id,
                                                               usages=True))
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

    @extensions.expected_errors((400, 403))
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize_update(context)
        project_id = id
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]

        bad_keys = []
        force_update = False

        if not self.is_valid_body(body, 'quota_set'):
            msg = _("quota_set not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        quota_set = body['quota_set']

        for key, value in quota_set.items():
            if ((key not in QUOTAS or key in FILTERED_QUOTAS)
                 and key != 'force'):
                bad_keys.append(key)
                continue
            if key == 'force':
                force_update = strutils.bool_from_string(value)
            elif key != 'force' and value:
                try:
                    value = utils.validate_integer(
                        value, key)
                except exception.InvalidInput as e:
                    LOG.warn(e.format_message())
                    raise webob.exc.HTTPBadRequest(
                        explanation=e.format_message())

        if len(bad_keys) > 0:
            msg = _("Bad key(s) %s in quota_set") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            settable_quotas = QUOTAS.get_settable_quotas(context, project_id,
                                                         user_id=user_id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        try:
            quotas = self._get_quotas(context, id, user_id=user_id,
                                      usages=True)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        LOG.debug(_("Force update quotas: %s"), force_update)

        for key, value in body['quota_set'].iteritems():
            if key == 'force' or (not value and value != 0):
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
                                "less than already used and reserved "
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
        return self._format_quota_set(id, self._get_quotas(context, id,
                                                           user_id=user_id))

    @extensions.expected_errors(())
    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        values = QUOTAS.get_defaults(context)
        values = dict((k, v) for k, v in values.items() if k not in
                      FILTERED_QUOTAS)
        return self._format_quota_set(id, values)

    @extensions.expected_errors(403)
    @wsgi.response(204)
    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize_delete(context)
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]
        try:
            nova.context.authorize_project_context(context, id)
            if user_id:
                QUOTAS.destroy_all_by_project_and_user(context,
                                                       id, user_id)
            else:
                QUOTAS.destroy_all_by_project(context, id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()


class QuotaSets(extensions.V3APIExtensionBase):
    """Quotas management support."""

    name = "Quotas"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(ALIAS,
                                            QuotaSetsController(),
                                            member_actions={'defaults': 'GET',
                                                            'detail': 'GET'})
        resources.append(res)

        return resources

    def get_controller_extensions(self):
        return []

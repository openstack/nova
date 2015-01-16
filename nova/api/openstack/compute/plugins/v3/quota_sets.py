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

from oslo.utils import strutils
import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack.compute.schemas.v3 import quota_sets
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
import nova.context
from nova import exception
from nova.i18n import _
from nova import objects
from nova import quota


ALIAS = "os-quota-sets"
QUOTAS = quota.QUOTAS
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
        quota_set.update(id=str(project_id))
        return dict(quota_set=quota_set)

    def _validate_quota_limit(self, resource, limit, minimum, maximum):
        # NOTE: -1 is a flag value for unlimited
        if limit < -1:
            msg = (_("Quota limit %(limit)s for %(resource)s "
                     "must be -1 or greater.") %
                   {'limit': limit, 'resource': resource})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        def conv_inf(value):
            return float("inf") if value == -1 else value

        if conv_inf(limit) < conv_inf(minimum):
            msg = (_("Quota limit %(limit)s for %(resource)s must "
                     "be greater than or equal to already used and "
                     "reserved %(minimum)s.") %
                   {'limit': limit, 'resource': resource, 'minimum': minimum})
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if conv_inf(limit) > conv_inf(maximum):
            msg = (_("Quota limit %(limit)s for %(resource)s must be "
                     "less than or equal to %(maximum)s.") %
                   {'limit': limit, 'resource': resource, 'maximum': maximum})
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
            return {k: v['limit'] for k, v in values.items()}

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
        except exception.Forbidden:
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
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()

    @extensions.expected_errors((400, 403))
    @validation.schema(quota_sets.update)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize_update(context)
        project_id = id
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]

        quota_set = body['quota_set']
        force_update = strutils.bool_from_string(quota_set.get('force',
                                                               'False'))

        try:
            settable_quotas = QUOTAS.get_settable_quotas(context, project_id,
                                                         user_id=user_id)
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()

        for key, value in body['quota_set'].iteritems():
            if key == 'force' or (not value and value != 0):
                continue
            # validate whether already used and reserved exceeds the new
            # quota, this check will be ignored if admin want to force
            # update
            value = int(value)
            if not force_update:
                minimum = settable_quotas[key]['minimum']
                maximum = settable_quotas[key]['maximum']
                self._validate_quota_limit(key, value, minimum, maximum)

            try:
                objects.Quotas.create_limit(context, project_id,
                                            key, value, user_id=user_id)
            except exception.QuotaExists:
                objects.Quotas.update_limit(context, project_id,
                                            key, value, user_id=user_id)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()
        return self._format_quota_set(id, self._get_quotas(context, id,
                                                           user_id=user_id))

    @extensions.expected_errors(())
    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        values = QUOTAS.get_defaults(context)
        return self._format_quota_set(id, values)

    # TODO(oomichi): Here should be 204(No Content) instead of 202 by v2.1
    # +microversions because the resource quota-set has been deleted completely
    # when returning a response.
    @extensions.expected_errors(403)
    @wsgi.response(202)
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
        except exception.Forbidden:
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

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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.context
from nova import exception
from nova.i18n import _
from nova import objects
from nova import quota
from nova import utils


QUOTAS = quota.QUOTAS
NON_QUOTA_KEYS = ['tenant_id', 'id', 'force']

# Quotas that are only enabled by specific extensions
EXTENDED_QUOTAS = {'server_groups': 'os-server-group-quotas',
                   'server_group_members': 'os-server-group-quotas'}

authorize_update = extensions.extension_authorizer('compute', 'quotas:update')
authorize_show = extensions.extension_authorizer('compute', 'quotas:show')
authorize_delete = extensions.extension_authorizer('compute', 'quotas:delete')


class QuotaSetsController(wsgi.Controller):

    supported_quotas = []

    def __init__(self, ext_mgr):
        self.ext_mgr = ext_mgr
        self.supported_quotas = QUOTAS.resources
        for resource, extension in EXTENDED_QUOTAS.items():
            if not self.ext_mgr.is_loaded(extension):
                self.supported_quotas.remove(resource)

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        if project_id:
            result = dict(id=str(project_id))
        else:
            result = {}

        for resource in self.supported_quotas:
            if resource in quota_set:
                result[resource] = quota_set[resource]

        return dict(quota_set=result)

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
            return dict((k, v['limit']) for k, v in values.items())

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
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()

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
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()

        if not self.is_valid_body(body, 'quota_set'):
            msg = _("quota_set not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        quota_set = body['quota_set']

        for key, value in quota_set.items():
            if (key not in self.supported_quotas
                and key not in NON_QUOTA_KEYS):
                bad_keys.append(key)
                continue
            if key == 'force' and extended_loaded:
                # only check the force optional when the extended has
                # been loaded
                force_update = strutils.bool_from_string(value)
            elif key not in NON_QUOTA_KEYS and value:
                try:
                    value = utils.validate_integer(value, key)
                except exception.InvalidInput as e:
                    raise webob.exc.HTTPBadRequest(
                        explanation=e.format_message())

        if bad_keys:
            msg = _("Bad key(s) %s in quota_set") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        for key, value in quota_set.items():
            if key in NON_QUOTA_KEYS or (not value and value != 0):
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
        values = self._get_quotas(context, id, user_id=user_id)
        return self._format_quota_set(None, values)

    def defaults(self, req, id):
        context = req.environ['nova.context']
        authorize_show(context)
        values = QUOTAS.get_defaults(context)
        return self._format_quota_set(id, values)

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
            except exception.Forbidden:
                raise webob.exc.HTTPForbidden()
        raise webob.exc.HTTPNotFound()


class Quotas(extensions.ExtensionDescriptor):
    """Quotas management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/compute/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                            QuotaSetsController(self.ext_mgr),
                                            member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources

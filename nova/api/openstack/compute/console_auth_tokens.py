# Copyright 2013 Cloudbase Solutions Srl
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
import nova.conf
from nova import context as nova_context
from nova.i18n import _
from nova import objects
from nova.policies import console_auth_tokens as cat_policies

CONF = nova.conf.CONF


class ConsoleAuthTokensController(wsgi.Controller):

    def _show(self, req, id, rdp_only):
        """Checks a console auth token and returns the related connect info."""
        context = req.environ['nova.context']
        context.can(cat_policies.BASE_POLICY_NAME)

        token = id
        if not token:
            msg = _("token not provided")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        connect_info = None

        results = nova_context.scatter_gather_skip_cell0(
            context, objects.ConsoleAuthToken.validate, token)
        # NOTE(melwitt): Console token auths are stored in cell databases,
        # but with only the token as a request param, we can't know which
        # cell database contains the token's corresponding connection info.
        # So, we must query all cells for the info and we can break the
        # loop as soon as we find a result because the token is associated
        # with one instance, which can only be in one cell.
        for result in results.values():
            if not nova_context.is_cell_failure_sentinel(result):
                connect_info = result
                break

        if not connect_info:
            raise webob.exc.HTTPNotFound(explanation=_("Token not found"))

        console_type = connect_info.console_type

        if rdp_only and console_type != "rdp-html5":
            raise webob.exc.HTTPUnauthorized(
                explanation=_("The requested console type details are not "
                              "accessible"))

        return {'console': {
            'instance_uuid': connect_info.instance_uuid,
            'host': connect_info.host,
            'port': connect_info.port,
            'internal_access_path': connect_info.internal_access_path,
        }}

    @wsgi.Controller.api_version("2.1", "2.30")
    @wsgi.expected_errors((400, 401, 404))
    def show(self, req, id):
        return self._show(req, id, True)

    @wsgi.Controller.api_version("2.31")  # noqa
    @wsgi.expected_errors((400, 404))
    def show(self, req, id):
        return self._show(req, id, False)

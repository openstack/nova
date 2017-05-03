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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova.i18n import _
from nova.policies import console_auth_tokens as cat_policies


class ConsoleAuthTokensController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        self._consoleauth_rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        super(ConsoleAuthTokensController, self).__init__(*args, **kwargs)

    def _show(self, req, id, rdp_only):
        """Checks a console auth token and returns the related connect info."""
        context = req.environ['nova.context']
        context.can(cat_policies.BASE_POLICY_NAME)

        token = id
        if not token:
            msg = _("token not provided")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        connect_info = self._consoleauth_rpcapi.check_token(context, token)
        if not connect_info:
            raise webob.exc.HTTPNotFound(explanation=_("Token not found"))

        console_type = connect_info.get('console_type')

        if rdp_only and console_type != "rdp-html5":
            raise webob.exc.HTTPUnauthorized(
                explanation=_("The requested console type details are not "
                              "accessible"))

        return {'console':
                {i: connect_info[i]
                 for i in ['instance_uuid', 'host', 'port',
                           'internal_access_path']
                 if i in connect_info}}

    @wsgi.Controller.api_version("2.1", "2.30")
    @extensions.expected_errors((400, 401, 404))
    def show(self, req, id):
        return self._show(req, id, True)

    @wsgi.Controller.api_version("2.31")  # noqa
    @extensions.expected_errors((400, 404))
    def show(self, req, id):
        return self._show(req, id, False)

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


authorize = extensions.extension_authorizer('compute', 'console_auth_tokens')


class ConsoleAuthTokensController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        self._consoleauth_rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        super(ConsoleAuthTokensController, self).__init__(*args, **kwargs)

    def show(self, req, id):
        """Checks a console auth token and returns the related connect info."""
        context = req.environ['nova.context']
        authorize(context)

        token = id
        connect_info = self._consoleauth_rpcapi.check_token(context, token)
        if not connect_info:
            raise webob.exc.HTTPNotFound(explanation=_("Token not found"))

        console_type = connect_info.get('console_type')
        # This is currently required only for RDP consoles
        if console_type != "rdp-html5":
            raise webob.exc.HTTPUnauthorized(
                explanation=_("The requested console type details are not "
                              "accessible"))

        return {'console':
                {i: connect_info[i]
                 for i in ['instance_uuid', 'host', 'port',
                           'internal_access_path']
                 if i in connect_info}}


class Console_auth_tokens(extensions.ExtensionDescriptor):
    """Console token authentication support."""
    name = "ConsoleAuthTokens"
    alias = "os-console-auth-tokens"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "consoles-auth-tokens/api/v2")
    updated = "2013-08-13T00:00:00Z"

    def get_resources(self):
        controller = ConsoleAuthTokensController()
        ext = extensions.ResourceExtension('os-console-auth-tokens',
                                           controller)
        return [ext]

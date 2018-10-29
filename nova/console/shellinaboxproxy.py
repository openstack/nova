# Copyright (c) 2018 OpenStack Foundation
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

from nova import config
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context

STATIC_FILES_EXT = ('.js', '.css', '.html', '.ico', '.png', '.gif')


class NovaShellInaBoxProxy(object):
    """Class that injects token validation routine into proxy logic.
    """

    def path_includes_static_files(self):
        """Returns True if requested path includes static files.
        """
        for extension in STATIC_FILES_EXT:
            if extension in self.path:
                return True

    def response(self, flow):
        """Validate the token and give 403 if not found or not valid.
        """
        if self.method == "GET" and not self.path_includes_static_files():

            if not self.token:
                # No token found
                flow.response.status_code = 403
                flow.response.content = b"No token provided."
            else:
                # Validate the token
                ctxt = context.get_admin_context()
                rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()

                if not rpcapi.check_token(ctxt, token=self.token):
                    # Token not valid
                    flow.response.status_code = 403
                    flow.response.content = ("The token has expired "
                                             "or invalid.")

    def request(self, flow):
        """Save the token, method and path that came with request.
        """
        self.token = flow.request.query.get("token", "")
        self.method = flow.request.method
        self.path = flow.request.path


def start():
    """Entrypoint. Configures rpc first, otherwise cannot validate token.
    """
    config.parse_args([])  # we need this to configure rpc
    return NovaShellInaBoxProxy()

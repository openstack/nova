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

from nova.compute import rpcapi as compute_rpcapi
from nova import config
from nova.console.websocketproxy import NovaProxyRequestHandlerBase
from nova import context
from nova import exception

STATIC_FILES_EXT = ('.js', '.css', '.html', '.ico', '.png', '.gif')


class NovaShellInaBoxProxy(NovaProxyRequestHandlerBase):
    """Class that injects token validation routine into proxy logic."""

    def __init__(self):
        self._compute_rpcapi = None

    @property
    def compute_rpcapi(self):
        # This is copied from NovaProxyRequestHandler, just to avoid
        # extending that class (because it inherits
        # websockify.ProxyRequestHandler in addition and we don't need that).
        # For upgrades we should have a look again if anything changed there,
        # that we might need to also include here.
        if not self._compute_rpcapi:
            self._compute_rpcapi = compute_rpcapi.ComputeAPI()
        return self._compute_rpcapi

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
                try:
                    super(NovaShellInaBoxProxy, self)._get_connect_info(
                        ctxt, self.token)
                except exception.InvalidToken:
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

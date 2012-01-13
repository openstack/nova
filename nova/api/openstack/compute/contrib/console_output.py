# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2011 Grid Dynamics
# Copyright 2011 Eldar Nugaev, Kirill Shileev, Ilya Alekseyev
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
#    under the License

import webob

from nova import compute
from nova import exception
from nova import log as logging
from nova.api.openstack import extensions


LOG = logging.getLogger('nova.api.openstack.compute.contrib.console_output')


class Console_output(extensions.ExtensionDescriptor):
    """Console log output support, with tailing ability."""

    name = "Console_output"
    alias = "os-console-output"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "os-console-output/api/v2"
    updated = "2011-12-08T00:00:00+00:00"

    def __init__(self, ext_mgr):
        self.compute_api = compute.API()
        super(Console_output, self).__init__(ext_mgr)

    def get_console_output(self, input_dict, req, server_id):
        """Get text console output."""
        context = req.environ['nova.context']

        try:
            instance = self.compute_api.routing_get(context, server_id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound(_('Instance not found'))

        try:
            length = input_dict['os-getConsoleOutput'].get('length')
        except (TypeError, KeyError):
            raise webob.exc.HTTPBadRequest(_('Malformed request body'))

        try:
            output = self.compute_api.get_console_output(context,
                                                         instance,
                                                         length)
        except exception.ApiError, e:
            raise webob.exc.HTTPBadRequest(explanation=e.message)
        except exception.NotAuthorized, e:
            raise webob.exc.HTTPUnauthorized()

        return {'output': output}

    def get_actions(self):
        """Return the actions the extension adds, as required by contract."""
        actions = [extensions.ActionExtension("servers", "os-getConsoleOutput",
                                              self.get_console_output)]

        return actions

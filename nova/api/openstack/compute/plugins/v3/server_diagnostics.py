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

import webob.exc

from nova.api.openstack import extensions
from nova import compute
from nova import exception


ALIAS = "os-server-diagnostics"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class ServerDiagnosticsController(object):
    @extensions.expected_errors(404)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        authorize(context)
        compute_api = compute.API()
        try:
            instance = compute_api.get(context, server_id, want_objects=True)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return compute_api.get_diagnostics(context, instance)


class ServerDiagnostics(extensions.V3APIExtensionBase):
    """Allow Admins to view server diagnostics through server action."""

    name = "ServerDiagnostics"
    alias = ALIAS
    version = 1

    def get_resources(self):
        parent_def = {'member_name': 'server', 'collection_name': 'servers'}
        resources = [
            extensions.ResourceExtension(ALIAS,
                                         ServerDiagnosticsController(),
                                         parent=parent_def)]
        return resources

    def get_controller_extensions(self):
        return []

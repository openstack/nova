#   Copyright 2012 Nebula, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Flavor Disabled API extension."""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi


authorize = extensions.soft_extension_authorizer('compute', 'flavor_disabled')


class FlavorDisabledController(wsgi.Controller):
    def _extend_flavors(self, req, flavors):
        for flavor in flavors:
            db_flavor = req.get_db_flavor(flavor['id'])
            key = "%s:disabled" % Flavor_disabled.alias
            flavor[key] = db_flavor['disabled']

    def _show(self, req, resp_obj):
        if not authorize(req.environ['nova.context']):
            return
        if 'flavor' in resp_obj.obj:
            self._extend_flavors(req, [resp_obj.obj['flavor']])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        return self._show(req, resp_obj)

    @wsgi.extends(action='create')
    def create(self, req, resp_obj, body):
        return self._show(req, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        if not authorize(req.environ['nova.context']):
            return
        self._extend_flavors(req, list(resp_obj.obj['flavors']))


class Flavor_disabled(extensions.ExtensionDescriptor):
    """Support to show the disabled status of a flavor."""

    name = "FlavorDisabled"
    alias = "OS-FLV-DISABLED"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "flavor_disabled/api/v1.1")
    updated = "2012-08-29T00:00:00Z"

    def get_controller_extensions(self):
        controller = FlavorDisabledController()
        extension = extensions.ControllerExtension(self, 'flavors', controller)
        return [extension]

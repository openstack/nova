# Copyright 2012 OpenStack Foundation
# Copyright 2011 Canonical Ltd.
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

"""The Flavor extra data extension

OpenStack API version 1.1 lists "name", "ram", "disk", "vcpus" as flavor
attributes.  This extension adds to that list:

- OS-FLV-EXT-DATA:ephemeral
"""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi


authorize = extensions.soft_extension_authorizer('compute', 'flavorextradata')


class FlavorextradataController(wsgi.Controller):
    def _extend_flavors(self, req, flavors):
        for flavor in flavors:
            db_flavor = req.get_db_flavor(flavor['id'])
            key = "%s:ephemeral" % Flavorextradata.alias
            flavor[key] = db_flavor['ephemeral_gb']

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


class Flavorextradata(extensions.ExtensionDescriptor):
    """Provide additional data for flavors."""

    name = "FlavorExtraData"
    alias = "OS-FLV-EXT-DATA"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "flavor_extra_data/api/v1.1")
    updated = "2011-09-14T00:00:00Z"

    def get_controller_extensions(self):
        controller = FlavorextradataController()
        extension = extensions.ControllerExtension(self, 'flavors', controller)
        return [extension]

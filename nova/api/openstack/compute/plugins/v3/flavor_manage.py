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

from nova.api.openstack.compute.schemas.v3 import flavor_manage
from nova.api.openstack.compute.views import flavors as flavors_view
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import flavors
from nova import exception

ALIAS = "os-flavor-manage"

authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class FlavorManageController(wsgi.Controller):
    """The Flavor Lifecycle API controller for the OpenStack API."""
    _view_builder_class = flavors_view.V3ViewBuilder

    def __init__(self):
        super(FlavorManageController, self).__init__()

    # NOTE(oomichi): Return 202 for backwards compatibility but should be
    # 204 as this operation complete the deletion of aggregate resource and
    # return no response body.
    @wsgi.response(202)
    @extensions.expected_errors((404))
    @wsgi.action("delete")
    def _delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)

        try:
            flavor = flavors.get_flavor_by_flavor_id(
                    id, ctxt=context, read_deleted="no")
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        flavors.destroy(flavor['name'])

    # NOTE(oomichi): Return 200 for backwards compatibility but should be 201
    # as this operation complete the creation of flavor resource.
    @wsgi.action("create")
    @extensions.expected_errors((400, 409, 500))
    @validation.schema(flavor_manage.create)
    def _create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)

        vals = body['flavor']

        name = vals['name']
        flavorid = vals.get('id')
        memory = vals['ram']
        vcpus = vals['vcpus']
        root_gb = vals['disk']
        ephemeral_gb = vals.get('OS-FLV-EXT-DATA:ephemeral', 0)
        swap = vals.get('swap', 0)
        rxtx_factor = vals.get('rxtx_factor', 1.0)
        is_public = vals.get('os-flavor-access:is_public', True)

        try:
            flavor = flavors.create(name, memory, vcpus, root_gb,
                                    ephemeral_gb=ephemeral_gb,
                                    flavorid=flavorid, swap=swap,
                                    rxtx_factor=rxtx_factor,
                                    is_public=is_public)
            # NOTE(gmann): For backward compatibility, non public flavor
            # access is not being added for created tenant. Ref -bug/1209101
            req.cache_db_flavor(flavor)
        except (exception.FlavorExists,
                exception.FlavorIdExists) as err:
            raise webob.exc.HTTPConflict(explanation=err.format_message())
        except exception.FlavorCreateFailed as err:
            raise webob.exc.HTTPInternalServerError(explanation=
                err.format_message())

        return self._view_builder.show(req, flavor)


class FlavorManage(extensions.V3APIExtensionBase):
    """Flavor create/delete API support."""

    name = "FlavorManage"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = FlavorManageController()
        extension = extensions.ControllerExtension(self, 'flavors', controller)
        return [extension]

    def get_resources(self):
        return []

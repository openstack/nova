# Copyright (c) 2011 OpenStack Foundation
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

"""The flavor access extension."""

import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import flavor_access
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova.i18n import _
from nova import objects

ALIAS = 'os-flavor-access'
soft_authorize = extensions.os_compute_soft_authorizer(ALIAS)
authorize = extensions.os_compute_authorizer(ALIAS)


def _marshall_flavor_access(flavor):
    rval = []
    for project_id in flavor.projects:
        rval.append({'flavor_id': flavor.flavorid,
                     'tenant_id': project_id})

    return {'flavor_access': rval}


class FlavorAccessController(wsgi.Controller):
    """The flavor access API controller for the OpenStack API."""

    def __init__(self):
        super(FlavorAccessController, self).__init__()

    @extensions.expected_errors(404)
    def index(self, req, flavor_id):
        context = req.environ['nova.context']
        authorize(context)

        flavor = common.get_flavor(context, flavor_id)

        # public flavor to all projects
        if flavor.is_public:
            explanation = _("Access list not available for public flavors.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        # private flavor to listed projects only
        return _marshall_flavor_access(flavor)


class FlavorActionController(wsgi.Controller):
    """The flavor access API controller for the OpenStack API."""
    def _extend_flavor(self, flavor_rval, flavor_ref):
        key = "%s:is_public" % (FlavorAccess.alias)
        flavor_rval[key] = flavor_ref['is_public']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if soft_authorize(context):
            db_flavor = req.get_db_flavor(id)

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if soft_authorize(context):
            flavors = list(resp_obj.obj['flavors'])
            for flavor_rval in flavors:
                db_flavor = req.get_db_flavor(flavor_rval['id'])
                self._extend_flavor(flavor_rval, db_flavor)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['nova.context']
        if soft_authorize(context):
            db_flavor = req.get_db_flavor(resp_obj.obj['flavor']['id'])

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.action("addTenantAccess")
    @validation.schema(flavor_access.add_tenant_access)
    def _add_tenant_access(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action="add_tenant_access")

        vals = body['addTenantAccess']
        tenant = vals['tenant']

        flavor = common.get_flavor(context, id)

        try:
            if api_version_request.is_supported(req, min_version='2.7'):
                if flavor.is_public:
                    exp = _("Can not add access to a public flavor.")
                    raise webob.exc.HTTPConflict(explanation=exp)
            flavor.add_access(tenant)
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.FlavorAccessExists as err:
            raise webob.exc.HTTPConflict(explanation=err.format_message())
        except exception.AdminRequired as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        return _marshall_flavor_access(flavor)

    @extensions.expected_errors((400, 403, 404))
    @wsgi.action("removeTenantAccess")
    @validation.schema(flavor_access.remove_tenant_access)
    def _remove_tenant_access(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action="remove_tenant_access")

        vals = body['removeTenantAccess']
        tenant = vals['tenant']

        flavor = objects.Flavor(context=context, flavorid=id)
        try:
            flavor.remove_access(tenant)
        except (exception.FlavorAccessNotFound,
                exception.FlavorNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.AdminRequired as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        return _marshall_flavor_access(flavor)


class FlavorAccess(extensions.V21APIExtensionBase):
    """Flavor access support."""

    name = "FlavorAccess"
    alias = ALIAS
    version = 1

    def get_resources(self):
        res = extensions.ResourceExtension(
            ALIAS,
            controller=FlavorAccessController(),
            parent=dict(member_name='flavor', collection_name='flavors'))

        return [res]

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(
                self, 'flavors', FlavorActionController())

        return [extension]

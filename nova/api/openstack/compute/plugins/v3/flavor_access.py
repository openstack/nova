# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.api.openstack.compute.schemas.v3 import flavor_access_schema
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api import validation
from nova import exception
from nova.objects import flavor as flavor_obj
from nova.openstack.common.gettextutils import _

ALIAS = 'flavor-access'
soft_authorize = extensions.soft_extension_authorizer('compute',
                                                      'v3:' + ALIAS)
authorize = extensions.extension_authorizer('compute', 'v3:%s' % ALIAS)


def make_flavor(elem):
    elem.set('{%s}is_public' % FlavorAccess.namespace,
             '%s:is_public' % FlavorAccess.alias)


def make_flavor_access(elem):
    elem.set('flavor_id')
    elem.set('tenant_id')


class FlavorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor', selector='flavor')
        make_flavor(root)
        alias = FlavorAccess.alias
        namespace = FlavorAccess.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class FlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem)
        alias = FlavorAccess.alias
        namespace = FlavorAccess.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class FlavorAccessTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor_access')
        elem = xmlutil.SubTemplateElement(root, 'access',
                                          selector='flavor_access')
        make_flavor_access(elem)
        return xmlutil.MasterTemplate(root, 1)


def _marshall_flavor_access(flavor):
    rval = []
    for project_id in flavor.projects:
        rval.append({'flavor_id': flavor.flavorid,
                     'tenant_id': project_id})

    return {'flavor_access': rval}


class FlavorAccessController(object):
    """The flavor access API controller for the OpenStack API."""

    def __init__(self):
        super(FlavorAccessController, self).__init__()

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=FlavorAccessTemplate)
    def index(self, req, flavor_id):
        context = req.environ['nova.context']
        authorize(context)

        try:
            flavor = flavor_obj.Flavor.get_by_flavor_id(context, flavor_id)
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        # public flavor to all projects
        if flavor.is_public:
            explanation = _("Access list not available for public flavors.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        # private flavor to listed projects only
        return _marshall_flavor_access(flavor)


class FlavorActionController(wsgi.Controller):
    """The flavor access API controller for the OpenStack API."""
    def _get_flavor_refs(self, context):
        """Return a dictionary mapping flavorid to flavor_ref."""

        flavors = flavor_obj.FlavorList.get_all(context)
        rval = {}
        for flavor in flavors:
            rval[flavor.flavorid] = flavor
        return rval

    def _extend_flavor(self, flavor_rval, flavor_ref):
        key = "%s:is_public" % (FlavorAccess.alias)
        flavor_rval[key] = flavor_ref['is_public']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorTemplate())
            db_flavor = req.get_db_flavor(id)

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorsTemplate())

            flavors = list(resp_obj.obj['flavors'])
            for flavor_rval in flavors:
                db_flavor = req.get_db_flavor(flavor_rval['id'])
                self._extend_flavor(flavor_rval, db_flavor)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['nova.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorTemplate())

            db_flavor = req.get_db_flavor(resp_obj.obj['flavor']['id'])

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @extensions.expected_errors((400, 403, 404, 409))
    @wsgi.serializers(xml=FlavorAccessTemplate)
    @wsgi.action("add_tenant_access")
    @validation.schema(request_body_schema=
                       flavor_access_schema.add_tenant_access)
    def _add_tenant_access(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action="add_tenant_access")

        vals = body['add_tenant_access']
        tenant = vals['tenant_id']

        flavor = flavor_obj.Flavor(context=context, flavorid=id)
        try:
            flavor.add_access(tenant)
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.FlavorAccessExists as err:
            raise webob.exc.HTTPConflict(explanation=err.format_message())
        except exception.AdminRequired as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        return _marshall_flavor_access(flavor)

    @extensions.expected_errors((400, 403, 404))
    @wsgi.serializers(xml=FlavorAccessTemplate)
    @wsgi.action("remove_tenant_access")
    @validation.schema(request_body_schema=
                       flavor_access_schema.remove_tenant_access)
    def _remove_tenant_access(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action="remove_tenant_access")

        vals = body['remove_tenant_access']
        tenant = vals['tenant_id']

        flavor = flavor_obj.Flavor(context=context, flavorid=id)
        try:
            flavor.remove_access(tenant)
        except (exception.FlavorAccessNotFound,
                exception.FlavorNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.AdminRequired as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        return _marshall_flavor_access(flavor)


class FlavorAccess(extensions.V3APIExtensionBase):
    """Flavor access support."""

    name = "FlavorAccess"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/core/%s/api/v3" % ALIAS
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

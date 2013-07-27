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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import flavors
from nova import exception
from nova.openstack.common.gettextutils import _


authorize = extensions.soft_extension_authorizer('compute', 'flavor_access')


def make_flavor(elem):
    elem.set('{%s}is_public' % Flavor_access.namespace,
             '%s:is_public' % Flavor_access.alias)


def make_flavor_access(elem):
    elem.set('flavor_id')
    elem.set('tenant_id')


class FlavorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor', selector='flavor')
        make_flavor(root)
        alias = Flavor_access.alias
        namespace = Flavor_access.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class FlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem)
        alias = Flavor_access.alias
        namespace = Flavor_access.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class FlavorAccessTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor_access')
        elem = xmlutil.SubTemplateElement(root, 'access',
                                          selector='flavor_access')
        make_flavor_access(elem)
        return xmlutil.MasterTemplate(root, 1)


def _marshall_flavor_access(flavor_id):
    rval = []
    try:
        access_list = flavors.\
                      get_flavor_access_by_flavor_id(flavor_id)
    except exception.FlavorNotFound:
        explanation = _("Flavor not found.")
        raise webob.exc.HTTPNotFound(explanation=explanation)

    for access in access_list:
        rval.append({'flavor_id': flavor_id,
                     'tenant_id': access['project_id']})

    return {'flavor_access': rval}


class FlavorAccessController(object):
    """The flavor access API controller for the OpenStack API."""

    def __init__(self):
        super(FlavorAccessController, self).__init__()

    @wsgi.serializers(xml=FlavorAccessTemplate)
    def index(self, req, flavor_id):
        context = req.environ['nova.context']
        authorize(context)

        try:
            flavor = flavors.get_flavor_by_flavor_id(flavor_id, ctxt=context)
        except exception.FlavorNotFound:
            explanation = _("Flavor not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        # public flavor to all projects
        if flavor['is_public']:
            explanation = _("Access list not available for public flavors.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        # private flavor to listed projects only
        return _marshall_flavor_access(flavor_id)


class FlavorActionController(wsgi.Controller):
    """The flavor access API controller for the OpenStack API."""

    def _check_body(self, body):
        if body is None or body == "":
            raise webob.exc.HTTPBadRequest(explanation=_("No request body"))

    def _get_flavor_refs(self, context):
        """Return a dictionary mapping flavorid to flavor_ref."""

        flavor_refs = flavors.get_all_flavors(context)
        rval = {}
        for name, obj in flavor_refs.iteritems():
            rval[obj['flavorid']] = obj
        return rval

    def _extend_flavor(self, flavor_rval, flavor_ref):
        key = "%s:is_public" % (Flavor_access.alias)
        flavor_rval[key] = flavor_ref['is_public']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorTemplate())
            db_flavor = req.get_db_flavor(id)

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorsTemplate())

            flavors = list(resp_obj.obj['flavors'])
            for flavor_rval in flavors:
                db_flavor = req.get_db_flavor(flavor_rval['id'])
                self._extend_flavor(flavor_rval, db_flavor)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorTemplate())

            db_flavor = req.get_db_flavor(resp_obj.obj['flavor']['id'])

            self._extend_flavor(resp_obj.obj['flavor'], db_flavor)

    @wsgi.serializers(xml=FlavorAccessTemplate)
    @wsgi.action("addTenantAccess")
    def _addTenantAccess(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        self._check_body(body)

        vals = body['addTenantAccess']
        tenant = vals['tenant']

        try:
            flavors.add_flavor_access(id, tenant, context)
        except exception.FlavorAccessExists as err:
            raise webob.exc.HTTPConflict(explanation=err.format_message())

        return _marshall_flavor_access(id)

    @wsgi.serializers(xml=FlavorAccessTemplate)
    @wsgi.action("removeTenantAccess")
    def _removeTenantAccess(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        self._check_body(body)

        vals = body['removeTenantAccess']
        tenant = vals['tenant']

        try:
            flavors.remove_flavor_access(id, tenant, context)
        except exception.FlavorAccessNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        return _marshall_flavor_access(id)


class Flavor_access(extensions.ExtensionDescriptor):
    """Flavor access support."""

    name = "FlavorAccess"
    alias = "os-flavor-access"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "flavor_access/api/v2")
    updated = "2012-08-01T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-flavor-access',
            controller=FlavorAccessController(),
            parent=dict(member_name='flavor', collection_name='flavors'))
        resources.append(res)

        return resources

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(
                self, 'flavors', FlavorActionController())

        return [extension]

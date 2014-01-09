# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 University of Southern California
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

"""The instance type extra specs extension."""

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _


authorize = extensions.extension_authorizer('compute', 'flavorextraspecs')


class ExtraSpecsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        extra_specs_dict = xmlutil.make_flat_dict('extra_specs', colon_ns=True)
        return xmlutil.MasterTemplate(extra_specs_dict, 1)


class ExtraSpecTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector(xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('extra_spec', selector=sel)
        root.set('key', 0)
        root.text = 1
        return xmlutil.MasterTemplate(root, 1)


class FlavorExtraSpecsController(object):
    """The flavor extra specs API controller for the OpenStack API."""

    def _get_extra_specs(self, context, flavor_id):
        extra_specs = db.flavor_extra_specs_get(context, flavor_id)
        return dict(extra_specs=extra_specs)

    def _check_body(self, body):
        if body is None or body == "":
            expl = _('No Request Body')
            raise exc.HTTPBadRequest(explanation=expl)

    @wsgi.serializers(xml=ExtraSpecsTemplate)
    def index(self, req, flavor_id):
        """Returns the list of extra specs for a given flavor."""
        context = req.environ['nova.context']
        authorize(context, action='index')
        return self._get_extra_specs(context, flavor_id)

    @wsgi.serializers(xml=ExtraSpecsTemplate)
    def create(self, req, flavor_id, body):
        context = req.environ['nova.context']
        authorize(context, action='create')
        self._check_body(body)
        specs = body.get('extra_specs')
        try:
            db.flavor_extra_specs_update_or_create(context,
                                                              flavor_id,
                                                              specs)
        except exception.MetadataLimitExceeded as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        return body

    @wsgi.serializers(xml=ExtraSpecTemplate)
    def update(self, req, flavor_id, id, body):
        context = req.environ['nova.context']
        authorize(context, action='update')
        self._check_body(body)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise exc.HTTPBadRequest(explanation=expl)
        try:
            db.flavor_extra_specs_update_or_create(context,
                                                               flavor_id,
                                                               body)
        except exception.MetadataLimitExceeded as error:
            raise exc.HTTPBadRequest(explanation=error.format_message())
        return body

    @wsgi.serializers(xml=ExtraSpecTemplate)
    def show(self, req, flavor_id, id):
        """Return a single extra spec item."""
        context = req.environ['nova.context']
        authorize(context, action='show')
        try:
            extra_spec = db.flavor_extra_specs_get_item(context,
                                                               flavor_id, id)
            return extra_spec
        except exception.InstanceTypeExtraSpecsNotFound:
            raise exc.HTTPNotFound()

    def delete(self, req, flavor_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['nova.context']
        authorize(context, action='delete')
        try:
            db.flavor_extra_specs_delete(context, flavor_id, id)
        except exception.InstanceTypeExtraSpecsNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())


class Flavorextraspecs(extensions.ExtensionDescriptor):
    """Instance type (flavor) extra specs."""

    name = "FlavorExtraSpecs"
    alias = "os-flavor-extra-specs"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "flavor_extra_specs/api/v1.1")
    updated = "2011-06-23T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
                'os-extra_specs',
                FlavorExtraSpecsController(),
                parent=dict(member_name='flavor', collection_name='flavors'))

        resources.append(res)
        return resources

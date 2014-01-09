# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack Foundation
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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import exception
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common.gettextutils import _


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
    ALIAS = 'flavor-extra-specs'

    def __init__(self, *args, **kwargs):
        super(FlavorExtraSpecsController, self).__init__(*args, **kwargs)
        self.authorize = extensions.extension_authorizer('compute',
                                                         'v3:' + self.ALIAS)

    def _get_extra_specs(self, context, flavor_id):
        extra_specs = db.instance_type_extra_specs_get(context, flavor_id)
        return dict(extra_specs=extra_specs)

    def _check_body(self, body):
        if body is None or body == "":
            expl = _('No Request Body')
            raise webob.exc.HTTPBadRequest(explanation=expl)

    @wsgi.serializers(xml=ExtraSpecsTemplate)
    def index(self, req, flavor_id):
        """Returns the list of extra specs for a given flavor."""
        context = req.environ['nova.context']
        self.authorize(context, action='index')
        return self._get_extra_specs(context, flavor_id)

    @wsgi.serializers(xml=ExtraSpecsTemplate)
    @wsgi.response(201)
    def create(self, req, flavor_id, body):
        context = req.environ['nova.context']
        self.authorize(context, action='create')
        self._check_body(body)
        specs = body.get('extra_specs', {})
        if not specs or type(specs) is not dict:
            raise webob.exc.HTTPBadRequest(_('No or bad extra_specs provided'))
        try:
            db.instance_type_extra_specs_update_or_create(context, flavor_id,
                                                          specs)
        except db_exc.DBDuplicateEntry as error:
            raise webob.exc.HTTPBadRequest(explanation=error.format_message())
        return body

    @wsgi.serializers(xml=ExtraSpecTemplate)
    def update(self, req, flavor_id, id, body):
        context = req.environ['nova.context']
        self.authorize(context, action='update')
        self._check_body(body)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        try:
            db.instance_type_extra_specs_update_or_create(context, flavor_id,
                                                          body)
        except db_exc.DBDuplicateEntry as error:
            raise webob.exc.HTTPBadRequest(explanation=error.format_message())
        return body

    @wsgi.serializers(xml=ExtraSpecTemplate)
    def show(self, req, flavor_id, id):
        """Return a single extra spec item."""
        context = req.environ['nova.context']
        self.authorize(context, action='show')
        try:
            extra_spec = db.instance_type_extra_specs_get_item(context,
                                                               flavor_id, id)
            return extra_spec
        except exception.InstanceTypeExtraSpecsNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.response(204)
    @extensions.expected_errors(404)
    def delete(self, req, flavor_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['nova.context']
        self.authorize(context, action='delete')
        try:
            db.instance_type_extra_specs_delete(context, flavor_id, id)
        except exception.InstanceTypeExtraSpecsNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())


class FlavorsExtraSpecs(extensions.V3APIExtensionBase):
    """Flavors Extension."""
    name = 'FlavorsExtraSpecs'
    alias = FlavorExtraSpecsController.ALIAS
    namespace = "http://docs.openstack.org/compute/core/%s/v3" % alias
    version = 1

    def get_resources(self):
        extra_specs = extensions.ResourceExtension(
                self.alias,
                FlavorExtraSpecsController(),
                parent=dict(member_name='flavor', collection_name='flavors'))

        return [extra_specs]

    def get_controller_extensions(self):
        return []

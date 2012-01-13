# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova.api.openstack.compute.views import flavors as flavors_view
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import instance_types
from nova import exception


def make_flavor(elem, detailed=False):
    elem.set('name')
    elem.set('id')
    if detailed:
        elem.set('ram')
        elem.set('disk')

        for attr in ("vcpus", "swap", "rxtx_factor"):
            elem.set(attr, xmlutil.EmptyStringSelector(attr))

    xmlutil.make_links(elem, 'links')


flavor_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class FlavorTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor', selector='flavor')
        make_flavor(root, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class MinimalFlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class FlavorsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=flavor_nsmap)


class Controller(wsgi.Controller):
    """Flavor controller for the OpenStack API."""

    _view_builder_class = flavors_view.ViewBuilder

    @wsgi.serializers(xml=MinimalFlavorsTemplate)
    def index(self, req):
        """Return all flavors in brief."""
        flavors = self._get_flavors(req)
        return self._view_builder.index(req, flavors)

    @wsgi.serializers(xml=FlavorsTemplate)
    def detail(self, req):
        """Return all flavors in detail."""
        flavors = self._get_flavors(req)
        return self._view_builder.detail(req, flavors)

    @wsgi.serializers(xml=FlavorTemplate)
    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            flavor = instance_types.get_instance_type_by_flavor_id(id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, flavor)

    def _get_flavors(self, req):
        """Helper function that returns a list of flavor dicts."""
        filters = {}
        if 'minRam' in req.params:
            try:
                filters['min_memory_mb'] = int(req.params['minRam'])
            except ValueError:
                pass  # ignore bogus values per spec

        if 'minDisk' in req.params:
            try:
                filters['min_local_gb'] = int(req.params['minDisk'])
            except ValueError:
                pass  # ignore bogus values per spec

        return instance_types.get_all_types(filters=filters)


def create_resource():
    return wsgi.Resource(Controller())

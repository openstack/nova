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
from lxml import etree

from nova.api.openstack import views
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import instance_types
from nova import db
from nova import exception


class Controller(object):
    """Flavor controller for the OpenStack API."""

    def index(self, req):
        """Return all flavors in brief."""
        items = self._get_flavors(req, is_detail=False)
        return dict(flavors=items)

    def detail(self, req):
        """Return all flavors in detail."""
        items = self._get_flavors(req, is_detail=True)
        return dict(flavors=items)

    def _get_view_builder(self, req):
        raise NotImplementedError()

    def _get_flavors(self, req, is_detail=True):
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

        ctxt = req.environ['nova.context']
        inst_types = instance_types.get_all_types(filters=filters)
        builder = self._get_view_builder(req)
        items = [builder.build(inst_type, is_detail=is_detail)
                 for inst_type in inst_types.values()]
        return items

    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            ctxt = req.environ['nova.context']
            flavor = instance_types.get_instance_type_by_flavor_id(id)
        except exception.NotFound:
            raise webob.exc.HTTPNotFound()

        builder = self._get_view_builder(req)
        values = builder.build(flavor, is_detail=True)
        return dict(flavor=values)

    def _get_view_builder(self, req):
        base_url = req.application_url
        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        return views.flavors.ViewBuilder(base_url, project_id)


def make_flavor(elem, detailed=False):
    elem.set('name')
    elem.set('id')
    if detailed:
        elem.set('ram')
        elem.set('disk')

        for attr in ("vcpus", "swap", "rxtx_quota", "rxtx_cap"):
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


class FlavorXMLSerializer(xmlutil.XMLTemplateSerializer):
    def show(self):
        return FlavorTemplate()

    def detail(self):
        return FlavorsTemplate()

    def index(self):
        return MinimalFlavorsTemplate()


def create_resource():
    body_serializers = {'application/xml': FlavorXMLSerializer()}
    serializer = wsgi.ResponseSerializer(body_serializers)
    return wsgi.Resource(Controller(), serializer=serializer)

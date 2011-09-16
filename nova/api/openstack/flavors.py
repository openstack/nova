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
import xml.dom.minidom as minidom

from nova import db
from nova import exception
from nova.api.openstack import views
from nova.api.openstack import wsgi


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
        ctxt = req.environ['nova.context']
        flavors = db.api.instance_type_get_all(ctxt)
        builder = self._get_view_builder(req)
        items = [builder.build(flavor, is_detail=is_detail)
                 for flavor in flavors.values()]
        return items

    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            ctxt = req.environ['nova.context']
            flavor = db.api.instance_type_get_by_flavor_id(ctxt, id)
        except exception.NotFound:
            return webob.exc.HTTPNotFound()

        builder = self._get_view_builder(req)
        values = builder.build(flavor, is_detail=True)
        return dict(flavor=values)


class ControllerV10(Controller):

    def _get_view_builder(self, req):
        return views.flavors.ViewBuilder()


class ControllerV11(Controller):

    def _get_view_builder(self, req):
        base_url = req.application_url
        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        return views.flavors.ViewBuilderV11(base_url, project_id)


class FlavorXMLSerializer(wsgi.XMLDictSerializer):

    def __init__(self):
        super(FlavorXMLSerializer, self).__init__(xmlns=wsgi.XMLNS_V11)

    def _flavor_to_xml(self, xml_doc, flavor, detailed):
        flavor_node = xml_doc.createElement('flavor')
        flavor_node.setAttribute('id', str(flavor['id']))
        flavor_node.setAttribute('name', flavor['name'])

        if detailed:
            flavor_node.setAttribute('ram', str(flavor['ram']))
            flavor_node.setAttribute('disk', str(flavor['disk']))

            for attr in ("vcpus", "swap", "rxtx_quota", "rxtx_cap"):
                flavor_node.setAttribute(attr, str(flavor[attr]))

        link_nodes = self._create_link_nodes(xml_doc, flavor['links'])
        for link_node in link_nodes:
            flavor_node.appendChild(link_node)
        return flavor_node

    def _flavors_list_to_xml(self, xml_doc, flavors, detailed):
        container_node = xml_doc.createElement('flavors')

        for flavor in flavors:
            item_node = self._flavor_to_xml(xml_doc, flavor, detailed)
            container_node.appendChild(item_node)
        return container_node

    def show(self, flavor_container):
        xml_doc = minidom.Document()
        flavor = flavor_container['flavor']
        node = self._flavor_to_xml(xml_doc, flavor, True)
        return self.to_xml_string(node, True)

    def detail(self, flavors_container):
        xml_doc = minidom.Document()
        flavors = flavors_container['flavors']
        node = self._flavors_list_to_xml(xml_doc, flavors, True)
        return self.to_xml_string(node, True)

    def index(self, flavors_container):
        xml_doc = minidom.Document()
        flavors = flavors_container['flavors']
        node = self._flavors_list_to_xml(xml_doc, flavors, False)
        return self.to_xml_string(node, True)


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    xml_serializer = {
        '1.0': wsgi.XMLDictSerializer(xmlns=wsgi.XMLNS_V10),
        '1.1': FlavorXMLSerializer(),
    }[version]

    body_serializers = {
        'application/xml': xml_serializer,
    }

    serializer = wsgi.ResponseSerializer(body_serializers)

    return wsgi.Resource(controller, serializer=serializer)

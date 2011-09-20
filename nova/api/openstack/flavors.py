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

from nova import db
from nova import exception
from nova.api.openstack import views
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil


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

    NSMAP = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}

    def __init__(self):
        super(FlavorXMLSerializer, self).__init__(xmlns=wsgi.XMLNS_V11)

    def _populate_flavor(self, flavor_elem, flavor_dict, detailed=False):
        """Populate a flavor xml element from a dict."""

        flavor_elem.set('name', flavor_dict['name'])
        flavor_elem.set('id', str(flavor_dict['id']))
        if detailed:
            flavor_elem.set('ram', str(flavor_dict['ram']))
            flavor_elem.set('disk', str(flavor_dict['disk']))

            for attr in ("vcpus", "swap", "rxtx_quota", "rxtx_cap"):
                flavor_elem.set(attr, str(flavor_dict.get(attr, "")))

        for link in flavor_dict.get('links', []):
            elem = etree.SubElement(flavor_elem,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
        return flavor_elem

    def show(self, flavor_container):
        flavor = etree.Element('flavor', nsmap=self.NSMAP)
        self._populate_flavor(flavor, flavor_container['flavor'], True)
        return self._to_xml(flavor)

    def detail(self, flavors_dict):
        flavors = etree.Element('flavors', nsmap=self.NSMAP)
        for flavor_dict in flavors_dict['flavors']:
            flavor = etree.SubElement(flavors, 'flavor')
            self._populate_flavor(flavor, flavor_dict, True)
        return self._to_xml(flavors)

    def index(self, flavors_dict):
        flavors = etree.Element('flavors', nsmap=self.NSMAP)
        for flavor_dict in flavors_dict['flavors']:
            flavor = etree.SubElement(flavors, 'flavor')
            self._populate_flavor(flavor, flavor_dict, False)
        return self._to_xml(flavors)


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

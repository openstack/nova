# Copyright 2011 OpenStack LLC.
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

import urlparse
import os.path

import webob.exc
from xml.dom import minidom

from nova import compute
from nova import exception
from nova import flags
import nova.image
from nova import log
from nova.api.openstack import common
from nova.api.openstack import image_metadata
from nova.api.openstack import servers
from nova.api.openstack.views import images as images_view
from nova.api.openstack import wsgi


LOG = log.getLogger('nova.api.openstack.images')
FLAGS = flags.FLAGS

SUPPORTED_FILTERS = {
    'name': 'name',
    'status': 'status',
    'changes-since': 'changes-since',
    'server': 'property-instance_ref',
    'type': 'property-image_type',
}


class Controller(object):
    """Base controller for retrieving/displaying images."""

    def __init__(self, image_service=None, compute_service=None):
        """Initialize new `ImageController`.

        :param compute_service: `nova.compute.api:API`
        :param image_service: `nova.image.service:BaseImageService`

        """
        self._compute_service = compute_service or compute.API()
        self._image_service = image_service or \
                nova.image.get_default_image_service()

    def _get_filters(self, req):
        """
        Return a dictionary of query param filters from the request

        :param req: the Request object coming from the wsgi layer
        :retval a dict of key/value filters
        """
        filters = {}
        for param in req.str_params:
            if param in SUPPORTED_FILTERS or param.startswith('property-'):
                # map filter name or carry through if property-*
                filter_name = SUPPORTED_FILTERS.get(param, param)
                filters[filter_name] = req.str_params.get(param)
        return filters

    def show(self, req, id):
        """Return detailed information about a specific image.

        :param req: `wsgi.Request` object
        :param id: Image identifier
        """
        context = req.environ['nova.context']

        try:
            image = self._image_service.show(context, id)
        except (exception.NotFound, exception.InvalidImageRef):
            explanation = _("Image not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        return dict(image=self.get_builder(req).build(image, detail=True))

    def delete(self, req, id):
        """Delete an image, if allowed.

        :param req: `wsgi.Request` object
        :param id: Image identifier (integer)
        """
        context = req.environ['nova.context']
        self._image_service.delete(context, id)
        return webob.exc.HTTPNoContent()

    def get_builder(self, request):
        """Indicates that you must use a Controller subclass."""
        raise NotImplementedError()


class ControllerV10(Controller):
    """Version 1.0 specific controller logic."""

    @common.check_snapshots_enabled
    def create(self, req, body):
        """Snapshot a server instance and save the image."""
        try:
            image = body["image"]
        except (KeyError, TypeError):
            msg = _("Invalid image entity")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            image_name = image["name"]
            instance_id = image["serverId"]
        except KeyError as missing_key:
            msg = _("Image entity requires %s") % missing_key
            raise webob.exc.HTTPBadRequest(explanation=msg)

        context = req.environ["nova.context"]
        props = {'instance_id': instance_id}

        try:
            image = self._compute_service.snapshot(context,
                                              instance_id,
                                              image_name,
                                              extra_properties=props)
        except exception.InstanceBusy:
            msg = _("Server is currently creating an image. Please wait.")
            raise webob.exc.HTTPConflict(explanation=msg)

        return dict(image=self.get_builder(req).build(image, detail=True))

    def get_builder(self, request):
        """Property to get the ViewBuilder class we need to use."""
        base_url = request.application_url
        return images_view.ViewBuilderV10(base_url)

    def index(self, req):
        """Return an index listing of images available to the request.

        :param req: `wsgi.Request` object

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        images = self._image_service.index(context, filters=filters)
        images = common.limited(images, req)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=False) for image in images])

    def detail(self, req):
        """Return a detailed index listing of images available to the request.

        :param req: `wsgi.Request` object.

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        images = self._image_service.detail(context, filters=filters)
        images = common.limited(images, req)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=True) for image in images])


class ControllerV11(Controller):
    """Version 1.1 specific controller logic."""

    def get_builder(self, req):
        """Property to get the ViewBuilder class we need to use."""
        base_url = req.application_url
        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        return images_view.ViewBuilderV11(base_url, project_id)

    def index(self, req):
        """Return an index listing of images available to the request.

        :param req: `wsgi.Request` object

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        page_params = common.get_pagination_params(req)
        images = self._image_service.index(context, filters=filters,
                                           **page_params)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=False) for image in images])

    def detail(self, req):
        """Return a detailed index listing of images available to the request.

        :param req: `wsgi.Request` object.

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        page_params = common.get_pagination_params(req)
        images = self._image_service.detail(context, filters=filters,
                                            **page_params)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=True) for image in images])

    def create(self, *args, **kwargs):
        raise webob.exc.HTTPMethodNotAllowed()


class ImageXMLSerializer(wsgi.XMLDictSerializer):

    xmlns = wsgi.XMLNS_V11

    def __init__(self):
        self.metadata_serializer = common.MetadataXMLSerializer()

    def _image_to_xml(self, xml_doc, image):
        image_node = xml_doc.createElement('image')
        image_node.setAttribute('id', str(image['id']))
        image_node.setAttribute('name', image['name'])
        link_nodes = self._create_link_nodes(xml_doc,
                                             image['links'])
        for link_node in link_nodes:
            image_node.appendChild(link_node)
        return image_node

    def _image_to_xml_detailed(self, xml_doc, image):
        image_node = xml_doc.createElement('image')
        self._add_image_attributes(image_node, image)

        if 'server' in image:
            server_node = self._create_server_node(xml_doc, image['server'])
            image_node.appendChild(server_node)

        metadata = image.get('metadata', {}).items()
        if len(metadata) > 0:
            metadata_node = self._create_metadata_node(xml_doc, metadata)
            image_node.appendChild(metadata_node)

        link_nodes = self._create_link_nodes(xml_doc,
                                             image['links'])
        for link_node in link_nodes:
            image_node.appendChild(link_node)

        return image_node

    def _add_image_attributes(self, node, image):
        node.setAttribute('id', str(image['id']))
        node.setAttribute('name', image['name'])
        node.setAttribute('created', image['created'])
        node.setAttribute('updated', image['updated'])
        node.setAttribute('status', image['status'])
        if 'progress' in image:
            node.setAttribute('progress', str(image['progress']))

    def _create_metadata_node(self, xml_doc, metadata):
        return self.metadata_serializer.meta_list_to_xml(xml_doc, metadata)

    def _create_server_node(self, xml_doc, server):
        server_node = xml_doc.createElement('server')
        server_node.setAttribute('id', str(server['id']))
        link_nodes = self._create_link_nodes(xml_doc,
                                             server['links'])
        for link_node in link_nodes:
            server_node.appendChild(link_node)
        return server_node

    def _image_list_to_xml(self, xml_doc, images, detailed):
        container_node = xml_doc.createElement('images')
        if detailed:
            image_to_xml = self._image_to_xml_detailed
        else:
            image_to_xml = self._image_to_xml

        for image in images:
            item_node = image_to_xml(xml_doc, image)
            container_node.appendChild(item_node)
        return container_node

    def index(self, images_dict):
        xml_doc = minidom.Document()
        node = self._image_list_to_xml(xml_doc,
                                       images_dict['images'],
                                       detailed=False)
        return self.to_xml_string(node, True)

    def detail(self, images_dict):
        xml_doc = minidom.Document()
        node = self._image_list_to_xml(xml_doc,
                                       images_dict['images'],
                                       detailed=True)
        return self.to_xml_string(node, True)

    def show(self, image_dict):
        xml_doc = minidom.Document()
        node = self._image_to_xml_detailed(xml_doc,
                                       image_dict['image'])
        return self.to_xml_string(node, True)


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    metadata = {
        "attributes": {
            "image": ["id", "name", "updated", "created", "status",
                      "serverId", "progress", "serverRef"],
            "link": ["rel", "type", "href"],
        },
    }

    xml_serializer = {
        '1.0': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V10),
        '1.1': ImageXMLSerializer(),
    }[version]

    body_serializers = {
        'application/xml': xml_serializer,
    }

    serializer = wsgi.ResponseSerializer(body_serializers)

    return wsgi.Resource(controller, serializer=serializer)

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

import os.path

import webob.exc
from xml.dom import minidom

from nova import compute
from nova import exception
from nova import flags
import nova.image
from nova import log
from nova import utils
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.api.openstack import image_metadata
from nova.api.openstack.views import images as images_view
from nova.api.openstack import wsgi


LOG = log.getLogger('nova.api.openstack.images')
FLAGS = flags.FLAGS

SUPPORTED_FILTERS = ['name', 'status']


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
                filters[param] = req.str_params.get(param)

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
            raise faults.Fault(webob.exc.HTTPNotFound(explanation=explanation))

        return dict(image=self.get_builder(req).build(image, detail=True))

    def delete(self, req, id):
        """Delete an image, if allowed.

        :param req: `wsgi.Request` object
        :param id: Image identifier (integer)
        """
        context = req.environ['nova.context']
        self._image_service.delete(context, id)
        return webob.exc.HTTPNoContent()

    def create(self, req, body):
        """Snapshot or backup a server instance and save the image.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        :param req: `wsgi.Request` object
        """
        def get_param(param):
            try:
                return body["image"][param]
            except KeyError:
                raise webob.exc.HTTPBadRequest(explanation="Missing required "
                        "param: %s" % param)

        context = req.environ['nova.context']
        content_type = req.get_content_type()

        if not body:
            raise webob.exc.HTTPBadRequest()

        image_type = body["image"].get("image_type", "snapshot")

        try:
            server_id = self._server_id_from_req(req, body)
        except KeyError:
            raise webob.exc.HTTPBadRequest()

        image_name = get_param("name")
        props = self._get_extra_properties(req, body)

        if image_type == "snapshot":
            image = self._compute_service.snapshot(
                        context, server_id, image_name,
                        extra_properties=props)
        elif image_type == "backup":
            # NOTE(sirp): Unlike snapshot, backup is not a customer facing
            # API call; rather, it's used by the internal backup scheduler
            if not FLAGS.allow_admin_api:
                raise webob.exc.HTTPBadRequest(
                        explanation="Admin API Required")

            backup_type = get_param("backup_type")
            rotation = int(get_param("rotation"))

            image = self._compute_service.backup(
                        context, server_id, image_name,
                        backup_type, rotation, extra_properties=props)
        else:
            LOG.error(_("Invalid image_type '%s' passed") % image_type)
            raise webob.exc.HTTPBadRequest(explanation="Invalue image_type: "
                   "%s" % image_type)

        return dict(image=self.get_builder(req).build(image, detail=True))

    def get_builder(self, request):
        """Indicates that you must use a Controller subclass."""
        raise NotImplementedError()

    def _server_id_from_req(self, req, data):
        raise NotImplementedError()

    def _get_extra_properties(self, req, data):
        return {}


class ControllerV10(Controller):
    """Version 1.0 specific controller logic."""

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
        images = self._image_service.index(context, filters)
        images = common.limited(images, req)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=False) for image in images])

    def detail(self, req):
        """Return a detailed index listing of images available to the request.

        :param req: `wsgi.Request` object.

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        images = self._image_service.detail(context, filters)
        images = common.limited(images, req)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=True) for image in images])

    def _server_id_from_req(self, req, data):
        try:
            return data['image']['serverId']
        except KeyError:
            msg = _("Expected serverId attribute on server entity.")
            raise webob.exc.HTTPBadRequest(explanation=msg)


class ControllerV11(Controller):
    """Version 1.1 specific controller logic."""

    def get_builder(self, request):
        """Property to get the ViewBuilder class we need to use."""
        base_url = request.application_url
        return images_view.ViewBuilderV11(base_url)

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

    def _server_id_from_req(self, req, data):
        try:
            server_ref = data['image']['serverRef']
        except KeyError:
            msg = _("Expected serverRef attribute on server entity.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        head, tail = os.path.split(server_ref)

        if head and head != os.path.join(req.application_url, 'servers'):
            msg = _("serverRef must match request url")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return tail

    def _get_extra_properties(self, req, data):
        server_ref = data['image']['serverRef']
        if not server_ref.startswith('http'):
            server_ref = os.path.join(req.application_url, 'servers',
                                      server_ref)
        return {'instance_ref': server_ref}


class ImageXMLSerializer(wsgi.DictSerializer):

    xmlns = {'': wsgi.XMLNS_V11, 'atom': "http://www.w3.org/2005/Atom"}

    def __init__(self):
        self.metadata_serializer = image_metadata.ImageMetadataXMLSerializer()

    def _add_xmlns(self, node):
        for key, ns in self.xmlns.iteritems():
            if key is not '':
                name = 'xmlns:%s' % key
            else:
                name = 'xmlns'
            node.setAttribute(name, ns)

    def _image_to_xml(self, xml_doc, image):
        image_node = xml_doc.createElement('image')
        self._add_image_attributes(image_node, image)

        if 'server' in image:
            server_node = self._create_server_node(xml_doc, image['server'])
            image_node.appendChild(server_node)

        metadata = image.get('metadata', {}).items()
        if len(metadata) > 0:
            metadata_node = self._create_metadata_node(xml_doc, metadata)
            image_node.appendChild(metadata_node)

        self._add_atom_links(xml_doc, image_node, image['links'])

        return image_node

    def _add_image_attributes(self, node, image):
        node.setAttribute('id', str(image['id']))
        node.setAttribute('name', image['name'])
        node.setAttribute('created', image['created'])
        node.setAttribute('updated', image['updated'])
        node.setAttribute('status', image['status'])
        if 'progress' in image:
            node.setAttribute('progress', str(image['progress']))

    def _create_server_node(self, xml_doc, server):
        server_node = xml_doc.createElement('server')
        server_node.setAttribute('id', str(server['id']))
        server_node.setAttribute('name', server['name'])
        self._add_atom_links(xml_doc, server_node, server['links'])
        return server_node

    def _create_metadata_node(self, xml_doc, metadata):
        return self.metadata_serializer.meta_list_to_xml(xml_doc, metadata)

    def _add_atom_links(self, xml_doc, node, links):
        for link in links:
            link_node = xml_doc.createElement('atom:link')
            link_node.setAttribute('rel', link['rel'])
            link_node.setAttribute('href', link['href'])
            node.appendChild(link_node)

    def _image_list_to_xml(self, xml_doc, images):
        container_node = xml_doc.createElement('images')
        for image in images:
            item_node = self._image_to_xml(xml_doc, image)
            container_node.appendChild(item_node)
        return container_node

    def _image_to_xml_string(self, image):
        xml_doc = minidom.Document()
        item_node = self._image_to_xml(xml_doc, image)
        self._add_xmlns(item_node)
        return item_node.toprettyxml(indent='    ')

    def _image_list_to_xml_string(self, images):
        xml_doc = minidom.Document()
        container_node = self._image_list_to_xml(xml_doc, images)
        self._add_xmlns(container_node)
        return container_node.toprettyxml(indent='    ')

    def detail(self, images_dict):
        return self._image_list_to_xml_string(images_dict['images'])

    def show(self, image_dict):
        return self._image_to_xml_string(image_dict['image'])

    def create(self, image_dict):
        return self._image_to_xml_string(image_dict['image'])


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

    serializers = {
        'application/xml': xml_serializer,
    }

    return wsgi.Resource(controller, serializers=serializers)

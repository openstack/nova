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

from lxml import etree
import webob.exc

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
from nova.api.openstack import xmlutil


LOG = log.getLogger('nova.api.openstack.images')
FLAGS = flags.FLAGS

SUPPORTED_FILTERS = {
    'name': 'name',
    'status': 'status',
    'changes-since': 'changes-since',
    'server': 'property-instance_ref',
    'type': 'property-image_type',
    'minRam': 'min_ram',
    'minDisk': 'min_disk',
}


class Controller(object):
    """Base controller for retrieving/displaying images."""

    def __init__(self, image_service=None, compute_service=None):
        """Initialize new `ImageController`.

        :param compute_service: `nova.compute.api:API`
        :param image_service: `nova.image.glance:GlancemageService`

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
        try:
            self._image_service.delete(context, id)
        except exception.ImageNotFound:
            explanation = _("Image not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)
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
        return self.get_builder(req).build_list(images)

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
        params = req.GET.copy()
        page_params = common.get_pagination_params(req)
        for key, val in page_params.iteritems():
            params[key] = val

        images = self._image_service.index(context, filters=filters,
                                           **page_params)
        return self.get_builder(req).build_list(images, **params)

    def detail(self, req):
        """Return a detailed index listing of images available to the request.

        :param req: `wsgi.Request` object.

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        params = req.GET.copy()
        page_params = common.get_pagination_params(req)
        for key, val in page_params.iteritems():
            params[key] = val
        images = self._image_service.detail(context, filters=filters,
                                            **page_params)

        return self.get_builder(req).build_list(images, detail=True, **params)

    def create(self, *args, **kwargs):
        raise webob.exc.HTTPMethodNotAllowed()


class ImageXMLSerializer(wsgi.XMLDictSerializer):

    NSMAP = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}

    def __init__(self):
        self.metadata_serializer = common.MetadataXMLSerializer()

    def _create_metadata_node(self, metadata_dict):
        metadata_elem = etree.Element('metadata', nsmap=self.NSMAP)
        self.metadata_serializer.populate_metadata(metadata_elem,
                                                   metadata_dict)
        return metadata_elem

    def _create_server_node(self, server_dict):
        server_elem = etree.Element('server', nsmap=self.NSMAP)
        server_elem.set('id', str(server_dict['id']))
        for link in server_dict.get('links', []):
            elem = etree.SubElement(server_elem,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
        return server_elem

    def _populate_image(self, image_elem, image_dict, detailed=False):
        """Populate an image xml element from a dict."""

        image_elem.set('name', image_dict['name'])
        image_elem.set('id', str(image_dict['id']))
        if detailed:
            image_elem.set('updated', str(image_dict['updated']))
            image_elem.set('created', str(image_dict['created']))
            image_elem.set('status', str(image_dict['status']))
            if 'progress' in image_dict:
                image_elem.set('progress', str(image_dict['progress']))
            if 'minRam' in image_dict:
                image_elem.set('minRam', str(image_dict['minRam']))
            if 'minDisk' in image_dict:
                image_elem.set('minDisk', str(image_dict['minDisk']))
            if 'server' in image_dict:
                server_elem = self._create_server_node(image_dict['server'])
                image_elem.append(server_elem)

            meta_elem = self._create_metadata_node(
                            image_dict.get('metadata', {}))
            image_elem.append(meta_elem)

        self._populate_links(image_elem, image_dict.get('links', []))

    def _populate_links(self, parent, links):
        for link in links:
            elem = etree.SubElement(parent, '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            if 'type' in link:
                elem.set('type', link['type'])
            elem.set('href', link['href'])

    def index(self, images_dict):
        images = etree.Element('images', nsmap=self.NSMAP)
        for image_dict in images_dict['images']:
            image = etree.SubElement(images, 'image')
            self._populate_image(image, image_dict, False)

        self._populate_links(images, images_dict.get('images_links', []))
        return self._to_xml(images)

    def detail(self, images_dict):
        images = etree.Element('images', nsmap=self.NSMAP)
        for image_dict in images_dict['images']:
            image = etree.SubElement(images, 'image')
            self._populate_image(image, image_dict, True)
        return self._to_xml(images)

    def show(self, image_dict):
        image = etree.Element('image', nsmap=self.NSMAP)
        self._populate_image(image, image_dict['image'], True)
        return self._to_xml(image)


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

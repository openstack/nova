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

import webob.exc

from nova.api.openstack import common
from nova.api.openstack.compute.views import images as views_images
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova import flags
import nova.image
from nova import log


LOG = log.getLogger('nova.api.openstack.compute.images')
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


def make_image(elem, detailed=False):
    elem.set('name')
    elem.set('id')

    if detailed:
        elem.set('updated')
        elem.set('created')
        elem.set('status')
        elem.set('progress')
        elem.set('minRam')
        elem.set('minDisk')

        server = xmlutil.SubTemplateElement(elem, 'server', selector='server')
        server.set('id')
        xmlutil.make_links(server, 'links')

        elem.append(common.MetadataTemplate())

    xmlutil.make_links(elem, 'links')


image_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class ImageTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('image', selector='image')
        make_image(root, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=image_nsmap)


class MinimalImagesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        make_image(elem)
        xmlutil.make_links(root, 'images_links')
        return xmlutil.MasterTemplate(root, 1, nsmap=image_nsmap)


class ImagesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        make_image(elem, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=image_nsmap)


class Controller(wsgi.Controller):
    """Base controller for retrieving/displaying images."""

    _view_builder_class = views_images.ViewBuilder

    def __init__(self, image_service=None, compute_service=None, **kwargs):
        """Initialize new `ImageController`.

        :param compute_service: `nova.compute.api:API`
        :param image_service: `nova.image.glance:GlancemageService`

        """
        super(Controller, self).__init__(**kwargs)
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
        for param in req.params:
            if param in SUPPORTED_FILTERS or param.startswith('property-'):
                # map filter name or carry through if property-*
                filter_name = SUPPORTED_FILTERS.get(param, param)
                filters[filter_name] = req.params.get(param)
        return filters

    @wsgi.serializers(xml=ImageTemplate)
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

        return self._view_builder.show(req, image)

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

    @wsgi.serializers(xml=MinimalImagesTemplate)
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
        return self._view_builder.index(req, images)

    @wsgi.serializers(xml=ImagesTemplate)
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

        return self._view_builder.detail(req, images)

    def create(self, *args, **kwargs):
        raise webob.exc.HTTPMethodNotAllowed()


def create_resource():
    return wsgi.Resource(Controller())

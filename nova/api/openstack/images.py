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

from nova import compute
from nova import exception
from nova import flags
import nova.image
from nova import log
from nova.api.openstack import common
from nova.api.openstack import faults
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
        """Snapshot a server instance and save the image.

        :param req: `wsgi.Request` object
        """
        context = req.environ['nova.context']
        content_type = req.get_content_type()

        if not body:
            raise webob.exc.HTTPBadRequest()

        try:
            server_id = self._server_id_from_req(req, body)
            image_name = body["image"]["name"]
        except KeyError:
            raise webob.exc.HTTPBadRequest()

        props = self._get_extra_properties(req, body)

        image = self._compute_service.snapshot(context, server_id,
                                               image_name, props)
        return dict(image=self.get_builder(req).build(image, detail=True))

    def get_builder(self, request):
        """Indicates that you must use a Controller subclass."""
        raise NotImplementedError

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
        (marker, limit) = common.get_pagination_params(req)
        images = self._image_service.index(
            context, filters=filters, marker=marker, limit=limit)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=False) for image in images])

    def detail(self, req):
        """Return a detailed index listing of images available to the request.

        :param req: `wsgi.Request` object.

        """
        context = req.environ['nova.context']
        filters = self._get_filters(req)
        (marker, limit) = common.get_pagination_params(req)
        images = self._image_service.detail(
            context, filters=filters, marker=marker, limit=limit)
        builder = self.get_builder(req).build
        return dict(images=[builder(image, detail=True) for image in images])

    def _server_id_from_req(self, req, data):
        try:
            server_ref = data['image']['serverRef']
        except KeyError:
            msg = _("Expected serverRef attribute on server entity.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if not server_ref.startswith('http'):
            return server_ref

        passed = urlparse.urlparse(server_ref)
        expected = urlparse.urlparse(req.application_url)
        version = expected.path.split('/')[1]
        expected_prefix = "/%s/servers/" % version
        _empty, _sep, server_id = passed.path.partition(expected_prefix)
        scheme_ok = passed.scheme == expected.scheme
        host_ok = passed.hostname == expected.hostname
        port_ok = (passed.port == expected.port or
                   passed.port == FLAGS.osapi_port)
        if not (scheme_ok and port_ok and host_ok and server_id):
            msg = _("serverRef must match request url")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return server_id

    def _get_extra_properties(self, req, data):
        server_ref = data['image']['serverRef']
        if not server_ref.startswith('http'):
            server_ref = os.path.join(req.application_url, 'servers',
                                      server_ref)
        return {'instance_ref': server_ref}


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    xmlns = {
        '1.0': wsgi.XMLNS_V10,
        '1.1': wsgi.XMLNS_V11,
    }[version]

    metadata = {
        "attributes": {
            "image": ["id", "name", "updated", "created", "status",
                      "serverId", "progress", "serverRef"],
            "link": ["rel", "type", "href"],
        },
    }

    serializers = {
        'application/xml': wsgi.XMLDictSerializer(xmlns=xmlns,
                                                  metadata=metadata),
    }

    return wsgi.Resource(controller, serializers=serializers)

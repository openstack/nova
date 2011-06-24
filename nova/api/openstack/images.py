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

from nova import compute
from nova import exception
from nova import flags
import nova.image
from nova import log
from nova import utils
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
                raise webob.exc.HTTPBadRequest()

        context = req.environ['nova.context']
        content_type = req.get_content_type()

        if not body:
            raise webob.exc.HTTPBadRequest()

        image_type = body["image"].get("image_type", "snapshot")

        try:
            server_id = self._server_id_from_req_data(body)
        except KeyError:
            raise webob.exc.HTTPBadRequest()

        if image_type == "snapshot":
            image_name = get_param("name")
            image = self._compute_service.snapshot(context, server_id,
                    image_name)
        elif image_type in ("daily", "weekly"):
            if not FLAGS.allow_admin_api:
                raise webob.exc.HTTPBadRequest()

            rotation = int(get_param("rotation"))
            image = self._compute_service.backup(context, server_id,
                    image_type, rotation)
        else:
            LOG.error(_("Invalid image_type '%s' passed" % image_type))
            raise webob.exc.HTTPBadRequest()


        return dict(image=self.get_builder(req).build(image, detail=True))

    def get_builder(self, request):
        """Indicates that you must use a Controller subclass."""
        raise NotImplementedError()

    def _server_id_from_req_data(self, data):
        raise NotImplementedError()


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

    def _server_id_from_req_data(self, data):
        return data['image']['serverId']


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

    def _server_id_from_req_data(self, data):
        return data['image']['serverRef']


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

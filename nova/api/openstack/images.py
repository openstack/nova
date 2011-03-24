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
from nova import utils
from nova import wsgi
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.api.openstack.views import images as images_view


class Controller(wsgi.Controller):
    """
    Base `wsgi.Controller` for retrieving and displaying images in the
    OpenStack API. Version-inspecific code goes here.
    """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": ["id", "name", "updated", "created", "status",
                          "serverId", "progress"],
                "link": ["rel", "type", "href"],
            },
        },
    }

    def __init__(self, image_service=None, compute_service=None):
        """
        Initialize new `ImageController`.

        @param compute_service: `nova.compute.api:API`
        @param image_service: `nova.image.service:BaseImageService`
        """
        _default_service = utils.import_object(flags.FLAGS.image_service)

        self.__compute = compute_service or compute.API()
        self.__image = image_service or _default_service

    def index(self, req):
        """
        Return an index listing of images available to the request.

        @param req: `wsgi.Request` object
        """
        context = req.environ['nova.context']
        images = self.__image.index(context)
        build = self.get_builder(req).build
        return dict(images=[build(image, False) for image in images])

    def detail(self, req):
        """
        Return a detailed index listing of images available to the request.

        @param req: `wsgi.Request` object.
        """
        context = req.environ['nova.context']
        images = self.__image.detail(context)
        build = self.get_builder(req).build
        return dict(images=[build(image, True) for image in images])

    def show(self, req, id):
        """
        Return detailed information about a specific image.

        @param req: `wsgi.Request` object
        @param id: Image identifier (integer)
        """
        image_id = id
        context = req.environ['nova.context']

        try:
            image = self.__image.show(context, image_id)
        except exception.NotFound:
            ex = webob.exc.HTTPNotFound(explanation="Image not found.")
            raise faults.Fault(ex)

        return dict(image=self.get_builder(req).build(image, True))

    def delete(self, req, id):
        """
        Delete an image, if allowed.

        @param req: `wsgi.Request` object
        @param id: Image identifier (integer)
        """
        image_id = id
        context = req.environ['nova.context']
        self.__image.delete(context, image_id)
        return exc.HTTPNoContent()

    def create(self, req):
        """
        Snapshot a server instance and save the image.

        @param req: `wsgi.Request` object
        """
        context = req.environ['nova.context']
        content_type = req.get_content_type()
        image = self._deserialize(req.body, content_type)

        if not image:
            raise exc.HTTPBadRequest()

        try:
            server_id = image["image"]["serverId"]
            image_name = image["image"]["name"]
        except KeyError:
            raise exc.HTTPBadRequest()

        image = self.__compute.snapshot(context, server_id, image_name)
        return self.get_builder(req).build(image, True)


class ControllerV10(Controller):
    """
    Version 1.0 specific controller logic.
    """

    def get_builder(self, request):
        """
        Property to get the ViewBuilder class we need to use.
        """
        base_url = request.application_url
        return images_view.ViewBuilderV10(base_url)


class ControllerV11(Controller):
    """
    Version 1.1 specific controller logic.
    """

    def get_builder(self, request):
        """
        Property to get the ViewBuilder class we need to use.
        """
        base_url = request.application_url
        return images_view.ViewBuilderV11(base_url)

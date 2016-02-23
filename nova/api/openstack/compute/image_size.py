# Copyright 2013 Rackspace Hosting
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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi

ALIAS = "image-size"

authorize = extensions.os_compute_soft_authorizer(ALIAS)


class ImageSizeController(wsgi.Controller):

    def _extend_image(self, image, image_cache):
        # NOTE(mriedem): The OS-EXT-* prefix should not be used for new
        # attributes after v2.1. They are only in v2.1 for backward compat
        # with v2.0.
        key = "OS-EXT-IMG-SIZE:size"
        image[key] = image_cache['size']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ["nova.context"]
        if authorize(context):
            image_resp = resp_obj.obj['image']
            # image guaranteed to be in the cache due to the core API adding
            # it in its 'show' method
            image_cached = req.get_db_item('images', image_resp['id'])
            self._extend_image(image_resp, image_cached)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            images_resp = list(resp_obj.obj['images'])
            # images guaranteed to be in the cache due to the core API adding
            # it in its 'detail' method
            for image in images_resp:
                image_cached = req.get_db_item('images', image['id'])
                self._extend_image(image, image_cached)


class ImageSize(extensions.V21APIExtensionBase):
    """Adds image size to image listings."""

    name = "ImageSize"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = ImageSizeController()
        extension = extensions.ControllerExtension(self, 'images', controller)
        return [extension]

    def get_resources(self):
        return []

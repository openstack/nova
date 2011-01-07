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
"""Implementation of an image service that uses Glance as the backend"""

from __future__ import absolute_import
import httplib
import json
import logging
import urlparse

import webob.exc

from nova import flags
from nova import exception
from nova import utils
import nova.image.service

FLAGS = flags.FLAGS

GlanceClient = utils.import_class('glance.client.Client')


class GlanceImageService(nova.image.service.BaseImageService):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self):
        self.client = GlanceClient(FLAGS.glance_host, FLAGS.glance_port)

    def index(self, context):
        """
        Calls out to Parallax for a list of images available
        """
        return self.client.get_images()

    def detail(self, context):
        """
        Calls out to Parallax for a list of detailed image information
        """
        return self.client.get_images_detailed()

    def show(self, context, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        image = self.client.get_image_meta(id)
        if image:
            return image
        raise exception.NotFound

    def create(self, context, data):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        return self.client.add_image(image_meta=data)

    def update(self, context, image_id, data):
        """Replace the contents of the given image with the new data.

        :raises NotFound if the image does not exist.

        """
        return self.client.update_image(image_id, data)

    def delete(self, context, image_id):
        """
        Delete the given image.

        :raises NotFound if the image does not exist.

        """
        return self.client.delete_image(image_id)

    def delete_all(self):
        """
        Clears out all images
        """
        raise NotImplementedError

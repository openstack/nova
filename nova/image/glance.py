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

from glance.common import exception as glance_exception

from nova import exception
from nova import flags
from nova import log
from nova import utils
from nova.image import service


LOG = log.getLogger('nova.image.glance')

FLAGS = flags.FLAGS

GlanceClient = utils.import_class('glance.client.Client')


class GlanceImageService(service.BaseImageService):
    """Provides storage and retrieval of disk image objects within Glance."""

    GLANCE_ONLY_ATTRS = ["size", "location", "disk_format",
                         "container_format"]

    # NOTE(sirp): Overriding to use _translate_to_service provided by
    # BaseImageService
    SERVICE_IMAGE_ATTRS = service.BaseImageService.BASE_IMAGE_ATTRS +\
                          GLANCE_ONLY_ATTRS

    def __init__(self):
        self.client = GlanceClient(FLAGS.glance_host, FLAGS.glance_port)

    def index(self, context):
        """
        Calls out to Glance for a list of images available
        """
        return self.client.get_images()

    def detail(self, context):
        """
        Calls out to Glance for a list of detailed image information
        """
        image_metas = self.client.get_images_detailed()
        translate = self._translate_to_base
        return [translate(image_meta) for image_meta in image_metas]

    def show(self, context, image_id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        try:
            image_meta = self.client.get_image_meta(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound

        meta = self._translate_to_base(image_meta)
        return meta

    def show_by_name(self, context, name):
        """
        Returns a dict containing image data for the given name.
        """
        # TODO(vish): replace this with more efficient call when glance
        #             supports it.
        images = self.detail(context)
        image = None
        for cantidate in images:
            if name == cantidate.get('name'):
                image = cantidate
                break
        if image is None:
            raise exception.NotFound
        return image

    def get(self, context, image_id, data):
        """
        Calls out to Glance for metadata and data and writes data.
        """
        try:
            image_meta, image_chunks = self.client.get_image(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound

        for chunk in image_chunks:
            data.write(chunk)

        meta = self._translate_to_base(image_meta)
        return meta

    def create(self, context, metadata, data=None):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.
        """
        LOG.debug(_("Creating image in Glance. Metadata passed in %s"),
                  metadata)
        meta = self._translate_to_service(metadata)
        LOG.debug(_("Metadata after formatting for Glance %s"), meta)
        return self.client.add_image(meta, data)

    def update(self, context, image_id, metadata, data=None):
        """Replace the contents of the given image with the new data.

        :raises NotFound if the image does not exist.
        """
        try:
            result = self.client.update_image(image_id, metadata, data)
        except glance_exception.NotFound:
            raise exception.NotFound
        return result

    def delete(self, context, image_id):
        """
        Delete the given image.

        :raises NotFound if the image does not exist.
        """
        try:
            result = self.client.delete_image(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound
        return result

    def delete_all(self):
        """
        Clears out all images
        """
        pass

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

import datetime as dt

from glance.common import exception as glance_exception

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.image import service


LOG = logging.getLogger('nova.image.glance')

FLAGS = flags.FLAGS

GlanceClient = utils.import_class('glance.client.Client')


class GlanceImageService(service.BaseImageService):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self, client=None):
        if client is None:
            self.client = GlanceClient(FLAGS.glance_host, FLAGS.glance_port)
        self.client = client

    def index(self, context):
        """
        Calls out to Glance for a list of images available
        """
        return self.client.get_images()

    def detail(self, context):
        """
        Calls out to Glance for a list of detailed image information
        """
        for image in self.client.get_images_detailed():
            yield self._convert_timestamps_to_datetimes(image)

    def show(self, context, image_id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        try:
            image = self.client.get_image_meta(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound
        return self._convert_timestamps_to_datetimes(image)

    def _convert_timestamps_to_datetimes(self, image):
        """
        Returns image with known timestamp fields converted to datetime objects
        """
        for attr in ['created_at', 'updated_at', 'deleted_at']:
            if attr in image and image[attr] is not None:
                image[attr] = self._parse_glance_iso8601_timestamp(image[attr])
        return image

    def _parse_glance_iso8601_timestamp(self, timestamp):
        """
        Parse a subset of iso8601 timestamps into datetime objects
        """
        return dt.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f")

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
            metadata, image_chunks = self.client.get_image(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound
        for chunk in image_chunks:
            data.write(chunk)
        return self._convert_timestamps_to_datetimes(metadata)

    def create(self, context, metadata, data=None):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        return self.client.add_image(metadata, data)

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

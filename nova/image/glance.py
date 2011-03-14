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
from nova import log as logging
from nova import utils
from nova.image import service


LOG = logging.getLogger('nova.image.glance')

FLAGS = flags.FLAGS

GlanceClient = utils.import_class('glance.client.Client')


class GlanceImageService(service.BaseImageService):
    """Provides storage and retrieval of disk image objects within Glance."""
    IMAGE_PROPERTIES = ['instance_id', 'os_type']

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
        return self.client.get_images_detailed()

    def show(self, context, image_id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        try:
            metadata = self.client.get_image_meta(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound

        meta = self._depropertify_metadata_from_glance(metadata)
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
            metadata, image_chunks = self.client.get_image(image_id)
        except glance_exception.NotFound:
            raise exception.NotFound
        for chunk in image_chunks:
            data.write(chunk)

        meta = self._depropertify_metadata_from_glance(metadata)
        return meta

    def create(self, context, metadata, data=None):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        LOG.debug(_("Creating image in Glance. Metdata passed in %s"),
                  metadata)

        meta = self._propertify_metadata_for_glance(metadata)
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

    @classmethod
    def _propertify_metadata_for_glance(cls, metadata):
        """Return a metadata dict suitable for passing to Glance.

        The ImageService exposes metadata as a flat-dict; however, Glance
        distinguishes between two different types of metadata:

            1. First-class attributes: These are columns on the image table
               and represent metadata that is common to all images on all IAAS
               providers.

            2. Properties: These are entries in the image_properties table and
               represent image/IAAS-provider specific metadata.

        To reconcile this difference, this function accepts a flat-dict of
        metadata, figures out which attributes are stored as image properties
        in Glance, and then adds those to a `properties` dict nested within
        the metadata.
        """
        new_metadata = metadata.copy()
        properties = {}
        for property_ in cls.IMAGE_PROPERTIES:
            if property_ in new_metadata:
                value = new_metadata.pop(property_)
                properties[property_] = value
        new_metadata['properties'] = properties
        return new_metadata

    @classmethod
    def _depropertify_metadata_from_glance(cls, metadata):
        """Return a metadata dict suitable for returning from ImageService
        """
        new_metadata = metadata.copy()
        properties = new_metadata.pop('properties')
        for property_ in cls.IMAGE_PROPERTIES:
            if property_ in properties and property_ not in new_metadata:
                value = properties[property_]
                new_metadata[property_] = value
        return new_metadata

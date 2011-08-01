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

import datetime
import random

from glance.common import exception as glance_exception

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.image import service


LOG = logging.getLogger('nova.image.glance')


FLAGS = flags.FLAGS


GlanceClient = utils.import_class('glance.client.Client')


def pick_glance_api_server():
    """Return which Glance API server to use for the request

    This method provides a very primitive form of load-balancing suitable for
    testing and sandbox environments. In production, it would be better to use
    one IP and route that to a real load-balancer.

        Returns (host, port)
    """
    host_port = random.choice(FLAGS.glance_api_servers)
    host, port_str = host_port.split(':')
    port = int(port_str)
    return host, port


class GlanceImageService(service.BaseImageService):
    """Provides storage and retrieval of disk image objects within Glance."""

    GLANCE_ONLY_ATTRS = ['size', 'location', 'disk_format',
                         'container_format', 'checksum']

    # NOTE(sirp): Overriding to use _translate_to_service provided by
    # BaseImageService
    SERVICE_IMAGE_ATTRS = service.BaseImageService.BASE_IMAGE_ATTRS +\
                          GLANCE_ONLY_ATTRS

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        # NOTE(sirp): we want to load balance each request across glance
        # servers. Since GlanceImageService is a long-lived object, `client`
        # is made to choose a new server each time via this property.
        if self._client is not None:
            return self._client
        glance_host, glance_port = pick_glance_api_server()
        return GlanceClient(glance_host, glance_port)

    def _set_client(self, client):
        self._client = client

    client = property(_get_client, _set_client)

    def _set_client_context(self, context):
        """Sets the client's auth token."""
        self.client.set_auth_token(context.auth_token)

    def index(self, context, filters=None, marker=None, limit=None):
        """Calls out to Glance for a list of images available."""
        # NOTE(sirp): We need to use `get_images_detailed` and not
        # `get_images` here because we need `is_public` and `properties`
        # included so we can filter by user
        self._set_client_context(context)
        filtered = []
        filters = filters or {}
        if 'is_public' not in filters:
            # NOTE(vish): don't filter out private images
            filters['is_public'] = 'none'
        image_metas = self.client.get_images_detailed(filters=filters,
                                                      marker=marker,
                                                      limit=limit)
        for image_meta in image_metas:
            if self._is_image_available(context, image_meta):
                meta_subset = utils.subset_dict(image_meta, ('id', 'name'))
                filtered.append(meta_subset)
        return filtered

    def detail(self, context, filters=None, marker=None, limit=None):
        """Calls out to Glance for a list of detailed image information."""
        self._set_client_context(context)
        filtered = []
        filters = filters or {}
        if 'is_public' not in filters:
            # NOTE(vish): don't filter out private images
            filters['is_public'] = 'none'
        image_metas = self.client.get_images_detailed(filters=filters,
                                                      marker=marker,
                                                      limit=limit)
        for image_meta in image_metas:
            if self._is_image_available(context, image_meta):
                base_image_meta = self._translate_to_base(image_meta)
                filtered.append(base_image_meta)
        return filtered

    def show(self, context, image_id):
        """Returns a dict with image data for the given opaque image id."""
        self._set_client_context(context)
        try:
            image_meta = self.client.get_image_meta(image_id)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)

        if not self._is_image_available(context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_to_base(image_meta)
        return base_image_meta

    def show_by_name(self, context, name):
        """Returns a dict containing image data for the given name."""
        # TODO(vish): replace this with more efficient call when glance
        #             supports it.
        image_metas = self.detail(context)
        for image_meta in image_metas:
            if name == image_meta.get('name'):
                return image_meta
        raise exception.ImageNotFound(image_id=name)

    def get(self, context, image_id, data):
        """Calls out to Glance for metadata and data and writes data."""
        self._set_client_context(context)
        try:
            image_meta, image_chunks = self.client.get_image(image_id)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)

        for chunk in image_chunks:
            data.write(chunk)

        base_image_meta = self._translate_to_base(image_meta)
        return base_image_meta

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image id.

        :raises: AlreadyExists if the image already exist.

        """
        self._set_client_context(context)
        # Translate Base -> Service
        LOG.debug(_('Creating image in Glance. Metadata passed in %s'),
                  image_meta)
        sent_service_image_meta = self._translate_to_service(image_meta)
        LOG.debug(_('Metadata after formatting for Glance %s'),
                  sent_service_image_meta)

        recv_service_image_meta = self.client.add_image(
            sent_service_image_meta, data)

        # Translate Service -> Base
        base_image_meta = self._translate_to_base(recv_service_image_meta)
        LOG.debug(_('Metadata returned from Glance formatted for Base %s'),
                  base_image_meta)
        return base_image_meta

    def update(self, context, image_id, image_meta, data=None):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        self._set_client_context(context)
        # NOTE(vish): show is to check if image is available
        self.show(context, image_id)
        try:
            image_meta = self.client.update_image(image_id, image_meta, data)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_to_base(image_meta)
        return base_image_meta

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.

        """
        self._set_client_context(context)
        # NOTE(vish): show is to check if image is available
        self.show(context, image_id)
        try:
            result = self.client.delete_image(image_id)
        except glance_exception.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return result

    def delete_all(self):
        """Clears out all images."""
        pass

    @classmethod
    def _translate_to_base(cls, image_meta):
        """Override translation to handle conversion to datetime objects."""
        image_meta = service.BaseImageService._propertify_metadata(
                        image_meta, cls.SERVICE_IMAGE_ATTRS)
        image_meta = _convert_timestamps_to_datetimes(image_meta)
        return image_meta


# utility functions
def _convert_timestamps_to_datetimes(image_meta):
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = _parse_glance_iso8601_timestamp(
                image_meta[attr])
    return image_meta


def _parse_glance_iso8601_timestamp(timestamp):
    """Parse a subset of iso8601 timestamps into datetime objects."""
    iso_formats = ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S']

    for iso_format in iso_formats:
        try:
            return datetime.datetime.strptime(timestamp, iso_format)
        except ValueError:
            pass

    raise ValueError(_('%(timestamp)s does not follow any of the '
                       'signatures: %(ISO_FORMATS)s') % locals())

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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

"""Implementation of an fake image service"""

import copy
import datetime
import random

from nova import exception
from nova import flags
from nova import log as logging
from nova.image import service


LOG = logging.getLogger('nova.image.fake')


FLAGS = flags.FLAGS


class _FakeImageService(service.BaseImageService):
    """Mock (fake) image service for unit testing."""

    def __init__(self):
        self.images = {}
        # NOTE(justinsb): The OpenStack API can't upload an image?
        # So, make sure we've got one..
        timestamp = datetime.datetime(2011, 01, 01, 01, 02, 03)
        image1 = {'id': '123456',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'raw',
                 'disk_format': 'raw',
                 'properties': {'kernel_id': FLAGS.null_kernel,
                                'ramdisk_id': FLAGS.null_kernel,
                                'architecture': 'x86_64'}}

        image2 = {'id': 'fake',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'properties': {'kernel_id': FLAGS.null_kernel,
                                'ramdisk_id': FLAGS.null_kernel}}

        image3 = {'id': '2',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': None,
                 'disk_format': None,
                 'properties': {'kernel_id': FLAGS.null_kernel,
                                'ramdisk_id': FLAGS.null_kernel}}

        image4 = {'id': '1',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'properties': {'kernel_id': FLAGS.null_kernel,
                                'ramdisk_id': FLAGS.null_kernel}}

        image5 = {'id': '3',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'properties': {'kernel_id': FLAGS.null_kernel,
                                'ramdisk_id': FLAGS.null_kernel}}

        self.create(None, image1)
        self.create(None, image2)
        self.create(None, image3)
        self.create(None, image4)
        self.create(None, image5)
        super(_FakeImageService, self).__init__()

    def index(self, context, filters=None, marker=None, limit=None):
        """Returns list of images."""
        retval = []
        for img in self.images.values():
            retval += [dict([(k, v) for k, v in img.iteritems()
                                                  if k in ['id', 'name']])]
        return retval

    def detail(self, context, filters=None, marker=None, limit=None):
        """Return list of detailed image information."""
        return copy.deepcopy(self.images.values())

    def show(self, context, image_id):
        """Get data about specified image.

        Returns a dict containing image data for the given opaque image id.

        """
        image = self.images.get(str(image_id))
        if image:
            return copy.deepcopy(image)
        LOG.warn('Unable to find image id %s.  Have images: %s',
                 image_id, self.images)
        raise exception.ImageNotFound(image_id=image_id)

    def show_by_name(self, context, name):
        """Returns a dict containing image data for the given name."""
        images = copy.deepcopy(self.images.values())
        for image in images:
            if name == image.get('name'):
                return image
        raise exception.ImageNotFound(image_id=name)

    def create(self, context, metadata, data=None):
        """Store the image data and return the new image id.

        :raises: Duplicate if the image already exist.

        """
        try:
            image_id = metadata['id']
        except KeyError:
            while True:
                image_id = random.randint(0, 2 ** 31 - 1)
                if not self.images.get(str(image_id)):
                    break

        image_id = str(image_id)

        if self.images.get(image_id):
            raise exception.Duplicate()

        metadata['id'] = image_id
        self.images[image_id] = copy.deepcopy(metadata)
        return self.images[image_id]

    def update(self, context, image_id, metadata, data=None):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        if not self.images.get(image_id):
            raise exception.ImageNotFound(image_id=image_id)
        self.images[image_id] = copy.deepcopy(metadata)

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.

        """
        removed = self.images.pop(image_id, None)
        if not removed:
            raise exception.ImageNotFound(image_id=image_id)

    def delete_all(self):
        """Clears out all images."""
        self.images.clear()

_fakeImageService = _FakeImageService()


def FakeImageService():
    return _fakeImageService


def FakeImageService_reset():
    global _fakeImageService
    _fakeImageService = _FakeImageService()

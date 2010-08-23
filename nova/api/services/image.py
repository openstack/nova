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

import cPickle as pickle
import os.path
import random
import string

class ImageService(object):
    """Provides storage and retrieval of disk image objects."""

    @staticmethod
    def load():
        """Factory method to return image service."""
        #TODO(gundlach): read from config.
        class_ = LocalImageService
        return class_()

    def index(self):
        """
        Return a dict from opaque image id to image data.
        """

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """


class GlanceImageService(ImageService):
    """Provides storage and retrieval of disk image objects within Glance."""
    # TODO(gundlach): once Glance has an API, build this.
    pass


class LocalImageService(ImageService):
    """Image service storing images to local disk."""

    def __init__(self):
        self._path = "/tmp/nova/images"
        try:
            os.makedirs(self._path)
        except OSError: # exists
            pass

    def _path_to(self, image_id=''):
        return os.path.join(self._path, image_id)

    def _ids(self):
        """The list of all image ids."""
        return os.listdir(self._path)

    def index(self):
        return dict((id, self.show(id)) for id in self._ids())

    def show(self, id):
        return pickle.load(open(self._path_to(id))) 

    def create(self, data):
        """
        Store the image data and return the new image id.
        """
        id = ''.join(random.choice(string.letters) for _ in range(20))
        self.update(id, data)
        return id

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data."""
        pickle.dump(data, open(self._path_to(image_id), 'w'))

    def delete(self, image_id):
        """
        Delete the given image.  Raises OSError if the image does not exist.
        """
        os.unlink(self._path_to(image_id))

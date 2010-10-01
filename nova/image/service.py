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

from nova import utils
from nova import flags


FLAGS = flags.FLAGS


flags.DEFINE_string('glance_teller_address', '127.0.0.1',
                    'IP address or URL where Glance\'s Teller service resides')
flags.DEFINE_string('glance_teller_port', '9191',
                    'Port for Glance\'s Teller service')
flags.DEFINE_string('glance_parallax_address', '127.0.0.1',
                    'IP address or URL where Glance\'s Parallax service resides')
flags.DEFINE_string('glance_parallax_port', '9191',
                    'Port for Glance\'s Parallax service')


class BaseImageService(object):

    """Base class for providing image search and retrieval services"""

    def index(self):
        """
        Return a dict from opaque image id to image data.
        """
        raise NotImplementedError

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        raise NotImplementedError

    def create(self, data):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        raise NotImplementedError

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data.

        :raises NotFound if the image does not exist.

        """
        raise NotImplementedError

    def delete(self, image_id):
        """
        Delete the given image. 
        
        :raises NotFound if the image does not exist.
        
        """
        raise NotImplementedError


class GlanceImageService(BaseImageService):
    
    """Provides storage and retrieval of disk image objects within Glance."""

    def index(self):
        """
        Calls out to Parallax for a list of images available
        """
        raise NotImplementedError

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        raise NotImplementedError

    def create(self, data):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        raise NotImplementedError

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data.

        :raises NotFound if the image does not exist.

        """
        raise NotImplementedError

    def delete(self, image_id):
        """
        Delete the given image. 
        
        :raises NotFound if the image does not exist.
        
        """
        raise NotImplementedError

    def delete_all(self):
        """
        Clears out all images
        """
        pass


class LocalImageService(BaseImageService):

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
        return [ self.show(id) for id in self._ids() ]

    def show(self, id):
        return pickle.load(open(self._path_to(id))) 

    def create(self, data):
        """
        Store the image data and return the new image id.
        """
        id = ''.join(random.choice(string.letters) for _ in range(20))
        data['id'] = id
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

    def delete_all(self):
        """
        Clears out all images in local directory
        """
        for f in os.listdir(self._path):
            os.unlink(self._path_to(f))

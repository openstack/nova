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

from nova import flags
from nova import exception

FLAGS = flags.FLAGS


flags.DEFINE_string('glance_teller_address', 'http://127.0.0.1',
                    'IP address or URL where Glance\'s Teller service resides')
flags.DEFINE_string('glance_teller_port', '9191',
                    'Port for Glance\'s Teller service')
flags.DEFINE_string('glance_parallax_address', 'http://127.0.0.1',
                    'IP address or URL where Glance\'s Parallax service resides')
flags.DEFINE_string('glance_parallax_port', '9292',
                    'Port for Glance\'s Parallax service')


class BaseImageService(object):

    """Base class for providing image search and retrieval services"""

    def index(self):
        """
        Returns a sequence of mappings of id and name information about
        images.

        :retval a sequence of mappings with the following signature:

            [
            {'id': opaque id of image,
             'name': name of image
             }, ...
            ]

        """
        raise NotImplementedError

    def detail(self):
        """
        Returns a sequence of mappings of detailed information about images.

        :retval a sequence of mappings with the following signature:

            [
            {'id': opaque id of image,
             'name': name of image,
             'created_at': creation timestamp,
             'updated_at': modification timestamp,
             'deleted_at': deletion timestamp or None,
             'deleted': boolean indicating if image has been deleted,
             'status': string description of image status,
             'is_public': boolean indicating if image is public
             }, ...
            ]

        If the service does not implement a method that provides a detailed
        set of information about images, then the method should raise
        NotImplementedError, in which case Nova will emulate this method
        with repeated calls to show() for each image received from the
        index() method.
        """
        raise NotImplementedError

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.

        :retval a mapping with the following signature:

            {'id': opaque id of image,
             'name': name of image,
             'created_at': creation timestamp,
             'updated_at': modification timestamp,
             'deleted_at': deletion timestamp or None,
             'deleted': boolean indicating if image has been deleted,
             'status': string description of image status,
             'is_public': boolean indicating if image is public
             }, ...

        :raises NotFound if the image does not exist
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


class LocalImageService(BaseImageService):

    """Image service storing images to local disk.
    
    It assumes that image_ids are integers."""

    def __init__(self):
        self._path = "/tmp/nova/images"
        try:
            os.makedirs(self._path)
        except OSError: # exists
            pass

    def _path_to(self, image_id):
        return os.path.join(self._path, str(image_id))

    def _ids(self):
        """The list of all image ids."""
        return [int(i) for i in os.listdir(self._path)]

    def index(self):
        return [dict(id=i['id'], name=i['name']) for i in self.detail()]

    def detail(self):
        return [self.show(id) for id in self._ids()]

    def show(self, id):
        try:
            return pickle.load(open(self._path_to(id))) 
        except IOError:
            raise exception.NotFound

    def create(self, data):
        """
        Store the image data and return the new image id.
        """
        id = random.randint(0, 2**32-1)
        data['id'] = id
        self.update(id, data)
        return id

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data."""
        try:
            pickle.dump(data, open(self._path_to(image_id), 'w'))
        except IOError:
            raise exception.NotFound

    def delete(self, image_id):
        """
        Delete the given image.  Raises OSError if the image does not exist.
        """
        try:
            os.unlink(self._path_to(image_id))
        except IOError:
            raise exception.NotFound

    def delete_all(self):
        """
        Clears out all images in local directory
        """
        for id in self._ids():
            os.unlink(self._path_to(id))

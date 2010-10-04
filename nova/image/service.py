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
import httplib
import json
import os.path
import random
import string
import urlparse

import webob.exc

from nova import utils
from nova import flags


FLAGS = flags.FLAGS


flags.DEFINE_string('glance_teller_address', 'http://127.0.0.1',
                    'IP address or URL where Glance\'s Teller service resides')
flags.DEFINE_string('glance_teller_port', '9191',
                    'Port for Glance\'s Teller service')
flags.DEFINE_string('glance_parallax_address', 'http://127.0.0.1',
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


class TellerClient(object):

    def __init__(self):
        self.address = FLAGS.glance_teller_address
        self.port = FLAGS.glance_teller_port
        url = urlparse.urlparse(self.address)
        self.netloc = url.netloc
        self.connection_type = {'http': httplib.HTTPConnection,
                                'https': httplib.HTTPSConnection}[url.scheme]


class ParallaxClient(object):

    def __init__(self):
        self.address = FLAGS.glance_parallax_address
        self.port = FLAGS.glance_parallax_port
        url = urlparse.urlparse(self.address)
        self.netloc = url.netloc
        self.connection_type = {'http': httplib.HTTPConnection,
                                'https': httplib.HTTPSConnection}[url.scheme]

    def get_images(self):
        """
        Returns a list of image data mappings from Parallax
        """
        try:
            c = self.connection_type(self.netloc, self.port)
            c.request("GET", "images")
            res = c.getresponse()
            if res.status == 200:
                data = json.loads(res.read())
                return data
            else:
                # TODO(jaypipes): return or raise HTTP error?
                return []
        finally:
            c.close()

    def get_image_metadata(self, image_id):
        """
        Returns a mapping of image metadata from Parallax
        """
        try:
            c = self.connection_type(self.netloc, self.port)
            c.request("GET", "images/%s" % image_id)
            res = c.getresponse()
            if res.status == 200:
                data = json.loads(res.read())
                return data
            else:
                # TODO(jaypipes): return or raise HTTP error?
                return []
        finally:
            c.close()

    def add_image_metadata(self, image_metadata):
        """
        Tells parallax about an image's metadata
        """
        pass

    def update_image_metadata(self, image_id, image_metadata):
        """
        Updates Parallax's information about an image
        """
        pass

    def delete_image_metadata(self, image_id):
        """
        Deletes Parallax's information about an image
        """
        pass


class GlanceImageService(BaseImageService):
    
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self):
        self.teller = TellerClient()
        self.parallax = ParallaxClient()

    def index(self):
        """
        Calls out to Parallax for a list of images available
        """
        images = self.parallax.get_images()
        return images

    def show(self, id):
        """
        Returns a dict containing image data for the given opaque image id.
        """
        image = self.parallax.get_image_metadata(id)
        return image 

    def create(self, data):
        """
        Store the image data and return the new image id.

        :raises AlreadyExists if the image already exist.

        """
        return self.parallax.add_image_metadata(data)

    def update(self, image_id, data):
        """Replace the contents of the given image with the new data.

        :raises NotFound if the image does not exist.

        """
        self.parallax.update_image_metadata(image_id, data)

    def delete(self, image_id):
        """
        Delete the given image. 
        
        :raises NotFound if the image does not exist.
        
        """
        self.parallax.delete_image_metadata(image_id)

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

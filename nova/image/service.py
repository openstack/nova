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

        Returns None if the id does not exist.
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


# TODO(gundlach): before this can be loaded dynamically in ImageService.load(),
# we'll have to make __init__() not require a context.  Right now it
# is only used by the AWS API, which hard-codes it, so that's OK.
class S3ImageService(ImageService):
    """Service that stores images in an S3 provider."""

    def __init__(self, context):
        self._context = context

    def index(self):
        response = self._conn().make_request(
                method='GET',
                bucket='_images')
        items = json.loads(response.read())
        return dict((item['imageId'], item) for item in items)
    
    def show(self, id):
        response = self._conn().make_request(
            method='GET',
            bucket='_images',
            query_args=qs({'image_id': image_id}))
        return json.loads(response.read())

    def delete(self, image_id):
        self._conn().make_request(
                method='DELETE',
                bucket='_images',
                query_args=qs({'image_id': image_id}))

    def _conn(self):
        """Return a boto S3Connection to the S3 store."""
        access = manager.AuthManager().get_access_key(self._context.user,
                                                      self._context.project)
        secret = str(self._context.user.secret)
        calling = boto.s3.connection.OrdinaryCallingFormat()
        return boto.s3.connection.S3Connection(aws_access_key_id=access,
                                               aws_secret_access_key=secret,
                                               is_secure=False,
                                               calling_format=calling,
                                               port=FLAGS.s3_port,
                                               host=FLAGS.s3_host)

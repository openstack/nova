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
import tempfile

from nova import exception
from nova.image import service


class LocalImageService(service.BaseImageService):

    """Image service storing images to local disk.

    It assumes that image_ids are integers."""

    def __init__(self):
        self._path = tempfile.mkdtemp()

    def _path_to(self, image_id):
        return os.path.join(self._path, str(image_id))

    def _ids(self):
        """The list of all image ids."""
        return [int(i) for i in os.listdir(self._path)]

    def index(self, context):
        return [dict(id=i['id'], name=i['name']) for i in self.detail(context)]

    def detail(self, context):
        return [self.show(context, id) for id in self._ids()]

    def show(self, context, id):
        try:
            return pickle.load(open(self._path_to(id)))
        except IOError:
            raise exception.NotFound

    def create(self, context, data):
        """
        Store the image data and return the new image id.
        """
        id = random.randint(0, 2 ** 31 - 1)
        data['id'] = id
        self.update(context, id, data)
        return id

    def update(self, context, image_id, data):
        """
        Replace the contents of the given image with the new data.
        """
        try:
            pickle.dump(data, open(self._path_to(image_id), 'w'))
        except IOError:
            raise exception.NotFound

    def delete(self, context, image_id):
        """
        Delete the given image.  Raises OSError if the image does not exist.
        """
        try:
            os.unlink(self._path_to(image_id))
        except IOError:
            raise exception.NotFound

    def delete_all(self):
        """
        Clears out all images in local directory.
        """
        for id in self._ids():
            os.unlink(self._path_to(id))

    def delete_imagedir(self):
        """
        Deletes the local directory.  Raises OSError if directory is not empty.
        """
        os.rmdir(self._path)

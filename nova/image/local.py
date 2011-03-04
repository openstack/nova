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

import json
import os.path
import random
import shutil

from nova import flags
from nova import exception
from nova.image import service


FLAGS = flags.FLAGS
flags.DEFINE_string('images_path', '$state_path/images',
                    'path to decrypted images')

class LocalImageService(service.BaseImageService):
    """Image service storing images to local disk.

    It assumes that image_ids are integers.

    """

    def __init__(self):
        self._path = FLAGS.images_path

    def _path_to(self, image_id, fname='info.json'):
        if fname:
            return os.path.join(self._path, str(image_id), fname)
        return os.path.join(self._path, str(image_id))

    def _ids(self):
        """The list of all image ids."""
        return [int(i) for i in os.listdir(self._path)
                if unicode(i).isnumeric()]

    def index(self, context):
        return [dict(image_id=i['id'], name=i.get('name'))
                for i in self.detail(context)]

    def detail(self, context):
        images = []
        for image_id in self._ids():
            try:
                image = self.show(context, image_id)
                images.append(image)
            except exception.NotFound:
                continue
        return images

    def show(self, context, image_id):
        try:
            with open(self._path_to(image_id)) as metadata_file:
                return json.load(metadata_file)
        except IOError:
            raise exception.NotFound

    def create(self, context, metadata, data=None):
        """Store the image data and return the new image id."""
        image_id = random.randint(0, 2 ** 31 - 1)
        image_path = self._path_to(image_id, None)
        if not os.path.exists(image_path):
            os.mkdir(image_path)
        return  self.update(context, image_id, metadata, data)

    def update(self, context, image_id, metadata, data=None):
        """Replace the contents of the given image with the new data."""
        metadata['id'] = image_id
        try:
            with open(self._path_to(image_id), 'w') as metadata_file:
                json.dump(metadata, metadata_file)
            if data:
                with open(self._path_to(image_id, 'image'), 'w') as image_file:
                    shutil.copyfileobj(data, image_file)
        except IOError:
            raise exception.NotFound
        return metadata

    def delete(self, context, image_id):
        """Delete the given image.
        Raises OSError if the image does not exist.

        """
        try:
            os.unlink(self._path_to(image_id))
        except IOError:
            raise exception.NotFound

    def delete_all(self):
        """Clears out all images in local directory."""
        for image_id in self._ids():
            os.unlink(self._path_to(image_id))

    def delete_imagedir(self):
        """Deletes the local directory.
        Raises OSError if directory is not empty.

        """
        os.rmdir(self._path)

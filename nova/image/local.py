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

from nova import exception
from nova import flags
from nova import log as logging
from nova.image import service


FLAGS = flags.FLAGS
flags.DEFINE_string('images_path', '$state_path/images',
                    'path to decrypted images')

LOG = logging.getLogger('nova.image.local')


class LocalImageService(service.BaseImageService):
    """Image service storing images to local disk.

    It assumes that image_ids are integers.

    """

    def __init__(self):
        self._path = FLAGS.images_path

    def _path_to(self, image_id, fname='info.json'):
        if fname:
            return os.path.join(self._path, '%08x' % int(image_id), fname)
        return os.path.join(self._path, '%08x' % int(image_id))

    def _ids(self):
        """The list of all image ids."""
        images = []
        for image_dir in os.listdir(self._path):
            try:
                unhexed_image_id = int(image_dir, 16)
            except ValueError:
                LOG.error(
                    _("%s is not in correct directory naming format"\
                       % image_dir))
            else:
                images.append(unhexed_image_id)
        return images

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
        except (IOError, ValueError):
            raise exception.NotFound

    def show_by_name(self, context, name):
        """Returns a dict containing image data for the given name."""
        # NOTE(vish): Not very efficient, but the local image service
        #             is for testing so it should be fine.
        images = self.detail(context)
        image = None
        for cantidate in images:
            if name == cantidate.get('name'):
                image = cantidate
                break
        if image == None:
            raise exception.NotFound
        return image

    def get(self, context, image_id, data):
        """Get image and metadata."""
        try:
            with open(self._path_to(image_id)) as metadata_file:
                metadata = json.load(metadata_file)
            with open(self._path_to(image_id, 'image')) as image_file:
                shutil.copyfileobj(image_file, data)
        except (IOError, ValueError):
            raise exception.NotFound
        return metadata

    def create(self, context, metadata, data=None):
        """Store the image data and return the new image."""
        image_id = random.randint(0, 2 ** 31 - 1)
        image_path = self._path_to(image_id, None)
        if not os.path.exists(image_path):
            os.mkdir(image_path)
        return self.update(context, image_id, metadata, data)

    def update(self, context, image_id, metadata, data=None):
        """Replace the contents of the given image with the new data."""
        metadata['id'] = image_id
        try:
            if data:
                location = self._path_to(image_id, 'image')
                with open(location, 'w') as image_file:
                    shutil.copyfileobj(data, image_file)
                # NOTE(vish): update metadata similarly to glance
                metadata['status'] = 'active'
                metadata['location'] = location
            with open(self._path_to(image_id), 'w') as metadata_file:
                json.dump(metadata, metadata_file)
        except (IOError, ValueError):
            raise exception.NotFound
        return metadata

    def delete(self, context, image_id):
        """Delete the given image.
        Raises OSError if the image does not exist.

        """
        try:
            shutil.rmtree(self._path_to(image_id, None))
        except (IOError, ValueError):
            raise exception.NotFound

    def delete_all(self):
        """Clears out all images in local directory."""
        for image_id in self._ids():
            shutil.rmtree(self._path_to(image_id, None))

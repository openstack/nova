# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
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

from glance.common import exception as glance_exception


NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"


class StubGlanceClient(object):

    def __init__(self, images=None):
        self.images = []
        _images = images or []
        map(lambda image: self.add_image(image, None), _images)

    def set_auth_token(self, auth_tok):
        pass

    def get_image_meta(self, image_id):
        for image in self.images:
            if image['id'] == str(image_id):
                return image
        raise glance_exception.NotFound()

    #TODO(bcwaldon): implement filters
    def get_images_detailed(self, filters=None, marker=None, limit=3):
        if marker is None:
            index = 0
        else:
            for index, image in enumerate(self.images):
                if image['id'] == str(marker):
                    index += 1
                    break
            else:
                raise glance_exception.Invalid()

        return self.images[index:index + limit]

    def get_image(self, image_id):
        return self.get_image_meta(image_id), []

    def add_image(self, metadata, data):
        metadata['created_at'] = NOW_GLANCE_FORMAT
        metadata['updated_at'] = NOW_GLANCE_FORMAT

        self.images.append(metadata)

        try:
            image_id = str(metadata['id'])
        except KeyError:
            # auto-generate an id if one wasn't provided
            image_id = str(len(self.images))

        self.images[-1]['id'] = image_id

        return self.images[-1]

    def update_image(self, image_id, metadata, data, features):
        for i, image in enumerate(self.images):
            if image['id'] == str(image_id):
                if 'id' in metadata:
                    metadata['id'] = str(metadata['id'])
                self.images[i].update(metadata)
                return self.images[i]
        raise glance_exception.NotFound()

    def delete_image(self, image_id):
        for i, image in enumerate(self.images):
            if image['id'] == image_id:
                del self.images[i]
                return
        raise glance_exception.NotFound()

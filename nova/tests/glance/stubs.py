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

import glanceclient.exc


NOW_GLANCE_FORMAT = "2010-10-11T10:30:22"


class StubGlanceClient(object):

    def __init__(self, images=None, version=None, endpoint=None, **params):
        self.auth_token = params.get('token')
        self.identity_headers = params.get('identity_headers')
        if self.identity_headers:
            if self.identity_headers.get('X-Auth-Token'):
                self.auth_token = (self.identity_headers.get('X-Auth_Token') or
                                   self.auth_token)
                del self.identity_headers['X-Auth-Token']
        self._images = []
        _images = images or []
        map(lambda image: self.create(**image), _images)

        #NOTE(bcwaldon): HACK to get client.images.* to work
        self.images = lambda: None
        for fn in ('list', 'get', 'data', 'create', 'update', 'delete'):
            setattr(self.images, fn, getattr(self, fn))

    #TODO(bcwaldon): implement filters
    def list(self, filters=None, marker=None, limit=30, page_size=20):
        if marker is None:
            index = 0
        else:
            for index, image in enumerate(self._images):
                if image.id == str(marker):
                    index += 1
                    break
            else:
                raise glanceclient.exc.BadRequest('Marker not found')
        return self._images[index:index + limit]

    def get(self, image_id):
        for image in self._images:
            if image.id == str(image_id):
                return image
        raise glanceclient.exc.NotFound(image_id)

    def data(self, image_id):
        self.get(image_id)
        return []

    def create(self, **metadata):
        metadata['created_at'] = NOW_GLANCE_FORMAT
        metadata['updated_at'] = NOW_GLANCE_FORMAT

        self._images.append(FakeImage(metadata))

        try:
            image_id = str(metadata['id'])
        except KeyError:
            # auto-generate an id if one wasn't provided
            image_id = str(len(self._images))

        self._images[-1].id = image_id

        return self._images[-1]

    def update(self, image_id, **metadata):
        for i, image in enumerate(self._images):
            if image.id == str(image_id):
                # If you try to update a non-authorized image, it raises
                # HTTPForbidden
                if image.owner == 'authorized_fake':
                    raise glanceclient.exc.HTTPForbidden

                for k, v in metadata.items():
                    setattr(self._images[i], k, v)
                return self._images[i]
        raise glanceclient.exc.NotFound(image_id)

    def delete(self, image_id):
        for i, image in enumerate(self._images):
            if image.id == image_id:
                # When you delete an image from glance, it sets the status to
                # DELETED. If you try to delete a DELETED image, it raises
                # HTTPForbidden.
                image_data = self._images[i]
                if image_data.deleted:
                    raise glanceclient.exc.HTTPForbidden()
                image_data.deleted = True
                image_data.deleted_at = NOW_GLANCE_FORMAT
                return
        raise glanceclient.exc.NotFound(image_id)


class FakeImage(object):
    def __init__(self, metadata):
        IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                            'container_format', 'checksum', 'id',
                            'name', 'created_at', 'updated_at',
                            'deleted', 'deleted_at', 'status',
                            'min_disk', 'min_ram', 'is_public']
        raw = dict.fromkeys(IMAGE_ATTRIBUTES)
        raw.update(metadata)
        self.__dict__['raw'] = raw

    def __getattr__(self, key):
        try:
            return self.__dict__['raw'][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        try:
            self.__dict__['raw'][key] = value
        except KeyError:
            raise AttributeError(key)

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

import copy
import StringIO

from glance.common import exception as glance_exception

from nova import exception
from nova.image import glance


def stubout_glance_client(stubs):
    def fake_get_glance_client(context, image_href):
        image_id = int(str(image_href).split('/')[-1])
        return (FakeGlance('foo'), image_id)
    stubs.Set(glance, 'get_glance_client', fake_get_glance_client)


class FakeGlance(object):
    IMAGE_MACHINE = 1
    IMAGE_KERNEL = 2
    IMAGE_RAMDISK = 3
    IMAGE_RAW = 4
    IMAGE_VHD = 5
    IMAGE_ISO = 6

    IMAGE_FIXTURES = {
        IMAGE_MACHINE: {
            'image_meta': {'name': 'fakemachine', 'size': 0,
                           'disk_format': 'ami',
                           'container_format': 'ami'},
            'image_data': StringIO.StringIO('')},
        IMAGE_KERNEL: {
            'image_meta': {'name': 'fakekernel', 'size': 0,
                           'disk_format': 'aki',
                           'container_format': 'aki'},
            'image_data': StringIO.StringIO('')},
        IMAGE_RAMDISK: {
            'image_meta': {'name': 'fakeramdisk', 'size': 0,
                           'disk_format': 'ari',
                           'container_format': 'ari'},
            'image_data': StringIO.StringIO('')},
        IMAGE_RAW: {
            'image_meta': {'name': 'fakeraw', 'size': 0,
                           'disk_format': 'raw',
                           'container_format': 'bare'},
            'image_data': StringIO.StringIO('')},
        IMAGE_VHD: {
            'image_meta': {'name': 'fakevhd', 'size': 0,
                           'disk_format': 'vhd',
                           'container_format': 'ovf'},
            'image_data': StringIO.StringIO('')},
        IMAGE_ISO: {
            'image_meta': {'name': 'fakeiso', 'size': 0,
                           'disk_format': 'iso',
                           'container_format': 'bare'},
            'image_data': StringIO.StringIO('')}}

    def __init__(self, host, port=None, use_ssl=False, auth_tok=None):
        pass

    def set_auth_token(self, auth_tok):
        pass

    def get_image_meta(self, image_id):
        meta = copy.deepcopy(self.IMAGE_FIXTURES[int(image_id)]['image_meta'])
        meta['id'] = image_id
        return meta

    def get_image(self, image_id):
        image = self.IMAGE_FIXTURES[int(image_id)]
        meta = copy.deepcopy(image['image_meta'])
        meta['id'] = image_id
        return meta, image['image_data']


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

    def update_image(self, image_id, metadata, data):
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

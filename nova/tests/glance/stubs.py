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

import StringIO

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
        return self.IMAGE_FIXTURES[int(image_id)]['image_meta']

    def get_image(self, image_id):
        image = self.IMAGE_FIXTURES[int(image_id)]
        return image['image_meta'], image['image_data']

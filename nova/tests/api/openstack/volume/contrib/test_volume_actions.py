#   Copyright 2012 OpenStack LLC.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import datetime
import webob

from nova.api.openstack.volume.contrib import volume_actions
from nova import exception
from nova.openstack.common.rpc import common as rpc_common
from nova import test
from nova.tests.api.openstack import fakes
from nova.volume import api as volume_api


def stub_volume_get(self, context, volume_id):
    volume = fakes.stub_volume(volume_id)
    if volume_id == 5:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    return volume


def stub_upload_volume_to_image_service(self, context, volume, metadata,
                                        force):
    ret = {"id": volume['id'],
           "updated_at": datetime.datetime(1, 1, 1, 1, 1, 1),
           "status": 'uploading',
           "display_description": volume['display_description'],
           "size": volume['size'],
           "volume_type": volume['volume_type'],
           "image_id": 1,
           "container_format": 'bare',
           "disk_format": 'raw',
           "image_name": 'image_name'}
    return ret


class VolumeImageActionsTest(test.TestCase):
    def setUp(self):
        super(VolumeImageActionsTest, self).setUp()
        self.controller = volume_actions.VolumeActionsController()

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

    def test_copy_volume_to_image(self):
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v1/tenant1/volumes/%s/action' % id)
        res_dict = self.controller._volume_upload_image(req, id, body)
        expected = {'os-volume_upload_image': {'id': id,
                           'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                           'status': 'uploading',
                           'display_description': 'displaydesc',
                           'size': 1,
                           'volume_type': {'name': 'vol_type_name'},
                           'image_id': 1,
                           'container_format': 'bare',
                           'disk_format': 'raw',
                           'image_name': 'image_name'}}
        self.assertDictMatch(res_dict, expected)

    def test_copy_volume_to_image_volumenotfound(self):
        def stub_volume_get_raise_exc(self, context, volume_id):
            raise exception.VolumeNotFound(volume_id=volume_id)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get_raise_exc)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v1/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_invalidvolume(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                               metadata, force):
            raise exception.InvalidVolume
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v1/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_valueerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                               metadata, force):
            raise ValueError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v1/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_remoteerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                               metadata, force):
            raise rpc_common.RemoteError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v1/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

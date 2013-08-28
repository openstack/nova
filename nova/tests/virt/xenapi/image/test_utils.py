# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

from nova.image import glance
from nova import test
from nova.virt.xenapi.image import utils


class GlanceImageTestCase(test.TestCase):
    def _get_image(self):
        return utils.GlanceImage('context', 'href')

    def _stub_out_glance_services(self):
        image_service = self.mox.CreateMock(glance.GlanceImageService)
        self.mox.StubOutWithMock(utils.glance, 'get_remote_image_service')
        utils.glance.get_remote_image_service('context', 'href').AndReturn(
            (image_service, 'id'))
        return image_service

    def test__image_id(self):
        self._stub_out_glance_services()
        self.mox.ReplayAll()

        image = self._get_image()

        self.assertEquals('id', image._image_id)

    def test__image_service(self):
        image_service = self._stub_out_glance_services()
        self.mox.ReplayAll()

        image = self._get_image()
        self.assertEquals(image_service, image._image_service)

    def test_meta(self):
        image_service = self._stub_out_glance_services()
        image_service.show('context', 'id').AndReturn('metadata')
        self.mox.ReplayAll()

        image = self._get_image()
        self.assertEquals('metadata', image.meta)

    def test_meta_caching(self):
        image_service = self._stub_out_glance_services()
        self.mox.ReplayAll()

        image = self._get_image()
        image._cached_meta = 'metadata'
        self.assertEquals('metadata', image.meta)

    def test_download_to(self):
        image_service = self._stub_out_glance_services()
        image_service.download('context', 'id', 'fobj').AndReturn('result')
        self.mox.ReplayAll()

        image = self._get_image()
        self.assertEquals('result', image.download_to('fobj'))


class RawImageTestCase(test.TestCase):
    def test_get_size(self):
        glance_image = self.mox.CreateMock(utils.GlanceImage)
        glance_image.meta = {'size': '123'}
        raw_image = utils.RawImage(glance_image)
        self.mox.ReplayAll()

        self.assertEquals(123, raw_image.get_size())

    def test_stream_to(self):
        glance_image = self.mox.CreateMock(utils.GlanceImage)
        glance_image.download_to('file').AndReturn('result')
        raw_image = utils.RawImage(glance_image)
        self.mox.ReplayAll()

        self.assertEquals('result', raw_image.stream_to('file'))

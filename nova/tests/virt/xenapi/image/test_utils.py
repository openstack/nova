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

import tarfile

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

    def test_is_raw_tgz_empty_meta(self):
        self._stub_out_glance_services()
        self.mox.ReplayAll()

        image = self._get_image()
        image._cached_meta = {}

        self.assertEquals(False, image.is_raw_tgz())

    def test_is_raw_tgz_for_raw_tgz(self):
        self._stub_out_glance_services()
        self.mox.ReplayAll()

        image = self._get_image()
        image._cached_meta = {'disk_format': 'raw', 'container_format': 'tgz'}

        self.assertEquals(True, image.is_raw_tgz())

    def test_data(self):
        image_service = self._stub_out_glance_services()
        image_service.download('context', 'id').AndReturn('data')
        self.mox.ReplayAll()

        image = self._get_image()

        self.assertEquals('data', image.data())


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


class TestIterableBasedFile(test.TestCase):
    def test_constructor(self):
        class FakeIterable(object):
            def __iter__(_self):
                return 'iterator'

        the_file = utils.IterableToFileAdapter(FakeIterable())

        self.assertEquals('iterator', the_file.iterator)

    def test_read_one_character(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEquals('c', the_file.read(1))

    def test_read_stores_remaining_characters(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        the_file.read(1)

        self.assertEquals('hunk1', the_file.remaining_data)

    def test_read_remaining_characters(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEquals('c', the_file.read(1))
        self.assertEquals('h', the_file.read(1))

    def test_read_reached_end_of_file(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEquals('chunk1', the_file.read(100))
        self.assertEquals('chunk2', the_file.read(100))
        self.assertEquals('', the_file.read(100))

    def test_empty_chunks(self):
        the_file = utils.IterableToFileAdapter([
            '', '', 'chunk2'
        ])

        self.assertEquals('chunk2', the_file.read(100))


class RawTGZTestCase(test.TestCase):
    def test_as_tarfile(self):
        image = utils.RawTGZImage(None)
        self.mox.StubOutWithMock(image, '_as_file')
        self.mox.StubOutWithMock(utils.tarfile, 'open')

        image._as_file().AndReturn('the_file')
        utils.tarfile.open(mode='r|gz', fileobj='the_file').AndReturn('tf')

        self.mox.ReplayAll()

        result = image._as_tarfile()
        self.assertEquals('tf', result)

    def test_as_file(self):
        self.mox.StubOutWithMock(utils, 'IterableToFileAdapter')
        glance_image = self.mox.CreateMock(utils.GlanceImage)
        image = utils.RawTGZImage(glance_image)
        glance_image.data().AndReturn('iterable-data')
        utils.IterableToFileAdapter('iterable-data').AndReturn('data-as-file')

        self.mox.ReplayAll()

        result = image._as_file()

        self.assertEquals('data-as-file', result)

    def test_get_size(self):
        tar_file = self.mox.CreateMock(tarfile.TarFile)
        tar_info = self.mox.CreateMock(tarfile.TarInfo)

        image = utils.RawTGZImage(None)

        self.mox.StubOutWithMock(image, '_as_tarfile')

        image._as_tarfile().AndReturn(tar_file)
        tar_file.next().AndReturn(tar_info)
        tar_info.size = 124

        self.mox.ReplayAll()

        result = image.get_size()

        self.assertEquals(124, result)
        self.assertEquals(image._tar_info, tar_info)
        self.assertEquals(image._tar_file, tar_file)

    def test_get_size_called_twice(self):
        tar_file = self.mox.CreateMock(tarfile.TarFile)
        tar_info = self.mox.CreateMock(tarfile.TarInfo)

        image = utils.RawTGZImage(None)

        self.mox.StubOutWithMock(image, '_as_tarfile')

        image._as_tarfile().AndReturn(tar_file)
        tar_file.next().AndReturn(tar_info)
        tar_info.size = 124

        self.mox.ReplayAll()

        image.get_size()
        result = image.get_size()

        self.assertEquals(124, result)
        self.assertEquals(image._tar_info, tar_info)
        self.assertEquals(image._tar_file, tar_file)

    def test_stream_to_without_size_retrieved(self):
        source_tar = self.mox.CreateMock(tarfile.TarFile)
        first_tarinfo = self.mox.CreateMock(tarfile.TarInfo)
        target_file = self.mox.CreateMock(file)
        source_file = self.mox.CreateMock(file)

        image = utils.RawTGZImage(None)
        image._image_service_and_image_id = ('service', 'id')

        self.mox.StubOutWithMock(image, '_as_tarfile', source_tar)
        self.mox.StubOutWithMock(utils.shutil, 'copyfileobj')

        image._as_tarfile().AndReturn(source_tar)
        source_tar.next().AndReturn(first_tarinfo)
        source_tar.extractfile(first_tarinfo).AndReturn(source_file)
        utils.shutil.copyfileobj(source_file, target_file)
        source_tar.close()

        self.mox.ReplayAll()

        image.stream_to(target_file)

    def test_stream_to_with_size_retrieved(self):
        source_tar = self.mox.CreateMock(tarfile.TarFile)
        first_tarinfo = self.mox.CreateMock(tarfile.TarInfo)
        target_file = self.mox.CreateMock(file)
        source_file = self.mox.CreateMock(file)
        first_tarinfo.size = 124

        image = utils.RawTGZImage(None)
        image._image_service_and_image_id = ('service', 'id')

        self.mox.StubOutWithMock(image, '_as_tarfile', source_tar)
        self.mox.StubOutWithMock(utils.shutil, 'copyfileobj')

        image._as_tarfile().AndReturn(source_tar)
        source_tar.next().AndReturn(first_tarinfo)
        source_tar.extractfile(first_tarinfo).AndReturn(source_file)
        utils.shutil.copyfileobj(source_file, target_file)
        source_tar.close()

        self.mox.ReplayAll()

        image.get_size()
        image.stream_to(target_file)

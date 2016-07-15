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

import mock

from nova import test
from nova.virt.xenapi.image import utils


@mock.patch.object(utils, 'IMAGE_API')
class GlanceImageTestCase(test.NoDBTestCase):

    def _get_image(self):
        return utils.GlanceImage(mock.sentinel.context,
                                 mock.sentinel.image_ref)

    def test_meta(self, mocked):
        mocked.get.return_value = mock.sentinel.meta

        image = self._get_image()
        self.assertEqual(mock.sentinel.meta, image.meta)
        mocked.get.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.image_ref)

    def test_download_to(self, mocked):
        mocked.download.return_value = None

        image = self._get_image()
        result = image.download_to(mock.sentinel.fobj)
        self.assertIsNone(result)
        mocked.download.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.image_ref,
                                                mock.sentinel.fobj)

    def test_is_raw_tgz_empty_meta(self, mocked):
        mocked.get.return_value = {}

        image = self._get_image()
        self.assertFalse(image.is_raw_tgz())

    def test_is_raw_tgz_for_raw_tgz(self, mocked):
        mocked.get.return_value = {
            'disk_format': 'raw',
            'container_format': 'tgz'
        }

        image = self._get_image()
        self.assertTrue(image.is_raw_tgz())

    def test_data(self, mocked):
        mocked.download.return_value = mock.sentinel.image
        image = self._get_image()

        self.assertEqual(mock.sentinel.image, image.data())


class RawImageTestCase(test.NoDBTestCase):
    @mock.patch.object(utils, 'GlanceImage', spec_set=True, autospec=True)
    def test_get_size(self, mock_glance_image):
        mock_glance_image.meta = {'size': '123'}
        raw_image = utils.RawImage(mock_glance_image)

        self.assertEqual(123, raw_image.get_size())

    @mock.patch.object(utils, 'GlanceImage', spec_set=True, autospec=True)
    def test_stream_to(self, mock_glance_image):
        mock_glance_image.download_to.return_value = 'result'
        raw_image = utils.RawImage(mock_glance_image)

        self.assertEqual('result', raw_image.stream_to('file'))
        mock_glance_image.download_to.assert_called_once_with('file')


class TestIterableBasedFile(test.NoDBTestCase):
    def test_constructor(self):
        class FakeIterable(object):
            def __iter__(_self):
                return 'iterator'

        the_file = utils.IterableToFileAdapter(FakeIterable())

        self.assertEqual('iterator', the_file.iterator)

    def test_read_one_character(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEqual('c', the_file.read(1))

    def test_read_stores_remaining_characters(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        the_file.read(1)

        self.assertEqual('hunk1', the_file.remaining_data)

    def test_read_remaining_characters(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEqual('c', the_file.read(1))
        self.assertEqual('h', the_file.read(1))

    def test_read_reached_end_of_file(self):
        the_file = utils.IterableToFileAdapter([
            'chunk1', 'chunk2'
        ])

        self.assertEqual('chunk1', the_file.read(100))
        self.assertEqual('chunk2', the_file.read(100))
        self.assertEqual('', the_file.read(100))

    def test_empty_chunks(self):
        the_file = utils.IterableToFileAdapter([
            '', '', 'chunk2'
        ])

        self.assertEqual('chunk2', the_file.read(100))


class RawTGZTestCase(test.NoDBTestCase):
    @mock.patch.object(utils.RawTGZImage, '_as_file', return_value='the_file')
    @mock.patch.object(utils.tarfile, 'open', return_value='tf')
    def test_as_tarfile(self, mock_open, mock_as_file):
        image = utils.RawTGZImage(None)
        result = image._as_tarfile()
        self.assertEqual('tf', result)
        mock_as_file.assert_called_once_with()
        mock_open.assert_called_once_with(mode='r|gz', fileobj='the_file')

    @mock.patch.object(utils, 'GlanceImage', spec_set=True, autospec=True)
    @mock.patch.object(utils, 'IterableToFileAdapter',
                       return_value='data-as-file')
    def test_as_file(self, mock_adapter, mock_glance_image):
        mock_glance_image.data.return_value = 'iterable-data'
        image = utils.RawTGZImage(mock_glance_image)
        result = image._as_file()
        self.assertEqual('data-as-file', result)
        mock_glance_image.data.assert_called_once_with()
        mock_adapter.assert_called_once_with('iterable-data')

    @mock.patch.object(tarfile, 'TarFile', spec_set=True, autospec=True)
    @mock.patch.object(tarfile, 'TarInfo', autospec=True)
    @mock.patch.object(utils.RawTGZImage, '_as_tarfile')
    def test_get_size(self, mock_as_tar, mock_tar_info, mock_tar_file):
        mock_tar_file.next.return_value = mock_tar_info
        mock_tar_info.size = 124
        mock_as_tar.return_value = mock_tar_file

        image = utils.RawTGZImage(None)
        result = image.get_size()

        self.assertEqual(124, result)
        self.assertEqual(image._tar_info, mock_tar_info)
        self.assertEqual(image._tar_file, mock_tar_file)
        mock_as_tar.assert_called_once_with()
        mock_tar_file.next.assert_called_once_with()

    @mock.patch.object(tarfile, 'TarFile', spec_set=True, autospec=True)
    @mock.patch.object(tarfile, 'TarInfo', autospec=True)
    @mock.patch.object(utils.RawTGZImage, '_as_tarfile')
    def test_get_size_called_twice(self, mock_as_tar, mock_tar_info,
                                   mock_tar_file):
        mock_tar_file.next.return_value = mock_tar_info
        mock_tar_info.size = 124
        mock_as_tar.return_value = mock_tar_file

        image = utils.RawTGZImage(None)
        image.get_size()
        result = image.get_size()

        self.assertEqual(124, result)
        self.assertEqual(image._tar_info, mock_tar_info)
        self.assertEqual(image._tar_file, mock_tar_file)
        mock_as_tar.assert_called_once_with()
        mock_tar_file.next.assert_called_once_with()

    @mock.patch.object(tarfile, 'TarFile', spec_set=True, autospec=True)
    @mock.patch.object(tarfile, 'TarInfo', spec_set=True, autospec=True)
    @mock.patch.object(utils.RawTGZImage, '_as_tarfile')
    @mock.patch.object(utils.shutil, 'copyfileobj')
    def test_stream_to_without_size_retrieved(self, mock_copyfile,
                                              mock_as_tar, mock_tar_info,
                                              mock_tar_file):
        target_file = mock.create_autospec(open)
        source_file = mock.create_autospec(open)
        mock_tar_file.next.return_value = mock_tar_info
        mock_tar_file.extractfile.return_value = source_file
        mock_as_tar.return_value = mock_tar_file

        image = utils.RawTGZImage(None)
        image._image_service_and_image_id = ('service', 'id')
        image.stream_to(target_file)

        mock_as_tar.assert_called_once_with()
        mock_tar_file.next.assert_called_once_with()
        mock_tar_file.extractfile.assert_called_once_with(mock_tar_info)
        mock_copyfile.assert_called_once_with(
            source_file, target_file)
        mock_tar_file.close.assert_called_once_with()

    @mock.patch.object(tarfile, 'TarFile', spec_set=True, autospec=True)
    @mock.patch.object(tarfile, 'TarInfo', autospec=True)
    @mock.patch.object(utils.RawTGZImage, '_as_tarfile')
    @mock.patch.object(utils.shutil, 'copyfileobj')
    def test_stream_to_with_size_retrieved(self, mock_copyfile,
                                           mock_as_tar, mock_tar_info,
                                           mock_tar_file):
        target_file = mock.create_autospec(open)
        source_file = mock.create_autospec(open)
        mock_tar_info.size = 124
        mock_tar_file.next.return_value = mock_tar_info
        mock_tar_file.extractfile.return_value = source_file
        mock_as_tar.return_value = mock_tar_file

        image = utils.RawTGZImage(None)
        image._image_service_and_image_id = ('service', 'id')
        image.get_size()
        image.stream_to(target_file)

        mock_as_tar.assert_called_once_with()
        mock_tar_file.next.assert_called_once_with()
        mock_tar_file.extractfile.assert_called_once_with(mock_tar_info)
        mock_copyfile.assert_called_once_with(
            source_file, target_file)
        mock_tar_file.close.assert_called_once_with()

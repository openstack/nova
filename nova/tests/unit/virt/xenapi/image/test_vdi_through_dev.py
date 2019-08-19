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

import contextlib
import tarfile

import eventlet
import mock
from os_xenapi.client import session as xenapi_session
import six

from nova.image import glance
from nova import test
from nova.virt.xenapi.image import vdi_through_dev


@contextlib.contextmanager
def fake_context(result=None):
    yield result


class TestDelegatingToCommand(test.NoDBTestCase):
    def test_upload_image_is_delegated_to_command(self):
        command = mock.create_autospec(vdi_through_dev.UploadToGlanceAsRawTgz,
                                       spec_set=True)
        command.upload_image.return_value = 'result'

        with mock.patch.object(vdi_through_dev, 'UploadToGlanceAsRawTgz',
                               return_value=command) as mock_upload:
            store = vdi_through_dev.VdiThroughDevStore()
            result = store.upload_image(
                'ctx', 'session', 'instance', 'image_id', 'vdis')

            self.assertEqual('result', result)
            mock_upload.assert_called_once_with(
                'ctx', 'session', 'instance', 'image_id', 'vdis')
            command.upload_image.assert_called_once_with()


class TestUploadToGlanceAsRawTgz(test.NoDBTestCase):
    @mock.patch.object(vdi_through_dev.vm_utils, 'vdi_attached')
    @mock.patch.object(vdi_through_dev.utils, 'make_dev_path')
    @mock.patch.object(vdi_through_dev.utils, 'temporary_chown')
    def test_upload_image(self, mock_vdi_temp_chown,
                          mock_vdi_make_dev_path, mock_vdi_attached):
        mock_vdi_attached.return_value = fake_context('dev')
        mock_vdi_make_dev_path.return_value = 'devpath'
        mock_vdi_temp_chown.return_value = fake_context()

        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])

        with test.nested(
            mock.patch.object(store, '_perform_upload'),
            mock.patch.object(store, '_get_vdi_ref',
                              return_value='vdi_ref'),
        ) as (mock_upload, mock_get_vdi):

            store.upload_image()

            mock_get_vdi.assert_called_once_with()
            mock_upload.assert_called_once_with('devpath')
            mock_vdi_attached.assert_called_once_with(
                'session', 'vdi_ref', read_only=True)
            mock_vdi_make_dev_path.assert_called_once_with('dev')
            mock_vdi_temp_chown.assert_called_once_with('devpath')

    def test__perform_upload(self):
        producer = mock.create_autospec(vdi_through_dev.TarGzProducer,
                                        spec_set=True)
        consumer = mock.create_autospec(glance.UpdateGlanceImage,
                                        spec_set=True)
        pool = mock.create_autospec(eventlet.GreenPool,
                                    spec_set=True)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])

        with test.nested(
            mock.patch.object(store, '_create_pipe',
                              return_value=('readfile', 'writefile')),
            mock.patch.object(store, '_get_virtual_size',
                              return_value='324'),
            mock.patch.object(glance, 'UpdateGlanceImage',
                              return_value=consumer),
            mock.patch.object(vdi_through_dev, 'TarGzProducer',
                              return_value=producer),
            mock.patch.object(vdi_through_dev.eventlet, 'GreenPool',
                              return_value=pool)
        ) as (mock_create_pipe, mock_virtual_size,
              mock_upload, mock_TarGzProducer, mock_greenpool):
            producer.get_metadata.return_value = "metadata"

            store._perform_upload('devpath')

            producer.get_metadata.assert_called_once_with()
            mock_virtual_size.assert_called_once_with()
            mock_create_pipe.assert_called_once_with()
            mock_TarGzProducer.assert_called_once_with(
                'devpath', 'writefile', '324', 'disk.raw')
            mock_upload.assert_called_once_with(
                'context', 'id', 'metadata', 'readfile')
            mock_greenpool.assert_called_once_with()
            pool.spawn.assert_has_calls([mock.call(producer.start),
                                         mock.call(consumer.start)])
            pool.waitall.assert_called_once_with()

    def test__get_vdi_ref(self):
        session = mock.create_autospec(xenapi_session.XenAPISession,
                                       spec_set=True)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', session, 'instance', 'id', ['vdi0', 'vdi1'])
        session.call_xenapi.return_value = 'vdi_ref'

        self.assertEqual('vdi_ref', store._get_vdi_ref())
        session.call_xenapi.assert_called_once_with(
            'VDI.get_by_uuid', 'vdi0')

    def test__get_virtual_size(self):
        session = mock.create_autospec(xenapi_session.XenAPISession,
                                       spec_set=True)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', session, 'instance', 'id', ['vdi0', 'vdi1'])

        with mock.patch.object(store, '_get_vdi_ref',
                               return_value='vdi_ref') as mock_get_vdi:
            store._get_virtual_size()

            mock_get_vdi.assert_called_once_with()
            session.call_xenapi.assert_called_once_with(
                'VDI.get_virtual_size', 'vdi_ref')

    @mock.patch.object(vdi_through_dev.os, 'pipe')
    @mock.patch.object(vdi_through_dev.greenio, 'GreenPipe')
    def test__create_pipe(self, mock_vdi_greenpipe, mock_vdi_os_pipe):
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])

        mock_vdi_os_pipe.return_value = ('rpipe', 'wpipe')
        mock_vdi_greenpipe.side_effect = ['rfile', 'wfile']

        result = store._create_pipe()
        self.assertEqual(('rfile', 'wfile'), result)
        mock_vdi_os_pipe.assert_called_once_with()
        mock_vdi_greenpipe.assert_has_calls(
            [mock.call('rpipe', 'rb', 0),
             mock.call('wpipe', 'wb', 0)])


class TestTarGzProducer(test.NoDBTestCase):
    def test_constructor(self):
        producer = vdi_through_dev.TarGzProducer('devpath', 'writefile',
            '100', 'fname')

        self.assertEqual('devpath', producer.fpath)
        self.assertEqual('writefile', producer.output)
        self.assertEqual('100', producer.size)
        self.assertEqual('writefile', producer.output)

    @mock.patch.object(vdi_through_dev.tarfile, 'TarInfo')
    @mock.patch.object(vdi_through_dev.tarfile, 'open')
    def test_start(self, mock_tar_open, mock_tar_TarInfo):
        outf = six.StringIO()
        producer = vdi_through_dev.TarGzProducer('fpath', outf,
                                                 '100', 'fname')

        tfile = mock.create_autospec(tarfile.TarFile, spec_set=True)
        tinfo = mock.create_autospec(tarfile.TarInfo)

        inf = mock.create_autospec(open, spec_set=True)

        mock_tar_open.return_value = fake_context(tfile)
        mock_tar_TarInfo.return_value = tinfo

        with mock.patch.object(producer, '_open_file',
                               return_value=fake_context(inf)
                               ) as mock_open_file:
            producer.start()

            self.assertEqual(100, tinfo.size)
            mock_tar_TarInfo.assert_called_once_with(name='fname')
            mock_tar_open.assert_called_once_with(fileobj=outf, mode='w|gz')
            mock_open_file.assert_called_once_with('fpath', 'rb')
            tfile.addfile.assert_called_once_with(tinfo, fileobj=inf)

    def test_get_metadata(self):
        producer = vdi_through_dev.TarGzProducer('devpath', 'writefile',
            '100', 'fname')

        self.assertEqual({
            'disk_format': 'raw',
            'container_format': 'tgz'},
            producer.get_metadata())

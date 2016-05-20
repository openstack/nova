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
import six

from nova.image import glance
from nova import test
from nova.virt.xenapi.client import session as xenapi_session
from nova.virt.xenapi.image import vdi_through_dev


@contextlib.contextmanager
def fake_context(result=None):
    yield result


class TestDelegatingToCommand(test.NoDBTestCase):
    def test_upload_image_is_delegated_to_command(self):
        command = self.mox.CreateMock(vdi_through_dev.UploadToGlanceAsRawTgz)
        self.mox.StubOutWithMock(vdi_through_dev, 'UploadToGlanceAsRawTgz')
        vdi_through_dev.UploadToGlanceAsRawTgz(
            'ctx', 'session', 'instance', 'image_id', 'vdis').AndReturn(
                command)
        command.upload_image().AndReturn('result')
        self.mox.ReplayAll()

        store = vdi_through_dev.VdiThroughDevStore()
        result = store.upload_image(
            'ctx', 'session', 'instance', 'image_id', 'vdis')

        self.assertEqual('result', result)


class TestUploadToGlanceAsRawTgz(test.NoDBTestCase):
    def test_upload_image(self):
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])
        self.mox.StubOutWithMock(store, '_perform_upload')
        self.mox.StubOutWithMock(store, '_get_vdi_ref')
        self.mox.StubOutWithMock(vdi_through_dev, 'glance')
        self.mox.StubOutWithMock(vdi_through_dev, 'vm_utils')
        self.mox.StubOutWithMock(vdi_through_dev, 'utils')

        store._get_vdi_ref().AndReturn('vdi_ref')
        vdi_through_dev.vm_utils.vdi_attached_here(
            'session', 'vdi_ref', read_only=True).AndReturn(
                fake_context('dev'))
        vdi_through_dev.utils.make_dev_path('dev').AndReturn('devpath')
        vdi_through_dev.utils.temporary_chown('devpath').AndReturn(
            fake_context())
        store._perform_upload('devpath')

        self.mox.ReplayAll()

        store.upload_image()

    def test__perform_upload(self):
        producer = self.mox.CreateMock(vdi_through_dev.TarGzProducer)
        consumer = self.mox.CreateMock(glance.UpdateGlanceImage)
        pool = self.mox.CreateMock(eventlet.GreenPool)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])
        self.mox.StubOutWithMock(store, '_create_pipe')
        self.mox.StubOutWithMock(store, '_get_virtual_size')
        self.mox.StubOutWithMock(producer, 'get_metadata')
        self.mox.StubOutWithMock(vdi_through_dev, 'TarGzProducer')
        self.mox.StubOutWithMock(glance, 'UpdateGlanceImage')
        self.mox.StubOutWithMock(vdi_through_dev, 'eventlet')

        producer.get_metadata().AndReturn('metadata')
        store._get_virtual_size().AndReturn('324')
        store._create_pipe().AndReturn(('readfile', 'writefile'))
        vdi_through_dev.TarGzProducer(
            'devpath', 'writefile', '324', 'disk.raw').AndReturn(
                producer)
        glance.UpdateGlanceImage('context', 'id', 'metadata',
            'readfile').AndReturn(consumer)
        vdi_through_dev.eventlet.GreenPool().AndReturn(pool)
        pool.spawn(producer.start)
        pool.spawn(consumer.start)
        pool.waitall()

        self.mox.ReplayAll()

        store._perform_upload('devpath')

    def test__get_vdi_ref(self):
        session = self.mox.CreateMock(xenapi_session.XenAPISession)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', session, 'instance', 'id', ['vdi0', 'vdi1'])
        session.call_xenapi('VDI.get_by_uuid', 'vdi0').AndReturn('vdi_ref')

        self.mox.ReplayAll()

        self.assertEqual('vdi_ref', store._get_vdi_ref())

    def test__get_virtual_size(self):
        session = self.mox.CreateMock(xenapi_session.XenAPISession)
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', session, 'instance', 'id', ['vdi0', 'vdi1'])
        self.mox.StubOutWithMock(store, '_get_vdi_ref')
        store._get_vdi_ref().AndReturn('vdi_ref')
        session.call_xenapi('VDI.get_virtual_size', 'vdi_ref')

        self.mox.ReplayAll()

        store._get_virtual_size()

    def test__create_pipe(self):
        store = vdi_through_dev.UploadToGlanceAsRawTgz(
            'context', 'session', 'instance', 'id', ['vdi0', 'vdi1'])
        self.mox.StubOutWithMock(vdi_through_dev, 'os')
        self.mox.StubOutWithMock(vdi_through_dev, 'greenio')
        vdi_through_dev.os.pipe().AndReturn(('rpipe', 'wpipe'))
        vdi_through_dev.greenio.GreenPipe('rpipe', 'rb', 0).AndReturn('rfile')
        vdi_through_dev.greenio.GreenPipe('wpipe', 'wb', 0).AndReturn('wfile')

        self.mox.ReplayAll()

        result = store._create_pipe()
        self.assertEqual(('rfile', 'wfile'), result)


class TestTarGzProducer(test.NoDBTestCase):
    def test_constructor(self):
        producer = vdi_through_dev.TarGzProducer('devpath', 'writefile',
            '100', 'fname')

        self.assertEqual('devpath', producer.fpath)
        self.assertEqual('writefile', producer.output)
        self.assertEqual('100', producer.size)
        self.assertEqual('writefile', producer.output)

    def test_start(self):
        outf = six.StringIO()
        producer = vdi_through_dev.TarGzProducer('fpath', outf,
            '100', 'fname')

        tfile = self.mox.CreateMock(tarfile.TarFile)
        tinfo = self.mox.CreateMock(tarfile.TarInfo)

        inf = self.mox.CreateMock(open)

        self.mox.StubOutWithMock(vdi_through_dev, 'tarfile')
        self.mox.StubOutWithMock(producer, '_open_file')

        vdi_through_dev.tarfile.TarInfo(name='fname').AndReturn(tinfo)
        vdi_through_dev.tarfile.open(fileobj=outf, mode='w|gz').AndReturn(
            fake_context(tfile))
        producer._open_file('fpath', 'rb').AndReturn(fake_context(inf))
        tfile.addfile(tinfo, fileobj=inf)
        outf.close()

        self.mox.ReplayAll()

        producer.start()

        self.assertEqual(100, tinfo.size)

    def test_get_metadata(self):
        producer = vdi_through_dev.TarGzProducer('devpath', 'writefile',
            '100', 'fname')

        self.assertEqual({
            'disk_format': 'raw',
            'container_format': 'tgz'},
            producer.get_metadata())

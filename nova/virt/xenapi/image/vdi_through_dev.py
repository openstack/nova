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
import os
import tarfile

import eventlet
from eventlet import greenio

from nova.image import glance
from nova import utils
from nova.virt.xenapi import vm_utils


class VdiThroughDevStore(object):
    """Deal with virtual disks by attaching them to the OS domU.

    At the moment it supports upload to Glance, and the upload format is a raw
    disk inside a tgz.
    """

    def upload_image(self, context, session, instance, image_id, vdi_uuids):
        command = UploadToGlanceAsRawTgz(
            context, session, instance, image_id, vdi_uuids)
        return command.upload_image()

    def download_image(self, context, session, instance, image_id):
        # TODO(matelakat) Move through-dev image download functionality to this
        # method.
        raise NotImplementedError()


class UploadToGlanceAsRawTgz(object):
    def __init__(self, context, session, instance, image_id, vdi_uuids):
        self.context = context
        self.image_id = image_id
        self.session = session
        self.vdi_uuids = vdi_uuids

    def _get_virtual_size(self):
        return self.session.call_xenapi(
            'VDI.get_virtual_size', self._get_vdi_ref())

    def _get_vdi_ref(self):
        return self.session.call_xenapi('VDI.get_by_uuid', self.vdi_uuids[0])

    def _perform_upload(self, devpath):
        readfile, writefile = self._create_pipe()
        size = self._get_virtual_size()
        producer = TarGzProducer(devpath, writefile, size, 'disk.raw')
        consumer = glance.UpdateGlanceImage(
            self.context, self.image_id, producer.get_metadata(), readfile)
        pool = eventlet.GreenPool()
        pool.spawn(producer.start)
        pool.spawn(consumer.start)
        pool.waitall()

    def _create_pipe(self):
        rpipe, wpipe = os.pipe()
        rfile = greenio.GreenPipe(rpipe, 'rb', 0)
        wfile = greenio.GreenPipe(wpipe, 'wb', 0)
        return rfile, wfile

    def upload_image(self):
        vdi_ref = self._get_vdi_ref()
        with vm_utils.vdi_attached(self.session, vdi_ref,
                                   read_only=True) as dev:
            devpath = utils.make_dev_path(dev)
            with utils.temporary_chown(devpath):
                self._perform_upload(devpath)


class TarGzProducer(object):
    def __init__(self, devpath, writefile, size, fname):
        self.fpath = devpath
        self.output = writefile
        self.size = size
        self.fname = fname

    def get_metadata(self):
        return {
            'disk_format': 'raw',
            'container_format': 'tgz'
        }

    def start(self):
        with contextlib.closing(self.output):
            tinfo = tarfile.TarInfo(name=self.fname)
            tinfo.size = int(self.size)
            with tarfile.open(fileobj=self.output, mode='w|gz') as tfile:
                with self._open_file(self.fpath, 'rb') as input_file:
                    tfile.addfile(tinfo, fileobj=input_file)

    def _open_file(self, *args):
        return open(*args)

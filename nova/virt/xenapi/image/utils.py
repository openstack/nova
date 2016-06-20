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

import shutil
import tarfile

from nova import image

_VDI_FORMAT_RAW = 1

IMAGE_API = image.API()


class GlanceImage(object):
    def __init__(self, context, image_href_or_id):
        self._context = context
        self._image_id = image_href_or_id
        self._cached_meta = None

    @property
    def meta(self):
        if self._cached_meta is None:
            self._cached_meta = IMAGE_API.get(self._context, self._image_id)
        return self._cached_meta

    def download_to(self, fileobj):
        return IMAGE_API.download(self._context, self._image_id, fileobj)

    def is_raw_tgz(self):
        return ['raw', 'tgz'] == [
            self.meta.get(key) for key in ('disk_format', 'container_format')]

    def data(self):
        return IMAGE_API.download(self._context, self._image_id)


class RawImage(object):
    def __init__(self, glance_image):
        self.glance_image = glance_image

    def get_size(self):
        return int(self.glance_image.meta['size'])

    def stream_to(self, fileobj):
        return self.glance_image.download_to(fileobj)


class IterableToFileAdapter(object):
    """A degenerate file-like so that an iterable could be read like a file.

    As Glance client returns an iterable, but tarfile requires a file like,
    this is the adapter between the two. This allows tarfile to access the
    glance stream.
    """

    def __init__(self, iterable):
        self.iterator = iterable.__iter__()
        self.remaining_data = ''

    def read(self, size):
        chunk = self.remaining_data
        try:
            while not chunk:
                chunk = next(self.iterator)
        except StopIteration:
            return ''
        return_value = chunk[0:size]
        self.remaining_data = chunk[size:]
        return return_value


class RawTGZImage(object):
    def __init__(self, glance_image):
        self.glance_image = glance_image
        self._tar_info = None
        self._tar_file = None

    def _as_file(self):
        return IterableToFileAdapter(self.glance_image.data())

    def _as_tarfile(self):
        return tarfile.open(mode='r|gz', fileobj=self._as_file())

    def get_size(self):
        if self._tar_file is None:
            self._tar_file = self._as_tarfile()
            self._tar_info = self._tar_file.next()
        return self._tar_info.size

    def stream_to(self, target_file):
        if self._tar_file is None:
            self._tar_file = self._as_tarfile()
            self._tar_info = self._tar_file.next()
        source_file = self._tar_file.extractfile(self._tar_info)
        shutil.copyfileobj(source_file, target_file)
        self._tar_file.close()

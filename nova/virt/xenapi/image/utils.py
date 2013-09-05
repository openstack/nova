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


class GlanceImage(object):
    def __init__(self, context, image_href_or_id):
        self._context = context
        self._image_service, self._image_id = glance.get_remote_image_service(
            context, image_href_or_id)
        self._cached_meta = None

    @property
    def meta(self):
        if self._cached_meta is None:
            self._cached_meta = self._image_service.show(
                self._context, self._image_id)
        return self._cached_meta

    def download_to(self, fileobj):
        return self._image_service.download(
            self._context, self._image_id, fileobj)


class RawImage(object):
    def __init__(self, glance_image):
        self.glance_image = glance_image

    def get_size(self):
        return int(self.glance_image.meta['size'])

    def stream_to(self, fileobj):
        return self.glance_image.download_to(fileobj)

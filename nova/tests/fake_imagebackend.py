# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Grid Dynamics
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

import os

from nova.virt.libvirt import config
from nova.virt.libvirt import imagebackend


class Backend(object):
    def __init__(self, use_cow):
        pass

    def image(self, instance, name, suffix='', image_type=''):
        class FakeImage(imagebackend.Image):
            def __init__(self, instance, name, suffix=''):
                self.path = os.path.join(instance, name + suffix)

            def create_image(self, prepare_template, base,
                              size, *args, **kwargs):
                pass

            def cache(self, fn, fname, size=None, *args, **kwargs):
                pass

            def libvirt_info(self, device_type):
                info = config.LibvirtConfigGuestDisk()
                info.source_type = 'file'
                info.source_device = device_type
                info.driver_format = 'raw'
                info.source_path = self.path
                return info

        return FakeImage(instance, name, suffix)

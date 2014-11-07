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

    def image(self, instance, name, image_type=''):
        class FakeImage(imagebackend.Image):
            def __init__(self, instance, name):
                self.path = os.path.join(instance['name'], name)

            def create_image(self, prepare_template, base,
                              size, *args, **kwargs):
                pass

            def cache(self, fetch_func, filename, size=None, *args, **kwargs):
                pass

            def snapshot(self, name):
                pass

            def libvirt_info(self, disk_bus, disk_dev, device_type,
                             cache_mode, extra_specs, hypervisor_version):
                info = config.LibvirtConfigGuestDisk()
                info.source_type = 'file'
                info.source_device = device_type
                info.target_bus = disk_bus
                info.target_dev = disk_dev
                info.driver_cache = cache_mode
                info.driver_format = 'raw'
                info.source_path = self.path
                return info

        return FakeImage(instance, name)

    def snapshot(self, instance, disk_path, image_type=''):
        # NOTE(bfilippov): this is done in favor for
        # snapshot tests in test_libvirt.LibvirtConnTestCase
        return imagebackend.Backend(True).snapshot(instance,
            disk_path,
            image_type=image_type)


class Raw(imagebackend.Image):
    # NOTE(spandhe) Added for test_rescue and test_rescue_config_drive
    def __init__(self, instance=None, disk_name=None, path=None):
        pass

    def _get_driver_format(self):
        pass

    def correct_format(self):
        pass

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        pass

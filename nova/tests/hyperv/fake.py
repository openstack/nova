# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Cloudbase Solutions Srl
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

import io
import os


class PathUtils(object):
    def open(self, path, mode):
        return io.BytesIO(b'fake content')

    def get_instances_path(self):
        return 'C:\\FakePath\\'

    def get_instance_path(self, instance_name):
        return os.path.join(self.get_instances_path(), instance_name)

    def get_vhd_path(self, instance_name):
        instance_path = self.get_instance_path(instance_name)
        return os.path.join(instance_path, instance_name + ".vhd")

    def get_base_vhd_path(self, image_name):
        base_dir = os.path.join(self.get_instances_path(), '_base')
        return os.path.join(base_dir, image_name + ".vhd")

    def make_export_path(self, instance_name):
        export_folder = os.path.join(self.get_instances_path(), "export",
                                     instance_name)
        return export_folder

    def vhd_exists(self, path):
        return False

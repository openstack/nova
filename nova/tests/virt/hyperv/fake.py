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

    def exists(self, path):
        return False

    def makedirs(self, path):
        pass

    def remove(self, path):
        pass

    def rename(self, src, dest):
        pass

    def copyfile(self, src, dest):
        pass

    def copy(self, src, dest):
        pass

    def rmtree(self, path):
        pass

    def get_instances_dir(self, remote_server=None):
        return 'C:\\FakeInstancesPath\\'

    def get_instance_migr_revert_dir(self, instance_name, create_dir=False,
                                     remove_dir=False):
        return os.path.join(self.get_instances_dir(), instance_name, '_revert')

    def get_instance_dir(self, instance_name, remote_server=None,
                         create_dir=True, remove_dir=False):
        return os.path.join(self.get_instances_dir(remote_server),
                            instance_name)

    def lookup_root_vhd_path(self, instance_name):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'root.vhd')

    def lookup_configdrive_path(self, instance_name):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'configdrive.iso')

    def lookup_ephemeral_vhd_path(self, instance_name):
        instance_path = self.get_instance_dir(instance_name)
        if instance_path:
            return os.path.join(instance_path, 'ephemeral.vhd')

    def get_root_vhd_path(self, instance_name, format_ext):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'root.' + format_ext)

    def get_ephemeral_vhd_path(self, instance_name, format_ext):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'ephemeral.' + format_ext.lower())

    def get_base_vhd_dir(self):
        return os.path.join(self.get_instances_dir(), '_base')

    def get_export_dir(self, instance_name):
        export_dir = os.path.join(self.get_instances_dir(), 'export',
                                  instance_name)
        return export_dir

    def vhd_exists(self, path):
        return False

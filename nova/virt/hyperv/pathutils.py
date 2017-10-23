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

import os
import six
import tempfile
import time

from os_win.utils import pathutils
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.i18n import _
from nova.virt.hyperv import constants

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

ERROR_INVALID_NAME = 123

# NOTE(claudiub): part of the pre-existing PathUtils is nova-specific and
# it does not belong in the os-win library. In order to ensure the same
# functionality with the least amount of changes necessary, adding as a mixin
# the os_win.pathutils.PathUtils class into this PathUtils.


class PathUtils(pathutils.PathUtils):

    def get_instances_dir(self, remote_server=None):
        local_instance_path = os.path.normpath(CONF.instances_path)

        if remote_server and not local_instance_path.startswith(r'\\'):
            if CONF.hyperv.instances_path_share:
                path = CONF.hyperv.instances_path_share
            else:
                # Use an administrative share
                path = local_instance_path.replace(':', '$')
            return ('\\\\%(remote_server)s\\%(path)s' %
                {'remote_server': remote_server, 'path': path})
        else:
            return local_instance_path

    def _get_instances_sub_dir(self, dir_name, remote_server=None,
                               create_dir=True, remove_dir=False):
        instances_path = self.get_instances_dir(remote_server)
        path = os.path.join(instances_path, dir_name)
        try:
            if remove_dir:
                self.check_remove_dir(path)
            if create_dir:
                self.check_create_dir(path)
            return path
        except WindowsError as ex:
            if ex.winerror == ERROR_INVALID_NAME:
                raise exception.AdminRequired(_(
                    "Cannot access \"%(instances_path)s\", make sure the "
                    "path exists and that you have the proper permissions. "
                    "In particular Nova-Compute must not be executed with the "
                    "builtin SYSTEM account or other accounts unable to "
                    "authenticate on a remote host.") %
                    {'instances_path': instances_path})
            raise

    def get_instance_migr_revert_dir(self, instance_name, create_dir=False,
                                     remove_dir=False):
        dir_name = '%s_revert' % instance_name
        return self._get_instances_sub_dir(dir_name, None, create_dir,
                                           remove_dir)

    def get_instance_dir(self, instance_name, remote_server=None,
                         create_dir=True, remove_dir=False):
        return self._get_instances_sub_dir(instance_name, remote_server,
                                           create_dir, remove_dir)

    def _lookup_vhd_path(self, instance_name, vhd_path_func,
                         *args, **kwargs):
        vhd_path = None
        for format_ext in ['vhd', 'vhdx']:
            test_path = vhd_path_func(instance_name, format_ext,
                                      *args, **kwargs)
            if self.exists(test_path):
                vhd_path = test_path
                break
        return vhd_path

    def lookup_root_vhd_path(self, instance_name, rescue=False):
        return self._lookup_vhd_path(instance_name, self.get_root_vhd_path,
                                     rescue)

    def lookup_configdrive_path(self, instance_name, rescue=False):
        configdrive_path = None
        for format_ext in constants.DISK_FORMAT_MAP:
            test_path = self.get_configdrive_path(instance_name, format_ext,
                                                  rescue=rescue)
            if self.exists(test_path):
                configdrive_path = test_path
                break
        return configdrive_path

    def lookup_ephemeral_vhd_path(self, instance_name, eph_name):
        return self._lookup_vhd_path(instance_name,
                                     self.get_ephemeral_vhd_path,
                                     eph_name)

    def get_root_vhd_path(self, instance_name, format_ext, rescue=False):
        instance_path = self.get_instance_dir(instance_name)
        image_name = 'root'
        if rescue:
            image_name += '-rescue'
        return os.path.join(instance_path,
                            image_name + '.' + format_ext.lower())

    def get_configdrive_path(self, instance_name, format_ext,
                             remote_server=None, rescue=False):
        instance_path = self.get_instance_dir(instance_name, remote_server)
        configdrive_image_name = 'configdrive'
        if rescue:
            configdrive_image_name += '-rescue'
        return os.path.join(instance_path,
                            configdrive_image_name + '.' + format_ext.lower())

    def get_ephemeral_vhd_path(self, instance_name, format_ext, eph_name):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, eph_name + '.' + format_ext.lower())

    def get_base_vhd_dir(self):
        return self._get_instances_sub_dir('_base')

    def get_export_dir(self, instance_name):
        dir_name = os.path.join('export', instance_name)
        return self._get_instances_sub_dir(dir_name, create_dir=True,
                                           remove_dir=True)

    def get_vm_console_log_paths(self, instance_name, remote_server=None):
        instance_dir = self.get_instance_dir(instance_name,
                                             remote_server)
        console_log_path = os.path.join(instance_dir, 'console.log')
        return console_log_path, console_log_path + '.1'

    def copy_vm_console_logs(self, instance_name, dest_host):
        local_log_paths = self.get_vm_console_log_paths(
            instance_name)
        remote_log_paths = self.get_vm_console_log_paths(
            instance_name, remote_server=dest_host)

        for local_log_path, remote_log_path in zip(local_log_paths,
                                                   remote_log_paths):
            if self.exists(local_log_path):
                self.copy(local_log_path, remote_log_path)

    def get_image_path(self, image_name):
        # Note: it is possible that the path doesn't exist
        base_dir = self.get_base_vhd_dir()
        for ext in ['vhd', 'vhdx']:
            file_path = os.path.join(base_dir,
                                     image_name + '.' + ext.lower())
            if self.exists(file_path):
                return file_path
        return None

    def get_age_of_file(self, file_name):
        return time.time() - os.path.getmtime(file_name)

    def check_dirs_shared_storage(self, src_dir, dest_dir):
        # Check if shared storage is being used by creating a temporary
        # file at the destination path and checking if it exists at the
        # source path.
        LOG.debug("Checking if %(src_dir)s and %(dest_dir)s point "
                  "to the same location.",
                  dict(src_dir=src_dir, dest_dir=dest_dir))

        try:
            with tempfile.NamedTemporaryFile(dir=dest_dir) as tmp_file:
                src_path = os.path.join(src_dir,
                                        os.path.basename(tmp_file.name))
                shared_storage = os.path.exists(src_path)
        except OSError as e:
            raise exception.FileNotFound(six.text_type(e))

        return shared_storage

    def check_remote_instances_dir_shared(self, dest):
        # Checks if the instances dir from a remote host points
        # to the same storage location as the local instances dir.
        local_inst_dir = self.get_instances_dir()
        remote_inst_dir = self.get_instances_dir(dest)
        return self.check_dirs_shared_storage(local_inst_dir,
                                              remote_inst_dir)

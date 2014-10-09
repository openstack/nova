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
import shutil
import sys

if sys.platform == 'win32':
    import wmi

from oslo.config import cfg

from nova.i18n import _
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.hyperv import constants
from nova.virt.hyperv import vmutils

LOG = logging.getLogger(__name__)

hyperv_opts = [
    cfg.StrOpt('instances_path_share',
               default="",
               help='The name of a Windows share name mapped to the '
                    '"instances_path" dir and used by the resize feature '
                    'to copy files to the target host. If left blank, an '
                    'administrative share will be used, looking for the same '
                    '"instances_path" used locally'),
]

CONF = cfg.CONF
CONF.register_opts(hyperv_opts, 'hyperv')
CONF.import_opt('instances_path', 'nova.compute.manager')


class PathUtils(object):
    def __init__(self):
        self._smb_conn = wmi.WMI(moniker=r"root\Microsoft\Windows\SMB")

    def open(self, path, mode):
        """Wrapper on __builtin__.open used to simplify unit testing."""
        import __builtin__
        return __builtin__.open(path, mode)

    def exists(self, path):
        return os.path.exists(path)

    def makedirs(self, path):
        os.makedirs(path)

    def remove(self, path):
        os.remove(path)

    def rename(self, src, dest):
        os.rename(src, dest)

    def copyfile(self, src, dest):
        self.copy(src, dest)

    def copy(self, src, dest):
        # With large files this is 2x-3x faster than shutil.copy(src, dest),
        # especially when copying to a UNC target.
        # shutil.copyfileobj(...) with a proper buffer is better than
        # shutil.copy(...) but still 20% slower than a shell copy.
        # It can be replaced with Win32 API calls to avoid the process
        # spawning overhead.
        output, ret = utils.execute('cmd.exe', '/C', 'copy', '/Y', src, dest)
        if ret:
            raise IOError(_('The file copy from %(src)s to %(dest)s failed')
                           % {'src': src, 'dest': dest})

    def rmtree(self, path):
        shutil.rmtree(path)

    def get_instances_dir(self, remote_server=None):
        local_instance_path = os.path.normpath(CONF.instances_path)

        if remote_server:
            if CONF.hyperv.instances_path_share:
                path = CONF.hyperv.instances_path_share
            else:
                # Use an administrative share
                path = local_instance_path.replace(':', '$')
            return ('\\\\%(remote_server)s\\%(path)s' %
                {'remote_server': remote_server, 'path': path})
        else:
            return local_instance_path

    def _check_create_dir(self, path):
        if not self.exists(path):
            LOG.debug('Creating directory: %s', path)
            self.makedirs(path)

    def _check_remove_dir(self, path):
        if self.exists(path):
            LOG.debug('Removing directory: %s', path)
            self.rmtree(path)

    def _get_instances_sub_dir(self, dir_name, remote_server=None,
                               create_dir=True, remove_dir=False):
        instances_path = self.get_instances_dir(remote_server)
        path = os.path.join(instances_path, dir_name)
        if remove_dir:
            self._check_remove_dir(path)
        if create_dir:
            self._check_create_dir(path)
        return path

    def get_instance_migr_revert_dir(self, instance_name, create_dir=False,
                                     remove_dir=False):
        dir_name = '%s_revert' % instance_name
        return self._get_instances_sub_dir(dir_name, None, create_dir,
                                           remove_dir)

    def get_instance_dir(self, instance_name, remote_server=None,
                         create_dir=True, remove_dir=False):
        return self._get_instances_sub_dir(instance_name, remote_server,
                                           create_dir, remove_dir)

    def _lookup_vhd_path(self, instance_name, vhd_path_func):
        vhd_path = None
        for format_ext in ['vhd', 'vhdx']:
            test_path = vhd_path_func(instance_name, format_ext)
            if self.exists(test_path):
                vhd_path = test_path
                break
        return vhd_path

    def lookup_root_vhd_path(self, instance_name):
        return self._lookup_vhd_path(instance_name, self.get_root_vhd_path)

    def lookup_configdrive_path(self, instance_name):
        configdrive_path = None
        for format_ext in constants.DISK_FORMAT_MAP:
            test_path = self.get_configdrive_path(instance_name, format_ext)
            if self.exists(test_path):
                configdrive_path = test_path
                break
        return configdrive_path

    def lookup_ephemeral_vhd_path(self, instance_name):
        return self._lookup_vhd_path(instance_name,
                                     self.get_ephemeral_vhd_path)

    def get_root_vhd_path(self, instance_name, format_ext):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'root.' + format_ext.lower())

    def get_configdrive_path(self, instance_name, format_ext):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'configdrive.' + format_ext.lower())

    def get_ephemeral_vhd_path(self, instance_name, format_ext):
        instance_path = self.get_instance_dir(instance_name)
        return os.path.join(instance_path, 'ephemeral.' + format_ext.lower())

    def get_base_vhd_dir(self):
        return self._get_instances_sub_dir('_base')

    def get_export_dir(self, instance_name):
        dir_name = os.path.join('export', instance_name)
        return self._get_instances_sub_dir(dir_name, create_dir=True,
                                           remove_dir=True)

    def get_vm_console_log_paths(self, vm_name, remote_server=None):
        instance_dir = self.get_instance_dir(vm_name,
                                             remote_server)
        console_log_path = os.path.join(instance_dir, 'console.log')
        return console_log_path, console_log_path + '.1'

    def check_smb_mapping(self, smbfs_share):
        mappings = self._smb_conn.Msft_SmbMapping(RemotePath=smbfs_share)

        if not mappings:
            return False

        if os.path.exists(smbfs_share):
            LOG.debug('Share already mounted: %s', smbfs_share)
            return True
        else:
            LOG.debug('Share exists but is unavailable: %s ', smbfs_share)
            self.unmount_smb_share(smbfs_share, force=True)
            return False

    def mount_smb_share(self, smbfs_share, username=None, password=None):
        try:
            LOG.debug('Mounting share: %s', smbfs_share)
            self._smb_conn.Msft_SmbMapping.Create(RemotePath=smbfs_share,
                                                  UserName=username,
                                                  Password=password)
        except wmi.x_wmi as exc:
            err_msg = (_(
                'Unable to mount SMBFS share: %(smbfs_share)s '
                'WMI exception: %(wmi_exc)s'), {'smbfs_share': smbfs_share,
                                                'wmi_exc': exc})
            raise vmutils.HyperVException(err_msg)

    def unmount_smb_share(self, smbfs_share, force=False):
        mappings = self._smb_conn.Msft_SmbMapping(RemotePath=smbfs_share)
        if not mappings:
            LOG.debug('Share %s is not mounted. Skipping unmount.',
                      smbfs_share)

        for mapping in mappings:
            # Due to a bug in the WMI module, getting the output of
            # methods returning None will raise an AttributeError
            try:
                mapping.Remove(Force=force)
            except AttributeError:
                pass
            except wmi.x_wmi:
                # If this fails, a 'Generic Failure' exception is raised.
                # This happens even if we unforcefully unmount an in-use
                # share, for which reason we'll simply ignore it in this
                # case.
                if force:
                    raise vmutils.HyperVException(
                        _("Could not unmount share: %s"), smbfs_share)

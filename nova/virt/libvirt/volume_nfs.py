# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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

"""Volume driver for using NFS as volumes storage. Nova compute part."""

import ctypes
import os

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.libvirt import volume

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('nfs_mount_point_base',
               default='$state_path/mnt',
               help='Base dir where nfs expected to be mounted on compute'),
]
FLAGS = flags.FLAGS
FLAGS.register_opts(volume_opts)


class NfsVolumeDriver(volume.LibvirtVolumeDriver):
    """ Class implements libvirt part of volume driver for NFS
    """
    def __init__(self, *args, **kwargs):
        """Create back-end to nfs and check connection"""
        super(NfsVolumeDriver, self).__init__(*args, **kwargs)

    def connect_volume(self, connection_info, mount_device):
        """Connect the volume. Returns xml for libvirt."""
        path = self._ensure_mounted(connection_info['data']['export'])
        path = os.path.join(path, connection_info['data']['name'])
        connection_info['data']['device_path'] = path
        conf = super(NfsVolumeDriver, self).connect_volume(connection_info,
                                                           mount_device)
        conf.source_type = 'file'
        return conf

    def disconnect_volume(self, connection_info, mount_device):
        """Disconnect the volume"""
        pass

    def _ensure_mounted(self, nfs_export):
        """
        @type nfs_export: string
        """
        mount_path = os.path.join(FLAGS.nfs_mount_point_base,
                                  self.get_hash_str(nfs_export))
        self._mount_nfs(mount_path, nfs_export, ensure=True)
        return mount_path

    def _mount_nfs(self, mount_path, nfs_share, ensure=False):
        """Mount nfs export to mount path"""
        if not self._path_exists(mount_path):
            utils.execute('mkdir', '-p', mount_path)

        try:
            utils.execute('mount', '-t', 'nfs', nfs_share, mount_path,
                          run_as_root=True)
        except exception.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.message:
                LOG.warn(_("%s is already mounted"), nfs_share)
            else:
                raise

    @staticmethod
    def get_hash_str(base_str):
        """returns string that represents hash of base_str (in a hex format)"""
        return str(ctypes.c_uint64(hash(base_str)).value)

    @staticmethod
    def _path_exists(path):
        """Check path """
        try:
            return utils.execute('stat', path, run_as_root=True)
        except exception.ProcessExecutionError:
            return False

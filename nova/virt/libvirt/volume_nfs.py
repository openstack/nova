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

import hashlib
import os

from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import paths
from nova import utils
from nova.virt.libvirt import volume

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Base dir where nfs expected to be mounted on compute'),
    cfg.StrOpt('nfs_mount_options',
               default=None,
               help='Mount options passed to the nfs client. See section '
                    'of the nfs man page for details'),
]
CONF = cfg.CONF
CONF.register_opts(volume_opts)


class NfsVolumeDriver(volume.LibvirtBaseVolumeDriver):
    """Class implements libvirt part of volume driver for NFS."""

    def __init__(self, connection):
        """Create back-end to nfs."""
        super(NfsVolumeDriver,
              self).__init__(connection, is_block_dev=False)

    def connect_volume(self, connection_info, mount_device):
        """Connect the volume. Returns xml for libvirt."""
        conf = super(NfsVolumeDriver,
                     self).connect_volume(connection_info, mount_device)
        path = self._ensure_mounted(connection_info['data']['export'])
        path = os.path.join(path, connection_info['data']['name'])
        conf.source_type = 'file'
        conf.source_path = path
        return conf

    def _ensure_mounted(self, nfs_export):
        """
        @type nfs_export: string
        """
        mount_path = os.path.join(CONF.nfs_mount_point_base,
                                  self.get_hash_str(nfs_export))
        self._mount_nfs(mount_path, nfs_export, ensure=True)
        return mount_path

    def _mount_nfs(self, mount_path, nfs_share, ensure=False):
        """Mount nfs export to mount path."""
        if not self._path_exists(mount_path):
            utils.execute('mkdir', '-p', mount_path)

        # Construct the NFS mount command.
        nfs_cmd = ['mount', '-t', 'nfs']
        if CONF.nfs_mount_options is not None:
            nfs_cmd.extend(['-o', CONF.nfs_mount_options])
        nfs_cmd.extend([nfs_share, mount_path])

        try:
            utils.execute(*nfs_cmd, run_as_root=True)
        except exception.ProcessExecutionError as exc:
            if ensure and 'already mounted' in exc.message:
                LOG.warn(_("%s is already mounted"), nfs_share)
            else:
                raise

    @staticmethod
    def get_hash_str(base_str):
        """returns string that represents hash of base_str (in hex format)."""
        return hashlib.md5(base_str).hexdigest()

    @staticmethod
    def _path_exists(path):
        """Check path."""
        try:
            return utils.execute('stat', path, run_as_root=True)
        except exception.ProcessExecutionError:
            return False

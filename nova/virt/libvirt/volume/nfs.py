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

import six

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging

from nova.i18n import _LE, _LW
from nova import paths
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import fs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the NFS volume is mounted on the'
               ' compute node'),
    cfg.StrOpt('nfs_mount_options',
               help='Mount options passed to the NFS client. See section '
                    'of the nfs man page for details'),
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class LibvirtNFSVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for NFS."""

    def _get_mount_point_base(self):
        return CONF.libvirt.nfs_mount_point_base

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtNFSVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume."""
        self._ensure_mounted(connection_info)

        connection_info['data']['device_path'] = \
            self._get_device_path(connection_info)

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""

        mount_path = self._get_mount_path(connection_info)

        try:
            utils.execute('umount', mount_path, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            export = connection_info['data']['export']
            if ('device is busy' in six.text_type(exc) or
                'target is busy' in six.text_type(exc)):
                LOG.debug("The NFS share %s is still in use.", export)
            elif ('not mounted' in six.text_type(exc)):
                LOG.debug("The NFS share %s has already been unmounted.",
                          export)
            else:
                LOG.exception(_LE("Couldn't unmount the NFS share %s"), export)

    def _ensure_mounted(self, connection_info):
        """@type connection_info: dict
        """
        nfs_export = connection_info['data']['export']
        mount_path = self._get_mount_path(connection_info)
        if not libvirt_utils.is_mounted(mount_path, nfs_export):
            options = connection_info['data'].get('options')
            self._mount_nfs(mount_path, nfs_export, options, ensure=True)
        return mount_path

    def _mount_nfs(self, mount_path, nfs_share, options=None, ensure=False):
        """Mount nfs export to mount path."""
        utils.execute('mkdir', '-p', mount_path)

        # Construct the NFS mount command.
        nfs_cmd = ['mount', '-t', 'nfs']
        if CONF.libvirt.nfs_mount_options is not None:
            nfs_cmd.extend(['-o', CONF.libvirt.nfs_mount_options])
        if options:
            nfs_cmd.extend(options.split(' '))
        nfs_cmd.extend([nfs_share, mount_path])

        try:
            utils.execute(*nfs_cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in six.text_type(exc):
                LOG.warn(_LW("%s is already mounted"), nfs_share)
            else:
                raise

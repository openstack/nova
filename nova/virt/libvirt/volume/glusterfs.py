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


from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
import six

from nova.i18n import _LE, _LW
from nova import paths
from nova import utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import fs

CONF = cfg.CONF
CONF.import_opt('qemu_allowed_storage_drivers',
                'nova.virt.libvirt.volume.volume',
                group='libvirt')

volume_opts = [
    cfg.StrOpt('glusterfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the glusterfs volume is mounted on the '
                    'compute node'),
    ]

CONF.register_opts(volume_opts, 'libvirt')

LOG = logging.getLogger(__name__)


class LibvirtGlusterfsVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for GlusterFS."""

    def _get_mount_point_base(self):
        return CONF.libvirt.glusterfs_mount_point_base

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtGlusterfsVolumeDriver,
                     self).get_config(connection_info, disk_info)

        data = connection_info['data']

        if 'gluster' in CONF.libvirt.qemu_allowed_storage_drivers:
            vol_name = data['export'].split('/')[1]
            source_host = data['export'].split('/')[0][:-1]

            conf.source_ports = ['24007']
            conf.source_type = 'network'
            conf.source_protocol = 'gluster'
            conf.source_hosts = [source_host]
            conf.source_name = '%s/%s' % (vol_name, data['name'])
        else:
            conf.source_type = 'file'
            conf.source_path = connection_info['data']['device_path']

        conf.driver_format = connection_info['data'].get('format', 'raw')

        return conf

    def connect_volume(self, connection_info, mount_device):
        if 'gluster' not in CONF.libvirt.qemu_allowed_storage_drivers:
            self._ensure_mounted(connection_info)
            connection_info['data']['device_path'] = \
                self._get_device_path(connection_info)

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""

        if 'gluster' in CONF.libvirt.qemu_allowed_storage_drivers:
            return

        mount_path = self._get_mount_path(connection_info)

        try:
            utils.execute('umount', mount_path, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            export = connection_info['data']['export']
            if 'target is busy' in six.text_type(exc):
                LOG.debug("The GlusterFS share %s is still in use.", export)
            else:
                LOG.exception(_LE("Couldn't unmount the GlusterFS share %s"),
                              export)

    def _ensure_mounted(self, connection_info):
        """@type connection_info: dict
        """
        glusterfs_export = connection_info['data']['export']
        mount_path = self._get_mount_path(connection_info)
        if not libvirt_utils.is_mounted(mount_path, glusterfs_export):
            options = connection_info['data'].get('options')
            self._mount_glusterfs(mount_path, glusterfs_export,
                                  options, ensure=True)
        return mount_path

    def _mount_glusterfs(self, mount_path, glusterfs_share,
                         options=None, ensure=False):
        """Mount glusterfs export to mount path."""
        utils.execute('mkdir', '-p', mount_path)

        gluster_cmd = ['mount', '-t', 'glusterfs']
        if options is not None:
            gluster_cmd.extend(options.split(' '))
        gluster_cmd.extend([glusterfs_share, mount_path])

        try:
            utils.execute(*gluster_cmd, run_as_root=True)
        except processutils.ProcessExecutionError as exc:
            if ensure and 'already mounted' in six.text_type(exc):
                LOG.warn(_LW("%s is already mounted"), glusterfs_share)
            else:
                raise

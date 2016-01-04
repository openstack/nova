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

from oslo_config import cfg
from oslo_log import log as logging
from six.moves import urllib
import six.moves.urllib.parse as urlparse

from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt.libvirt.volume import fs

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('scality_sofs_config',
               help='Path or URL to Scality SOFS configuration file'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted'),
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class LibvirtScalityVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):
    """Scality SOFS Nova driver. Provide hypervisors with access
    to sparse files on SOFS.
    """

    def _get_mount_point_base(self):
        return CONF.libvirt.scality_sofs_mount_point

    def _get_device_path(self, connection_info):
        """Returns the hashed path to the device.

        :param connection_info: dict of the form

        ::

          connection_info = {
              'data': {
                  'sofs_path': the file system share
                  ...
              }
              ...
          }

        :returns: The full path to the device.
        """
        # TODO(mriedem): change the scality volume driver in cinder to set
        # the export and name keys rather than the sofs_path so this is
        # standardized.
        path = os.path.join(CONF.libvirt.scality_sofs_mount_point,
                            connection_info['data']['sofs_path'])
        return path

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtScalityVolumeDriver,
                     self).get_config(connection_info, disk_info)
        conf.source_type = 'file'
        conf.source_path = connection_info['data']['device_path']

        # The default driver cache policy is 'none', and this causes
        # qemu/kvm to open the volume file with O_DIRECT, which is
        # rejected by FUSE (on kernels older than 3.3). Scality SOFS
        # is FUSE based, so we must provide a more sensible default.
        conf.driver_cache = 'writethrough'

        return conf

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume."""
        self._check_prerequisites()
        self._mount_sofs()

        connection_info['data']['device_path'] = \
            self._get_device_path(connection_info)

    def _check_prerequisites(self):
        """Sanity checks before attempting to mount SOFS."""

        # config is mandatory
        config = CONF.libvirt.scality_sofs_config
        if not config:
            msg = _("Value required for 'scality_sofs_config'")
            LOG.warn(msg)
            raise exception.NovaException(msg)

        # config can be a file path or a URL, check it
        if urlparse.urlparse(config).scheme == '':
            # turn local path into URL
            config = 'file://%s' % config
        try:
            urllib.request.urlopen(config, timeout=5).close()
        except urllib.error.URLError as e:
            msg = _("Cannot access 'scality_sofs_config': %s") % e
            LOG.warn(msg)
            raise exception.NovaException(msg)

        # mount.sofs must be installed
        if not os.access('/sbin/mount.sofs', os.X_OK):
            msg = _("Cannot execute /sbin/mount.sofs")
            LOG.warn(msg)
            raise exception.NovaException(msg)

    def _sofs_is_mounted(self):
        """Detects whether Scality SOFS is already mounted."""
        mount_path = CONF.libvirt.scality_sofs_mount_point.rstrip('/')
        with io.open('/proc/mounts') as mounts:
            for mount in mounts.readlines():
                parts = mount.split()
                if (parts[0].endswith('fuse') and
                        parts[1].rstrip('/') == mount_path):
                            return True
        return False

    def _mount_sofs(self):
        config = CONF.libvirt.scality_sofs_config
        mount_path = CONF.libvirt.scality_sofs_mount_point

        if not os.path.isdir(mount_path):
            utils.execute('mkdir', '-p', mount_path)
        if not self._sofs_is_mounted():
            utils.execute('mount', '-t', 'sofs', config, mount_path,
                          run_as_root=True)
            if not self._sofs_is_mounted():
                msg = _("Cannot mount Scality SOFS, check syslog for errors")
                LOG.warn(msg)
                raise exception.NovaException(msg)

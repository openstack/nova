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

import collections
import re

from os_brick import initiator
from os_brick.initiator import connector
from oslo_config import cfg
from oslo_log import log as logging

from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt.libvirt.volume import fs

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

VzShare = collections.namedtuple('VzShare',
                                 ['cluster_name', 'mds_list', 'password'])


class LibvirtVZStorageVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for VzStorage."""

    SHARE_FORMAT_REGEX = r'(?:(\S+):/)?([a-zA-Z0-9_-]+)(?::(\S+))?$'
    SHARE_LOCK_NAME = "vz_share-%s"

    def __init__(self, connection):
        super(LibvirtVZStorageVolumeDriver, self).__init__(connection)

        # Check for duplicate options:
        # -c - cluster name
        # -l - log file, includes %(cluster_name)s, so it's handled as a
        #      separate config parameter
        # -C - SSD cache file, the same thing with %(cluster_name)s
        # -u, -g, -m - there are default values for these options, so
        #              they're separate config parameters
        cfg_opts_set = set(CONF.libvirt.vzstorage_mount_opts)
        invalid_opts_set = set(('-c', '-l', '-C', '-u', '-g', '-m',))
        invalid_cfg_opts = cfg_opts_set.intersection(invalid_opts_set)

        if invalid_cfg_opts:
            msg = (_("You can't use %s options in vzstorage_mount_opts "
                     "configuration parameter.") %
                     ', '.join(invalid_cfg_opts))
            raise exception.InternalError(msg)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            initiator.VZSTORAGE, utils.get_root_helper(),
            vzstorage_mount_point_base=CONF.libvirt.vzstorage_mount_point_base)

    def _get_mount_point_base(self):
        return CONF.libvirt.vzstorage_mount_point_base

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtVZStorageVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.driver_cache = 'writeback'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def _parse_vz_share(self, vz_share):
        m = re.match(self.SHARE_FORMAT_REGEX, vz_share)
        if not m:
            msg = _("Valid share format is "
                    "[mds[,mds1[...]]:/]clustername[:password]")
            raise exception.InvalidVolume(msg)

        if m.group(1):
            mds_list = m.group(1).split(',')
        else:
            mds_list = None

        return VzShare(cluster_name=m.group(2),
                       mds_list=mds_list,
                       password=m.group(3))

    def _get_mount_opts(self, vz_share):
        cluster_name = self._parse_vz_share(vz_share).cluster_name

        # pstorage-mount man page:
        # https://static.openvz.org/vz-man/man1/pstorage-mount.1.gz.html
        mount_opts = ['-u', CONF.libvirt.vzstorage_mount_user,
                      '-g', CONF.libvirt.vzstorage_mount_group,
                      '-m', CONF.libvirt.vzstorage_mount_perms,
                      '-l', (CONF.libvirt.vzstorage_log_path %
                             {'cluster_name': cluster_name})]

        if CONF.libvirt.vzstorage_cache_path:
            mount_opts.extend(['-C', (CONF.libvirt.vzstorage_cache_path %
                                      {'cluster_name': cluster_name})])
        mount_opts.extend(CONF.libvirt.vzstorage_mount_opts)

        return ' '.join(mount_opts)

    def connect_volume(self, connection_info, instance):
        """Attach the volume to instance_name."""
        vz_share = connection_info['data']['export']
        share_lock = self.SHARE_LOCK_NAME % vz_share

        @utils.synchronized(share_lock)
        def _connect_volume(connection_info, instance):
            LOG.debug("Calling os-brick to mount vzstorage")
            connection_info['data']['options'] = self._get_mount_opts(vz_share)
            device_info = self.connector.connect_volume(
                connection_info['data'])
            LOG.debug("Attached vzstorage volume %s", device_info)
            connection_info['data']['device_path'] = device_info['path']

        return _connect_volume(connection_info, instance)

    def disconnect_volume(self, connection_info, instance):
        """Detach the volume from instance_name."""
        LOG.debug("calling os-brick to detach Vzstorage Volume",
                instance=instance)
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected Vzstorage Volume", instance=instance)

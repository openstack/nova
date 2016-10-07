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


from oslo_log import log as logging

import nova.conf
from nova.virt.libvirt.volume import fs

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class LibvirtNFSVolumeDriver(fs.LibvirtMountedFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for NFS."""

    def __init__(self, connection):
        super(LibvirtNFSVolumeDriver, self).__init__(connection, 'nfs')

    def _get_mount_point_base(self):
        return CONF.libvirt.nfs_mount_point_base

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtNFSVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        conf.driver_io = "native"
        return conf

    def _mount_options(self, connection_info):
        options = []
        if CONF.libvirt.nfs_mount_options is not None:
            options.extend(['-o', CONF.libvirt.nfs_mount_options])

        conn_options = connection_info['data'].get('options')
        if conn_options:
            options.extend(conn_options.split(' '))

        return options

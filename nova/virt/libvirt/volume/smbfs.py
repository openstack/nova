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

import re

import nova.conf
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt.volume import fs
from nova.virt.libvirt.volume import remotefs

CONF = nova.conf.CONF

USERNAME_REGEX = re.compile(r"(user(?:name)?)=(?:[^ ,]+\\)?([^ ,]+)")


class LibvirtSMBFSVolumeDriver(fs.LibvirtBaseFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for SMBFS."""

    def _get_mount_point_base(self):
        return CONF.libvirt.smbfs_mount_point_base

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtSMBFSVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = 'file'
        conf.driver_cache = 'writeback'
        conf.source_path = connection_info['data']['device_path']
        conf.driver_format = connection_info['data'].get('format', 'raw')
        return conf

    def connect_volume(self, connection_info, instance):
        """Connect the volume."""
        smbfs_share = connection_info['data']['export']
        mount_path = self._get_mount_path(connection_info)

        if not libvirt_utils.is_mounted(mount_path, smbfs_share):
            mount_options = self._parse_mount_options(connection_info)
            remotefs.mount_share(mount_path, smbfs_share,
                                 export_type='cifs', options=mount_options)

        device_path = self._get_device_path(connection_info)
        connection_info['data']['device_path'] = device_path

    def disconnect_volume(self, connection_info, instance):
        """Disconnect the volume."""
        smbfs_share = connection_info['data']['export']
        mount_path = self._get_mount_path(connection_info)
        remotefs.unmount_share(mount_path, smbfs_share)

    def _parse_mount_options(self, connection_info):
        mount_options = " ".join(
            [connection_info['data'].get('options') or '',
             CONF.libvirt.smbfs_mount_options])

        if not USERNAME_REGEX.findall(mount_options):
            mount_options = mount_options + ' -o username=guest'
        else:
            # Remove the Domain Name from user name
            mount_options = USERNAME_REGEX.sub(r'\1=\2', mount_options)
        return mount_options.strip(", ").split(' ')

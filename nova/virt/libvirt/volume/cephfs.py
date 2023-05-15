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

# The driver is not designed to function as a volume for libvirt. Rather,
# its purpose is to facilitate the mounting of cephfs shares exposed by manila
# on compute, enabling the shares to be accessed and shared using virtiofs.
# This is the reason why get_config and extend_volume are not implemented.

import nova.conf
from nova.virt.libvirt.volume import fs

CONF = nova.conf.CONF


class LibvirtCEPHFSVolumeDriver(fs.LibvirtMountedFileSystemVolumeDriver):
    """Class implements libvirt part of volume driver for CEPHFS."""

    def __init__(self, connection):
        super(LibvirtCEPHFSVolumeDriver, self).__init__(connection, 'ceph')

    def _get_mount_point_base(self):
        return CONF.libvirt.ceph_mount_point_base

    def get_config(self, connection_info, disk_info):
        raise NotImplementedError()

    def _mount_options(self, connection_info):
        options = []
        conn_options = connection_info['data'].get('options')
        if CONF.libvirt.ceph_mount_options is not None:
            options.extend(CONF.libvirt.ceph_mount_options)
            if conn_options:
                options.extend(conn_options)
            options = [','.join(options)]
            options.insert(0, '-o')
        else:
            if conn_options:
                options.extend(['-o', ','.join(conn_options)])

        return options

    def extend_volume(self, connection_info, instance, requested_size):
        raise NotImplementedError()

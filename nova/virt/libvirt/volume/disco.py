#    Copyright (c) 2015 Industrial Technology Research Institute.
#    All Rights Reserved.
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

"""Libvirt volume driver for DISCO."""

from os_brick import initiator
from os_brick.initiator import connector

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

CONF = nova.conf.CONF


class LibvirtDISCOVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Class DISCO Libvirt volume Driver.

    Implements Libvirt part of volume driver for DISCO cinder driver.
    Uses the DISCO connector from the os-brick projects.
    """

    def __init__(self, host):
        """Init DISCO connector for LibVirt."""
        super(LibvirtDISCOVolumeDriver, self).__init__(host,
                                                       is_block_dev=False)
        self.connector = connector.InitiatorConnector.factory(
            initiator.DISCO, utils.get_root_helper(),
            device_scan_attempts=CONF.libvirt.num_volume_scan_tries)

    def get_config(self, connection_info, disk_info):
        """Get DISCO volume attachment configuration."""
        conf = super(LibvirtDISCOVolumeDriver, self).get_config(
            connection_info, disk_info)

        conf.source_path = connection_info['data']['device_path']
        conf.source_protocol = 'disco'
        conf.source_type = 'file'
        return conf

    def connect_volume(self, connection_info, instance):
        """Connect a DISCO volume to a compute node."""
        device_info = self.connector.connect_volume(connection_info['data'])
        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, instance):
        """Disconnect a DISCO volume of a compute node."""
        self.connector.disconnect_volume(connection_info['data'], None)
        super(LibvirtDISCOVolumeDriver, self).disconnect_volume(
            connection_info, instance)

# Copyright 2015 HGST
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

from os_brick.initiator import connector

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume


CONF = nova.conf.CONF


class LibvirtHGSTVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Driver to attach HGST volumes to libvirt."""
    def __init__(self, host):
        super(LibvirtHGSTVolumeDriver,
              self).__init__(host, is_block_dev=True)
        self.connector = connector.InitiatorConnector.factory(
            'HGST', utils.get_root_helper(),
            device_scan_attempts=CONF.libvirt.num_volume_scan_tries)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtHGSTVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        return conf

    def connect_volume(self, connection_info, disk_info, instance):
        device_info = self.connector.connect_volume(connection_info['data'])
        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, disk_dev, instance):
        self.connector.disconnect_volume(connection_info['data'], None)
        super(LibvirtHGSTVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev, instance)

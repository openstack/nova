# Copyright (c) 2015 EMC Corporation
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

"""Libvirt volume driver for ScaleIO."""

from os_brick import initiator
from os_brick.initiator import connector
from oslo_log import log as logging

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class LibvirtScaleIOVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Class ScaleIO Libvirt volume Driver

    Implements Libvirt part of volume driver for ScaleIO cinder driver.
    Uses the ScaleIO connector from the os-brick projects
    """
    def __init__(self, host):
        super(LibvirtScaleIOVolumeDriver, self).__init__(host,
                                                         is_block_dev=False)
        self.connector = connector.InitiatorConnector.factory(
            initiator.SCALEIO, utils.get_root_helper(),
            device_scan_attempts=CONF.libvirt.num_volume_scan_tries)

    def get_config(self, connection_info, disk_info):
        conf = super(LibvirtScaleIOVolumeDriver, self).get_config(
            connection_info, disk_info)

        conf.source_type = 'block'
        conf.source_path = connection_info['data']['device_path']
        return conf

    def connect_volume(self, connection_info, instance):
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached ScaleIO volume %s.", device_info)
        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, instance):
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected volume", instance=instance)

        super(LibvirtScaleIOVolumeDriver, self).disconnect_volume(
            connection_info, instance)

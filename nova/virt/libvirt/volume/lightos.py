# Copyright (C) 2016-2020 Lightbits Labs Ltd.
# Copyright (C) 2020 Intel Corporation
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

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume
from os_brick import initiator
from os_brick.initiator import connector
from oslo_log import log as logging


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF


class LibvirtLightOSVolumeDriver(libvirt_volume.LibvirtVolumeDriver):
    """Driver to attach NVMe volumes to libvirt."""
    VERSION = '2.3.12'

    def __init__(self, connection):
        super(LibvirtLightOSVolumeDriver, self).__init__(connection)
        self.connector = connector.InitiatorConnector.factory(
            initiator.LIGHTOS,
            root_helper=utils.get_root_helper(),
            device_scan_attempts=CONF.libvirt.num_nvme_discover_tries)

    def connect_volume(self, connection_info, instance):
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Connecting NVMe volume with device_info %s", device_info)
        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, instance, force=False):
        """Detach the volume from the instance."""
        LOG.debug("Disconnecting NVMe disk. instance:%s, volume_id:%s",
                  connection_info.get("instance", ""),
                  connection_info.get("volume_id", ""))
        self.connector.disconnect_volume(
            connection_info['data'], None, force=force)
        super(LibvirtLightOSVolumeDriver, self).disconnect_volume(
            connection_info, instance, force=force)

    def extend_volume(self, connection_info, instance, requested_size):
        """Extend the volume."""
        LOG.debug("calling os-brick to extend LightOS Volume."
                  "instance:%s, volume_id:%s",
                  connection_info.get("instance", ""),
                  connection_info.get("volume_id", ""))
        new_size = self.connector.extend_volume(connection_info['data'])
        LOG.debug("Extend LightOS Volume %s; new_size=%s",
                  connection_info['data']['device_path'], new_size)
        return new_size

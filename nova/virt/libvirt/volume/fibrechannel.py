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

from os_brick import initiator
from os_brick.initiator import connector
from oslo_log import log as logging

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class LibvirtFibreChannelVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Driver to attach Fibre Channel Network volumes to libvirt."""

    def __init__(self, host):
        super(LibvirtFibreChannelVolumeDriver,
              self).__init__(host, is_block_dev=False)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            initiator.FIBRE_CHANNEL, utils.get_root_helper(),
            use_multipath=CONF.libvirt.volume_use_multipath,
            device_scan_attempts=CONF.libvirt.num_volume_scan_tries)

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtFibreChannelVolumeDriver,
                     self).get_config(connection_info, disk_info)

        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        conf.driver_io = "native"
        return conf

    def connect_volume(self, connection_info, instance):
        """Attach the volume to instance_name."""

        LOG.debug("Calling os-brick to attach FC Volume")
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached FC volume %s", device_info)

        connection_info['data']['device_path'] = device_info['path']
        if 'multipath_id' in device_info:
            connection_info['data']['multipath_id'] = \
                device_info['multipath_id']

    def disconnect_volume(self, connection_info, instance):
        """Detach the volume from instance_name."""

        LOG.debug("calling os-brick to detach FC Volume", instance=instance)
        # TODO(walter-boring) eliminated the need for preserving
        # multipath_id.  Use scsi_id instead of multipath -ll
        # This will then eliminate the need to pass anything in
        # the 2nd param of disconnect_volume and be consistent
        # with the rest of the connectors.
        self.connector.disconnect_volume(connection_info['data'],
                                         connection_info['data'])
        LOG.debug("Disconnected FC Volume", instance=instance)

        super(LibvirtFibreChannelVolumeDriver,
              self).disconnect_volume(connection_info, instance)

    def extend_volume(self, connection_info, instance, requested_size):
        """Extend the volume."""
        LOG.debug("calling os-brick to extend FC Volume", instance=instance)
        new_size = self.connector.extend_volume(connection_info['data'])
        LOG.debug("Extend FC Volume %s; new_size=%s",
                  connection_info['data']['device_path'],
                  new_size, instance=instance)
        return new_size

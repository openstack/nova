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
"""Libvirt volume driver for iSCSI"""

from os_brick import exception as os_brick_exception
from os_brick.initiator import connector
from oslo_log import log as logging

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class LibvirtISCSIVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def __init__(self, host):
        super(LibvirtISCSIVolumeDriver, self).__init__(host,
                                                       is_block_dev=True)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            'ISCSI', utils.get_root_helper(),
            use_multipath=CONF.libvirt.volume_use_multipath,
            device_scan_attempts=CONF.libvirt.num_volume_scan_tries,
            transport=self._get_transport())

    def _get_transport(self):
        if CONF.libvirt.iscsi_iface:
            transport = CONF.libvirt.iscsi_iface
        else:
            transport = 'default'

        return transport

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtISCSIVolumeDriver,
                     self).get_config(connection_info, disk_info)
        conf.source_type = "block"
        conf.source_path = connection_info['data']['device_path']
        conf.driver_io = "native"
        return conf

    def connect_volume(self, connection_info, disk_info, instance):
        """Attach the volume to instance_name."""

        LOG.debug("Calling os-brick to attach iSCSI Volume")
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached iSCSI volume %s", device_info)

        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, disk_dev, instance):
        """Detach the volume from instance_name."""

        LOG.debug("calling os-brick to detach iSCSI Volume")
        try:
            self.connector.disconnect_volume(connection_info['data'], None)
        except os_brick_exception.VolumeDeviceNotFound as exc:
            LOG.warning('Ignoring VolumeDeviceNotFound: %s', exc)
            return
        LOG.debug("Disconnected iSCSI Volume %s", disk_dev)

        super(LibvirtISCSIVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev, instance)

    def extend_volume(self, connection_info, instance):
        """Extend the volume."""
        LOG.debug("calling os-brick to extend iSCSI Volume", instance=instance)
        new_size = self.connector.extend_volume(connection_info['data'])
        LOG.debug("Extend iSCSI Volume %s; new_size=%s",
                  connection_info['data']['device_path'],
                  new_size, instance=instance)
        return new_size

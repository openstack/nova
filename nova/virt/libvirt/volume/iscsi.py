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

from os_brick.initiator import connector
from oslo_config import cfg
from oslo_log import log as logging

from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI or FC volume'),
    cfg.StrOpt('iscsi_iface',
               deprecated_name='iscsi_transport',
               help='The iSCSI transport iface to use to connect to target in '
                    'case offload support is desired. Default format is of '
                    'the form <transport_name>.<hwaddress> where '
                    '<transport_name> is one of (be2iscsi, bnx2i, cxgb3i, '
                    'cxgb4i, qla4xxx, ocs) and <hwaddress> is the MAC address '
                    'of the interface and can be generated via the '
                    'iscsiadm -m iface command. Do not confuse the '
                    'iscsi_iface parameter to be provided here with the '
                    'actual transport name.'),
                    # iser is also supported, but use LibvirtISERVolumeDriver
                    # instead
    ]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class LibvirtISCSIVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""

    def __init__(self, connection):
        super(LibvirtISCSIVolumeDriver, self).__init__(connection,
                                                       is_block_dev=True)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            'ISCSI', utils.get_root_helper(),
            use_multipath=CONF.libvirt.iscsi_use_multipath,
            device_scan_attempts=CONF.libvirt.num_iscsi_scan_tries,
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
        return conf

    def connect_volume(self, connection_info, disk_info):
        """Attach the volume to instance_name."""

        LOG.debug("Calling os-brick to attach iSCSI Volume")
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached iSCSI volume %s", device_info)

        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""

        LOG.debug("calling os-brick to detach iSCSI Volume")
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected iSCSI Volume %s", disk_dev)

        super(LibvirtISCSIVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)

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

from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume


LOG = logging.getLogger(__name__)


class LibvirtDRBDVolumeDriver(libvirt_volume.LibvirtVolumeDriver):
    """Driver to attach DRBD volumes to libvirt."""

    def __init__(self, host):
        super(LibvirtDRBDVolumeDriver, self).__init__(host)
        self.connector = connector.InitiatorConnector.factory(
            initiator.DRBD, utils.get_root_helper())

    def connect_volume(self, connection_info, instance):
        """Connect the volume.

        Sets the connection_info['data']['device_path'] value upon successful
        connection.

        :param connection_info: dict of connection information for the backend
            storage when a connection was initiated with Cinder. Expects
            connection_info['data']['device'] to be set.
        :param instance: The nova.objects.Instance that is having a volume
            connected to it.
        """
        LOG.debug("Calling os-brick to attach DRBD Volume.", instance=instance)
        device_info = self.connector.connect_volume(connection_info['data'])
        LOG.debug("Attached DRBD volume %s", device_info, instance=instance)
        connection_info['data']['device_path'] = device_info['path']

    def disconnect_volume(self, connection_info, instance):
        """Disconnect the volume.

        :param connection_info: dict of connection information for the backend
            storage when a connection was initiated with Cinder.
        :param instance: The nova.objects.Instance that is having a volume
            disconnected from it.
        """
        LOG.debug("Calling os-brick to detach DRBD Volume.", instance=instance)
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected DRBD Volume", instance=instance)

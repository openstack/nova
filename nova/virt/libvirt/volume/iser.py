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

import nova.conf
from nova import utils
from nova.virt.libvirt.volume import iscsi


CONF = nova.conf.CONF


class LibvirtISERVolumeDriver(iscsi.LibvirtISCSIVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, connection):
        super(LibvirtISERVolumeDriver, self).__init__(connection)

        # Call the factory here so we can support
        # more than x86 architectures.
        self.connector = connector.InitiatorConnector.factory(
            initiator.ISER, utils.get_root_helper(),
            use_multipath=CONF.libvirt.iser_use_multipath,
            device_scan_attempts=CONF.libvirt.num_iser_scan_tries,
            transport=self._get_transport())

    def _get_transport(self):
        return 'iser'

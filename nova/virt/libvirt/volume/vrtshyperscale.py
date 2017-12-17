# Copyright (c) 2017 Veritas Technologies LLC.
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

"""Libvirt volume driver for HyperScale."""

from os_brick import initiator
from os_brick.initiator import connector
from oslo_log import log as logging

from nova import utils
from nova.virt.libvirt.volume import volume as libvirt_volume

LOG = logging.getLogger(__name__)


class LibvirtHyperScaleVolumeDriver(libvirt_volume.LibvirtVolumeDriver):
    """Class HyperScale libvirt volume driver

    This class implements a Libvirt volume driver for Veritas
    HyperScale storage. The class uses its parent class get_config method,
    and calls the Veritas HyperScale os-brick connector to handle the work
    of the connect_volume and disconnect volume methods.
    """

    def __init__(self, connection):
        super(LibvirtHyperScaleVolumeDriver, self).__init__(connection)
        self.connector = connector.InitiatorConnector.factory(
            initiator.VERITAS_HYPERSCALE, utils.get_root_helper())

    def connect_volume(self, connection_info, instance):
        # The os-brick connector may raise BrickException.
        # The convention in nova is to just propagate it up.
        # Note that the device path is returned from the os-brick connector
        # using the "path" key, LibvirtVolumeDriver.get_config gets the
        # device path from the "device_path" key in connection_info.

        device_info = self.connector.connect_volume(connection_info['data'])
        connection_info['data']['device_path'] = device_info.get('path')
        LOG.info("connect_volume: device path %(device_path)s",
            {'device_path': connection_info['data']['device_path']})

    def disconnect_volume(self, connection_info, instance):
        self.connector.disconnect_volume(connection_info['data'], None)
        LOG.debug("Disconnected volume %(vol_id)s",
                  {'vol_id': connection_info['data']['name']},
                  instance=instance)

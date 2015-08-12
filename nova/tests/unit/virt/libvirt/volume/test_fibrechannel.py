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

import platform

import mock
from os_brick.initiator import connector

from nova.compute import arch
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import fibrechannel


class LibvirtFibreChannelVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_fibrechan_driver(self):
        libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                                                                self.fake_conn)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.FibreChannelConnector)

    def _test_libvirt_fibrechan_driver_s390(self):
        libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                                                                self.fake_conn)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.FibreChannelConnectorS390X)

    @mock.patch.object(platform, 'machine', return_value=arch.S390)
    def test_libvirt_fibrechan_driver_s390(self, mock_machine):
        self._test_libvirt_fibrechan_driver_s390()

    @mock.patch.object(platform, 'machine', return_value=arch.S390X)
    def test_libvirt_fibrechan_driver_s390x(self, mock_machine):
        self._test_libvirt_fibrechan_driver_s390()

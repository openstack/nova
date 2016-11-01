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

import mock
from os_brick.initiator import connector

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import aoe


class LibvirtAOEVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):

    @mock.patch('os.path.exists', return_value=True)
    def test_libvirt_aoe_driver(self, exists):
        libvirt_driver = aoe.LibvirtAOEVolumeDriver(self.fake_host)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.AoEConnector)

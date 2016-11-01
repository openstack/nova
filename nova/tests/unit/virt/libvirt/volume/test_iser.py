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

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import iser


class LibvirtISERVolumeDriverTestCase(test_volume.LibvirtVolumeBaseTestCase):
    """Tests the libvirt iSER volume driver."""

    def test_get_transport(self):
        driver = iser.LibvirtISERVolumeDriver(self.fake_host)
        self.assertEqual('iser', driver._get_transport())

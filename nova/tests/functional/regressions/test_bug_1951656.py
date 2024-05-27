#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_vgpu


class VGPUTestsLibvirt7_7(test_vgpu.VGPUTestBase):

    FAKE_LIBVIRT_VERSION = 7007000

    def setUp(self):
        super(VGPUTestsLibvirt7_7, self).setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        # Start compute1 supporting only nvidia-11
        self.flags(
            enabled_mdev_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        self.compute1 = self.start_compute_with_vgpu('host1')

    def test_create_servers_with_vgpu(self):

        # Create a single instance against a specific compute node.
        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')

        self.assert_mdev_usage(self.compute1, expected_amount=1)

        self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')

        self.assert_mdev_usage(self.compute1, expected_amount=2)

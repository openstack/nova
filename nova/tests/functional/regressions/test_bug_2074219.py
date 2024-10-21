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


class VGPUTestVolumeOPs(test_vgpu.VGPUTestBase):

    FAKE_LIBVIRT_VERSION = 7007000

    def setUp(self):
        super().setUp()
        extra_spec = {"resources:VGPU": "1"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

        # Start compute1 supporting only nvidia-11
        self.flags(
            enabled_mdev_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        self.compute1 = self.start_compute_with_vgpu('host1')

    def test_create_vgpu_server_volume_attach(self):

        # Create a single instance against a specific compute node.
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=self.flavor, host=self.compute1.host,
            networks='auto', expected_state='ACTIVE')
        server_id = server['id']

        self.assert_mdev_usage(self.compute1, expected_amount=1)

        # Attach a volume to the instance
        # reuse IMAGE_BACKED_VOL for simplicity
        self.api.post_server_volume(
            server_id,
            {
                'volumeAttachment': {
                    'volumeId': self.cinder.IMAGE_BACKED_VOL
                }
            }
        )
        self._wait_for_volume_attach(server_id, self.cinder.IMAGE_BACKED_VOL)
        return server_id

    def test_create_vgpu_server_volume_detach(self):
        server_id = self.test_create_vgpu_server_volume_attach()
        # Detach the volume from the instance
        # DELETE /servers/{server_id}/os-volume_attachments/{volume_id} is
        # async but as we are using CastAsCall it's sync in our func tests
        self.api.delete_server_volume(
            server_id, self.cinder.IMAGE_BACKED_VOL)
        self._wait_for_volume_detach(
            server_id, self.cinder.IMAGE_BACKED_VOL)

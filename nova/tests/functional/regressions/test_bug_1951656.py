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

from oslo_utils import uuidutils


from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_vgpu
from nova.virt.libvirt import utils as libvirt_utils


class VGPUTestsLibvirt7_7(test_vgpu.VGPUTestBase):

    def _create_mdev(self, physical_device, mdev_type, uuid=None):
        # We need to fake the newly created sysfs object by adding a new
        # FakeMdevDevice in the existing persisted Connection object so
        # when asking to get the existing mdevs, we would see it.
        if not uuid:
            uuid = uuidutils.generate_uuid()
        mdev_name = libvirt_utils.mdev_uuid2name(uuid)
        libvirt_parent = self.pci2libvirt_address(physical_device)

        # Libvirt 7.7 now creates mdevs with a parent_addr suffix.
        new_mdev_name = '_'.join([mdev_name, libvirt_parent])

        # Here, we get the right compute thanks by the self.current_host that
        # was modified just before
        connection = self.computes[
            self._current_host].driver._host.get_connection()
        connection.mdev_info.devices.update(
            {mdev_name: fakelibvirt.FakeMdevDevice(dev_name=new_mdev_name,
                                                   type_id=mdev_type,
                                                   parent=libvirt_parent)})
        return uuid

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

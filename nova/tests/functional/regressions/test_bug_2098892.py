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


class VGPUTestsListDevices(test_vgpu.VGPUTestBase):
    """Regression test for bug 2098892.

    Test that nodeDeviceLookupByName() is called with valid types to prevent:

    File "/usr/lib64/python3.9/site-packages/libvirt.py", line 5201, in
      nodeDeviceLookupByName ret =
      libvirtmod.virNodeDeviceLookupByName(self._o, name)
      TypeError: virNodeDeviceLookupByName() argument 2 must be str or None,
      not Proxy

    in the future. This test relies on the LibvirtFixture checking for the
    correct types in its nodeDeviceLookupByName() method and raising TypeError
    if they are invalid.

    We don't test this by importing the libvirt module because the libvirt
    module is forbidden to be imported into our test environment. It is
    excluded from test-requirements.txt and we also use the
    ImportModulePoisonFixture in nova/test.py to prevent use of modules such as
    libvirt.
    """

    def setUp(self):
        super().setUp()

        # Start compute supporting only nvidia-11
        self.flags(
            enabled_mdev_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        self.start_compute_with_vgpu('host1')

    def test_update_available_resource(self):
        # We only want to verify no errors were logged by
        # update_available_resource (logging under the 'except Exception:').
        self._run_periodics(raise_on_error=True)

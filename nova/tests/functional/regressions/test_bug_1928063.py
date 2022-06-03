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

import copy
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova import test
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import base
from nova.virt.libvirt.host import SEV_KERNEL_PARAM_FILE


class TestSEVInstanceReboot(base.ServersTestBase):
    """Regression test for bug #1899835

    This regression test aims to assert the failure to hard reboot SEV based
    instances due to the use of image_meta.name within
    nova.virt.hardware.get_mem_encryption_constraint.
    """
    microversion = 'latest'

    @test.patch_open(SEV_KERNEL_PARAM_FILE, "1\n")
    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def setUp(self):
        super().setUp()

        # Configure the compute to allow SEV based instances and then start
        self.flags(num_memory_encrypted_guests=16, group='libvirt')
        with test.patch_exists(SEV_KERNEL_PARAM_FILE, True):
            self.start_compute()

        # Create a SEV enabled image for the test
        sev_image = copy.deepcopy(self.glance.image1)
        sev_image['id'] = uuids.sev_image_id
        sev_image['properties']['hw_firmware_type'] = 'uefi'
        sev_image['properties']['hw_machine_type'] = 'q35'
        sev_image['properties']['hw_mem_encryption'] = 'True'
        self.glance.create(None, sev_image)

    def test_hard_reboot(self):
        # Launch a SEV based instance and then attempt to hard reboot
        server = self._create_server(
            image_uuid=uuids.sev_image_id,
            networks='none'
        )

        # Hard reboot the server
        self._reboot_server(server, hard=True)

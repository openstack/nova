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

import fixtures
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import versionutils

from nova import exception
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver


class TestTDX(base.ServersTestBase):
    microversion = 'latest'

    def setUp(self):
        super().setUp()

        # Create a TDX enabled image for the test
        intel_tdx_image = copy.deepcopy(self.glance.image1)
        intel_tdx_image['id'] = uuids.intel_tdx_image_id
        intel_tdx_image['properties']['hw_firmware_type'] = 'uefi'
        intel_tdx_image['properties']['hw_firmware_stateless'] = 'True'
        intel_tdx_image['properties']['hw_machine_type'] = 'q35'
        intel_tdx_image['properties']['hw_mem_encryption'] = 'True'
        intel_tdx_image['properties']['hw_mem_encryption_model'] = 'intel-tdx'
        intel_tdx_image['properties']['hw_video_model'] = 'none'
        self.glance.create(None, intel_tdx_image)

        self.flags(cpu_mode='host-passthrough', group='libvirt')

        self.tdx = True
        self.misc_capacity = 63

        def mock_capacity():
            if not self.tdx or self.misc_capacity is None:
                return 0
            return self.misc_capacity

        def mock_domain_capability():
            if not self.tdx:
                return (
                    fakelibvirt.virConnect
                    ._domain_capability_features_with_TDX_unsupported
                )
            return fakelibvirt.virConnect._domain_capability_features_with_TDX

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._get_tdx_capacity',
            side_effect=mock_capacity))

        self.useFixture(fixtures.MockPatchObject(
            fakelibvirt.virConnect,
            '_domain_capability_features',
            new_callable=mock.PropertyMock,
            side_effect=mock_domain_capability))

    def test_intel_tdx_lost_after_restart(self):
        """Compute should fail if intel-tdx instance exists but intel-tdx is
        lost
        """
        libvirt_version = versionutils.convert_version_to_int(
            driver.MIN_LIBVIRT_STATELESS_FIRMWARE)
        self.hostname = self.start_compute(
            libvirt_version=libvirt_version)

        # create intel-tdx instance
        self._create_server(
            image_uuid=uuids.intel_tdx_image_id,
            networks='none'
        )

        # now intel-tdx is lost, so compute should fail
        self.tdx = False
        ex = self.assertRaises(
            exception.InvalidConfiguration,
            self.restart_compute_service, self.hostname)
        self.assertIn(
            'This host has instances with the memory encryption feature by '
            'intel-tdx enabled but the host is configured not to support '
            'this feature any more.',
            str(ex))

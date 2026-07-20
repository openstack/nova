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
from nova.virt.libvirt import host


class TestSEV(base.ServersTestBase):
    microversion = 'latest'

    def setUp(self):
        super().setUp()

        # Create a SEV enabled image for the test
        sev_image = copy.deepcopy(self.glance.image1)
        sev_image['id'] = uuids.sev_image_id
        sev_image['properties']['hw_firmware_type'] = 'uefi'
        sev_image['properties']['hw_machine_type'] = 'q35'
        sev_image['properties']['hw_mem_encryption'] = 'True'
        self.glance.create(None, sev_image)

        # Create a SEV-ES enabled image for the test
        sev_es_image = copy.deepcopy(self.glance.image1)
        sev_es_image['id'] = uuids.sev_es_image_id
        sev_es_image['properties']['hw_firmware_type'] = 'uefi'
        sev_es_image['properties']['hw_machine_type'] = 'q35'
        sev_es_image['properties']['hw_mem_encryption'] = 'True'
        sev_es_image['properties']['hw_mem_encryption_model'] = 'amd-sev-es'
        self.glance.create(None, sev_es_image)

        # Create a SEV-SNP enabled image for the test
        sev_snp_image = copy.deepcopy(self.glance.image1)
        sev_snp_image['id'] = uuids.sev_snp_image_id
        sev_snp_image['properties']['hw_firmware_type'] = 'uefi'
        sev_snp_image['properties']['hw_firmware_stateless'] = 'True'
        sev_snp_image['properties']['hw_machine_type'] = 'q35'
        sev_snp_image['properties']['hw_mem_encryption'] = 'True'
        sev_snp_image['properties']['hw_mem_encryption_model'] = 'amd-sev-snp'
        self.glance.create(None, sev_snp_image)

        self.sev = True
        self.sev_es = True
        self.sev_snp = False

        def mock_kernel(model='sev'):
            if model == 'sev-snp':
                return self.sev_snp
            if model == 'sev-es':
                return self.sev_es
            return self.sev

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._kernel_supports_amd_sev',
            side_effect=mock_kernel))

        self.qemu_version = versionutils.convert_version_to_int(
            host.MIN_QEMU_SEV_ES_VERSION)

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def test_sev_lost_after_restart(self):
        """Compute should fail if sev instance exists but sev is lost
        """
        self.hostname = self.start_compute(
            qemu_version=self.qemu_version)

        # create sev instance
        self._create_server(
            image_uuid=uuids.sev_image_id,
            networks='none'
        )

        # sev-es is lost but sev is still available, so compute should be
        # able to start
        self.sev_es = False
        self.restart_compute_service(self.hostname)

        # now sev is lost, so compute should fail
        self.sev = False
        ex = self.assertRaises(
            exception.InvalidConfiguration,
            self.restart_compute_service, self.hostname)
        self.assertIn(
            'This host has instances with the memory encryption feature by '
            'amd-sev enabled but the host is configured not to support '
            'this feature any more.',
            str(ex))

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def test_sev_es_lost_after_restart(self):
        """Compute should fail if sev-es instance exists but sev-es is lost
        """
        self.hostname = self.start_compute(
            qemu_version=self.qemu_version)

        # create sev-es instance
        self._create_server(
            image_uuid=uuids.sev_es_image_id,
            networks='none'
        )

        # now sev-es is lost, so compute should fail
        self.sev_es = False
        ex = self.assertRaises(
            exception.InvalidConfiguration,
            self.restart_compute_service, self.hostname)
        self.assertIn(
            'This host has instances with the memory encryption feature by '
            'amd-sev-es enabled but the host is configured not to support '
            'this feature any more.',
            str(ex))

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def test_sev_snp_detected_after_restart(self):
        """Compute should fail if sev-es instance exists but sev-snp is
        detected
        """
        self.hostname = self.start_compute(
            qemu_version=self.qemu_version)

        # create sev-es instance
        self._create_server(
            image_uuid=uuids.sev_es_image_id,
            networks='none'
        )

        # sev-es is lost because sev-snp is detected, so compute should fail
        self.sev_snp = True
        ex = self.assertRaises(
            exception.InvalidConfiguration,
            self.restart_compute_service, self.hostname)
        self.assertIn(
            'This host has instances with the memory encryption feature by '
            'amd-sev-es enabled but the host is configured not to support '
            'this feature any more.',
            str(ex))

    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect.
        _domain_capability_features_with_launch_security_SEV_SNP)
    def test_sev_snp_lost_after_restart(self):
        """Compute should fail if sev-snp instance exists but sev-snp is lost
        """
        self.sev_es = False
        self.sev_snp = True
        libvirt_version = versionutils.convert_version_to_int(
            driver.MIN_LIBVIRT_STATELESS_FIRMWARE)
        self.hostname = self.start_compute(
            libvirt_version=libvirt_version,
            qemu_version=self.qemu_version)

        # create sev-snp instance
        self._create_server(
            image_uuid=uuids.sev_snp_image_id,
            networks='none'
        )

        # now sev-snp is lost, so compute should fail
        self.sev_es = True
        self.sev_snp = False
        ex = self.assertRaises(
            exception.InvalidConfiguration,
            self.restart_compute_service, self.hostname)
        self.assertIn(
            'This host has instances with the memory encryption feature by '
            'amd-sev-snp enabled but the host is configured not to support '
            'this feature any more.',
            str(ex))

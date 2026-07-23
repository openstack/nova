# Copyright (c) 2018 Intel, Inc.
# All Rights Reserved.
#
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

import builtins
import contextlib
import ddt
import fixtures
import os
import os_resource_classes as orc
import os_traits as ost
from oslo_utils import versionutils
from unittest import mock

from nova import conf
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import integrated_helpers
from nova.virt.libvirt import host as libvirt_host

CONF = conf.CONF


class LibvirtReportTraitsTests(
        integrated_helpers.LibvirtProviderUsageBaseTestCase):
    # These must match the capabilities in
    # nova.virt.libvirt.driver.LibvirtDriver.capabilities
    expected_libvirt_driver_capability_traits = set([
        trait for trait in [
            ost.COMPUTE_ACCELERATORS,
            ost.COMPUTE_DEVICE_TAGGING,
            ost.COMPUTE_NET_ATTACH_INTERFACE,
            ost.COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG,
            ost.COMPUTE_VOLUME_ATTACH_WITH_TAG,
            ost.COMPUTE_VOLUME_EXTEND,
            ost.COMPUTE_VOLUME_MULTI_ATTACH,
            ost.COMPUTE_TRUSTED_CERTS,
            ost.COMPUTE_IMAGE_TYPE_AKI,
            ost.COMPUTE_IMAGE_TYPE_AMI,
            ost.COMPUTE_IMAGE_TYPE_ARI,
            ost.COMPUTE_IMAGE_TYPE_ISO,
            ost.COMPUTE_IMAGE_TYPE_QCOW2,
            ost.COMPUTE_IMAGE_TYPE_RAW,
            ost.COMPUTE_RESCUE_BFV,
        ]
    ])

    def test_report_cpu_traits(self):
        self.assertEqual([], self._get_all_providers())
        self.start_compute()

        # Test CPU traits reported on initial node startup, these specific
        # trait values are coming from fakelibvirt's baselineCPU result.
        # COMPUTE_NODE is always set on the compute node provider.
        traits = self._get_provider_traits(self.host_uuid)
        for trait in (
            'HW_CPU_X86_VMX', 'HW_CPU_X86_INTEL_VMX', 'HW_CPU_X86_AESNI',
            'COMPUTE_NODE',
        ):
            self.assertIn(trait, traits)

        self._create_trait('CUSTOM_TRAITS')
        new_traits = ['CUSTOM_TRAITS', 'HW_CPU_X86_AVX']
        self._set_provider_traits(self.host_uuid, new_traits)
        # The above is an out-of-band placement operation, as if the operator
        # used the CLI. So now we have to "SIGHUP the compute process" to clear
        # the report client cache so the subsequent update picks up the change.
        self.compute.manager.reset()
        self._run_periodics()
        # HW_CPU_X86_AVX is filtered out because nova-compute owns CPU traits
        # and it's not in the baseline for the host.
        traits = set(self._get_provider_traits(self.host_uuid))
        expected_traits = self.expected_libvirt_driver_capability_traits.union(
            [
                'HW_CPU_X86_VMX',
                'HW_CPU_X86_INTEL_VMX',
                'HW_CPU_X86_AESNI',
                'CUSTOM_TRAITS',
                # The periodic restored the COMPUTE_NODE trait.
                'COMPUTE_NODE',
            ])
        for trait in expected_traits:
            self.assertIn(trait, traits)


@ddt.ddt
class LibvirtReportSevTraitsTests(
        integrated_helpers.LibvirtProviderUsageBaseTestCase):

    STUB_INIT_HOST = False

    def setUp(self):
        super().setUp()
        qemu_version = versionutils.convert_version_to_int(
            libvirt_host.MIN_QEMU_SEV_ES_VERSION)
        self.useFixture(fixtures.MockPatchObject(
            fakelibvirt.Connection, 'getVersion',
            return_value=qemu_version))
        self.useFixture(fixtures.MockPatchObject(
            fakelibvirt.virConnect, '_domain_capability_features',
            new=fakelibvirt.virConnect.
                _domain_capability_features_with_launch_security_SEV_SNP))

    def start_compute_with_sev(self, sev, sev_es, sev_snp):
        self.libvirt.amd_sev.sev = sev
        self.libvirt.amd_sev.sev_es = sev_es
        self.libvirt.amd_sev.sev_snp = sev_snp
        self.start_compute()

    def restart_compute_service_with_sev(self, sev, sev_es, sev_snp):
        # Retrigger detection of SEV support
        self.compute.driver._host._domain_caps = None
        self.compute.driver._host._supports_amd_sev = None
        self.compute.driver._host._supports_amd_sev_es = None
        self.compute.driver._host._supports_amd_sev_snp = None

        self.libvirt.amd_sev.sev = sev
        self.libvirt.amd_sev.sev_es = sev_es
        self.libvirt.amd_sev.sev_snp = sev_snp
        self.restart_compute_service(self.compute)

    def assertMemEncryptionSlotsEqual(self, rp_uuid, slots):
        inventory = self._get_provider_inventory(rp_uuid)
        if slots == 0:
            self.assertNotIn(orc.MEM_ENCRYPTION_CONTEXT, inventory)
        else:
            self.assertEqual(
                {
                    'total': slots,
                    'min_unit': 1,
                    'max_unit': 1,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                    'reserved': 0,
                },
                inventory[orc.MEM_ENCRYPTION_CONTEXT]
            )

    def _get_amd_sev_rps(self):
        root_rp = self._get_resource_provider_by_uuid(self.host_uuid)
        rps = self._get_all_rps_in_a_tree(self.host_uuid)
        return {
            'sev': [rp for rp in rps
                    if rp['name'] == '%s_amd_sev' % root_rp['name']],
            'sev-es': [rp for rp in rps
                       if rp['name'] == '%s_amd_sev_es' % root_rp['name']],
            'sev-snp': [rp for rp in rps
                        if rp['name'] == '%s_amd_sev_snp' % root_rp['name']],
        }

    def _assert_global_sev_traits(self):
        """Assert that sev traits are present in global traits"""
        global_traits = self._get_all_traits()
        self.assertIn(ost.HW_CPU_X86_AMD_SEV, global_traits)
        self.assertIn(ost.HW_CPU_X86_AMD_SEV_ES, global_traits)
        self.assertIn(ost.HW_CPU_X86_AMD_SEV_SNP, global_traits)

    def _assert_root_provider_sev_traits(self):
        """Assert that sev capabilities are not present in root RP"""
        traits = self._get_provider_traits(self.host_uuid)
        self.assertNotIn(ost.HW_CPU_X86_AMD_SEV, traits)
        self.assertNotIn(ost.HW_CPU_X86_AMD_SEV_ES, traits)
        self.assertNotIn(ost.HW_CPU_X86_AMD_SEV_SNP, traits)
        self.assertMemEncryptionSlotsEqual(self.host_uuid, 0)

    def _assert_sev_rps(self, sev, sev_es, sev_snp):
        """Assert presence of sub-RPs representing SEV ASID slots"""

        # sanity checks for root RP
        self._assert_global_sev_traits()
        self._assert_root_provider_sev_traits()

        sev_rps = self._get_amd_sev_rps()
        if sev:
            self.assertEqual(1, len(sev_rps['sev']))
            rp_uuid = sev_rps['sev'][0]['uuid']
            rp_traits = self._get_provider_traits(rp_uuid)
            self.assertIn(ost.HW_CPU_X86_AMD_SEV, rp_traits)
            self.assertMemEncryptionSlotsEqual(rp_uuid, 100)
        else:
            self.assertEqual(0, len(sev_rps['sev']))

        if sev_es and not sev_snp:
            self.assertEqual(1, len(sev_rps['sev-es']))
            rp_uuid = sev_rps['sev-es'][0]['uuid']
            rp_traits = self._get_provider_traits(rp_uuid)
            self.assertIn(ost.HW_CPU_X86_AMD_SEV_ES, rp_traits)
            self.assertMemEncryptionSlotsEqual(rp_uuid, 15)
        else:
            self.assertEqual(0, len(sev_rps['sev-es']))

        if sev_snp:
            self.assertEqual(1, len(sev_rps['sev-snp']))
            rp_uuid = sev_rps['sev-snp'][0]['uuid']
            rp_traits = self._get_provider_traits(rp_uuid)
            self.assertIn(ost.HW_CPU_X86_AMD_SEV_SNP, rp_traits)
            self.assertMemEncryptionSlotsEqual(rp_uuid, 15)
        else:
            self.assertEqual(0, len(sev_rps['sev-snp']))

    def _assert_host_sev_support(self, sev, sev_es, sev_snp):
        """Assert sev support detected by LibvirtHost.

        We intentionally assert the internal caches so that we can also verify
        that these support flags are already evaluated.
        """
        self.assertIs(sev, self.compute.driver._host._supports_amd_sev)
        self.assertIs(sev_es and not sev_snp,
                      self.compute.driver._host._supports_amd_sev_es)
        self.assertIs(sev_snp, self.compute.driver._host._supports_amd_sev_snp)

    @ddt.unpack
    @ddt.data(
        # sev is detected
        (
            {'sev': False, 'sev_es': False, 'sev_snp': False},
            {'sev': True, 'sev_es': False, 'sev_snp': False}
        ),
        # sev-es is detected
        (
            {'sev': True, 'sev_es': False, 'sev_snp': False},
             {'sev': True, 'sev_es': True, 'sev_snp': False}
        ),
        # sev-snp is detected
        (
            {'sev': True, 'sev_es': True, 'sev_snp': False},
            {'sev': True, 'sev_es': True, 'sev_snp': True}
        ),
    )
    def test_sev_trait_off_on(self, before, after):
        """Test that the compute service reports the SEV trait in
        the list of global traits, but doesn't create SEV sub-RP in
        the placement API, due to the SEV capability being (mocked as) absent.

        Then test that if the SEV capability appears (again via mocking), after
        a restart of the compute service, the SEV sub-RP is created.
        """
        self.start_compute_with_sev(**before)

        before['sev_es'] = before['sev_es'] and not before['sev_snp']
        self._assert_host_sev_support(**before)
        self._assert_sev_rps(**before)

        self.restart_compute_service_with_sev(**after)

        after['sev_es'] = after['sev_es'] and not after['sev_snp']
        self._assert_host_sev_support(**after)
        self._assert_sev_rps(**after)

    @ddt.unpack
    @ddt.data(
        # sev is lost
        (
            {'sev': True, 'sev_es': False, 'sev_snp': False},
            {'sev': False, 'sev_es': False, 'sev_snp': False}
        ),
        # sev-es is lost
        (
            {'sev': True, 'sev_es': True, 'sev_snp': False},
            {'sev': True, 'sev_es': False, 'sev_snp': False}
        ),
        # sev-snp is lost
        (
            {'sev': True, 'sev_es': True, 'sev_snp': True},
            {'sev': True, 'sev_es': True, 'sev_snp': False}
        ),
        # sev and sev-es are lost
        (
            {'sev': True, 'sev_es': True, 'sev_snp': False},
            {'sev': False, 'sev_es': False, 'sev_snp': False}
        ),
    )
    def test_sev_trait_change(self, before, after):
        """Test that the compute service reports the SEV trait in
        the list of global traits, and immediately creates SEV sub-RP in
        the placement API, due to the SEV capability being (mocked as) present.

        Then test that if the SEV capability disappears (again via mocking),
        after a restart of the compute service, the SEV sub-RP is deleted.
        """
        self.start_compute_with_sev(**before)

        self._assert_host_sev_support(**before)
        self._assert_sev_rps(**before)

        self.restart_compute_service_with_sev(**after)

        self._assert_host_sev_support(**after)
        self._assert_sev_rps(**after)


@ddt.ddt
class LibvirtReportTdxTraitsTests(
        integrated_helpers.LibvirtProviderUsageBaseTestCase):

    STUB_INIT_HOST = False

    def start_compute_with_tdx(self, enabled):
        with self._patch_tdx_capability(enabled):
            self.start_compute()

    def restart_compute_service_with_tdx(self, enabled):
        # Retrigger detection of TDX support
        self.compute.driver._host._domain_caps = None
        self.compute.driver._host._supports_intel_tdx = None

        with self._patch_tdx_capability(enabled):
            self.restart_compute_service(self.compute)

    def assertMemEncryptionSlotsEqual(self, rp_uuid, slots):
        inventory = self._get_provider_inventory(rp_uuid)
        if slots == 0:
            self.assertNotIn(orc.MEM_ENCRYPTION_CONTEXT, inventory)
        else:
            self.assertEqual(
                {
                    'total': slots,
                    'min_unit': 1,
                    'max_unit': 1,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                    'reserved': 0,
                },
                inventory[orc.MEM_ENCRYPTION_CONTEXT]
            )

    def _get_intel_tdx_rps(self):
        root_rp = self._get_resource_provider_by_uuid(self.host_uuid)
        rps = self._get_all_rps_in_a_tree(self.host_uuid)
        return [rp for rp in rps
                if rp['name'] == '%s_intel_tdx' % root_rp['name']]

    @contextlib.contextmanager
    def _patch_tdx_capability(self, enabled):
        """Patch /sys/fs/cgroup/misc.capacity and domain tdx capability

        Domain tdx capability is changed according to the expected presence
        of TDX.
        """
        real_exists = os.path.exists
        real_open = builtins.open

        def fake_exists(path):
            if path == libvirt_host.MISC_CONTROL_GROUP_CAPACITY_FILE:
                return True
            return real_exists(path)

        def fake_open(path, *args, **kwargs):
            if path == libvirt_host.MISC_CONTROL_GROUP_CAPACITY_FILE:
                return mock.mock_open(read_data='tdx 63\n')(path)
            return real_open(path, *args, **kwargs)

        if enabled:
            caps = (fakelibvirt.virConnect.
                    _domain_capability_features_with_TDX)
        else:
            caps = (fakelibvirt.virConnect.
                    _domain_capability_features_with_TDX_unsupported)

        with mock.patch('os.path.exists') as mock_exists, \
                mock.patch('builtins.open') as mock_open, \
                mock.patch.object(fakelibvirt.virConnect,
                                  '_domain_capability_features',
                                  new=caps):
            mock_exists.side_effect = fake_exists
            mock_open.side_effect = fake_open

            yield

            if enabled:
                mock_exists.assert_has_calls([
                    mock.call(libvirt_host.MISC_CONTROL_GROUP_CAPACITY_FILE)
                ])
                mock_open.assert_has_calls([
                    mock.call(libvirt_host.MISC_CONTROL_GROUP_CAPACITY_FILE)
                ])

    def _assert_global_tdx_traits(self):
        """Assert that tdx traits are present in global traits"""
        global_traits = self._get_all_traits()
        self.assertIn(ost.HW_CPU_X86_INTEL_TDX, global_traits)

    def _assert_root_provider_tdx_traits(self):
        """Assert that tdx capabilities are not present in root RP"""
        traits = self._get_provider_traits(self.host_uuid)
        self.assertNotIn(ost.HW_CPU_X86_INTEL_TDX, traits)
        self.assertMemEncryptionSlotsEqual(self.host_uuid, 0)

    def _assert_tdx_rps(self, enabled):
        """Assert presence of sub-RPs representing TDX capacility"""

        # sanity checks for root RP
        self._assert_global_tdx_traits()
        self._assert_root_provider_tdx_traits()

        tdx_rps = self._get_intel_tdx_rps()
        if enabled:
            self.assertEqual(1, len(tdx_rps))
            rp_uuid = tdx_rps[0]['uuid']
            rp_traits = self._get_provider_traits(rp_uuid)
            self.assertIn(ost.HW_CPU_X86_INTEL_TDX, rp_traits)
            self.assertMemEncryptionSlotsEqual(rp_uuid, 63)
        else:
            self.assertEqual(0, len(tdx_rps))

    def _assert_host_tdx_support(self, enabled):
        """Assert tdx support detected by LibvirtHost.

        We intentionally assert the internal caches so that we can also verify
        that these support flags are already evaluated.
        """
        self.assertIs(enabled,
                      self.compute.driver._host._supports_intel_tdx)

    @ddt.unpack
    @ddt.data(
        (False, True),
        (True, False)
    )
    def test_tdx_trait_changed(self, before, after):
        """Test that the compute service reports the TDX trait in
        the list of global traits, but create TDX sub-RP in the placement API
        only when the TDX capability being (mocked as) present.

        Then test that if the TDX capability appears/disappears (again via
        mocking), after a restart of the compute service, the TDX sub-RP is
        created/deleted.
        """
        self.flags(cpu_mode="host-passthrough", group="libvirt")

        self.start_compute_with_tdx(before)
        self._assert_host_tdx_support(before)
        self._assert_tdx_rps(before)

        self.restart_compute_service_with_tdx(after)
        self._assert_host_tdx_support(after)
        self._assert_tdx_rps(after)

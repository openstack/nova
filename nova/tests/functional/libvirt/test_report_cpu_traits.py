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

import mock
import os_resource_classes as orc
import os_traits as ost


from nova import conf
from nova.db import constants as db_const
from nova import test
from nova.tests.functional.libvirt import integrated_helpers
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt.host import SEV_KERNEL_PARAM_FILE

CONF = conf.CONF


class LibvirtReportTraitsTestBase(
        integrated_helpers.LibvirtProviderUsageBaseTestCase):
    pass

    def assertMemEncryptionSlotsEqual(self, slots):
        inventory = self._get_provider_inventory(self.host_uuid)
        if slots == 0:
            self.assertNotIn(orc.MEM_ENCRYPTION_CONTEXT, inventory)
        else:
            self.assertEqual(
                inventory[orc.MEM_ENCRYPTION_CONTEXT],
                {
                    'total': slots,
                    'min_unit': 1,
                    'max_unit': 1,
                    'step_size': 1,
                    'allocation_ratio': 1.0,
                    'reserved': 0,
                }
            )


class LibvirtReportTraitsTests(LibvirtReportTraitsTestBase):
    def test_report_cpu_traits(self):
        self.assertEqual([], self._get_all_providers())
        self.start_compute()

        # Test CPU traits reported on initial node startup, these specific
        # trait values are coming from fakelibvirt's baselineCPU result.
        # COMPUTE_NODE is always set on the compute node provider.
        traits = self._get_provider_traits(self.host_uuid)
        for trait in ('HW_CPU_X86_VMX', 'HW_CPU_X86_AESNI', 'COMPUTE_NODE'):
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
            [u'HW_CPU_X86_VMX', u'HW_CPU_X86_AESNI', u'CUSTOM_TRAITS',
             # The periodic restored the COMPUTE_NODE trait.
             u'COMPUTE_NODE']
        )
        for trait in expected_traits:
            self.assertIn(trait, traits)


class LibvirtReportNoSevTraitsTests(LibvirtReportTraitsTestBase):
    STUB_INIT_HOST = False

    @test.patch_exists(SEV_KERNEL_PARAM_FILE, False)
    def setUp(self):
        super(LibvirtReportNoSevTraitsTests, self).setUp()
        self.start_compute()

    def test_sev_trait_off_on(self):
        """Test that the compute service reports the SEV trait in the list of
        global traits, but doesn't immediately register it on the
        compute host resource provider in the placement API, due to
        the kvm-amd kernel module's sev parameter file being (mocked
        as) absent.

        Then test that if the SEV capability appears (again via
        mocking), after a restart of the compute service, the trait
        gets registered on the compute host.

        Also test that on both occasions, the inventory of the
        MEM_ENCRYPTION_CONTEXT resource class on the compute host
        corresponds to the absence or presence of the SEV capability.
        """
        self.assertFalse(self.compute.driver._host.supports_amd_sev)

        sev_trait = ost.HW_CPU_X86_AMD_SEV

        global_traits = self._get_all_traits()
        self.assertIn(sev_trait, global_traits)

        traits = self._get_provider_traits(self.host_uuid)
        self.assertNotIn(sev_trait, traits)

        self.assertMemEncryptionSlotsEqual(0)

        # Now simulate the host gaining SEV functionality.  Here we
        # simulate a kernel update or reconfiguration which causes the
        # kvm-amd kernel module's "sev" parameter to become available
        # and set to 1, however it could also happen via a libvirt
        # upgrade, for instance.
        sev_features = \
            fakelibvirt.virConnect._domain_capability_features_with_SEV
        with test.nested(
                self.patch_exists(SEV_KERNEL_PARAM_FILE, True),
                self.patch_open(SEV_KERNEL_PARAM_FILE, "1\n"),
                mock.patch.object(fakelibvirt.virConnect,
                                  '_domain_capability_features',
                                  new=sev_features)
        ) as (mock_exists, mock_open, mock_features):
            # Retrigger the detection code.  In the real world this
            # would be a restart of the compute service.
            # As we are changing the domain caps we need to clear the
            # cache in the host object.
            self.compute.driver._host._domain_caps = None
            self.compute.driver._host._set_amd_sev_support()
            self.assertTrue(self.compute.driver._host.supports_amd_sev)

            mock_exists.assert_has_calls([mock.call(SEV_KERNEL_PARAM_FILE)])
            mock_open.assert_has_calls([mock.call(SEV_KERNEL_PARAM_FILE)])

            # However it won't disappear in the provider tree and get synced
            # back to placement until we force a reinventory:
            self.compute.manager.reset()
            # reset cached traits so they are recalculated.
            self.compute.driver._static_traits = None
            self._run_periodics()

            traits = self._get_provider_traits(self.host_uuid)
            self.assertIn(sev_trait, traits)

            # Sanity check that we've still got the trait globally.
            self.assertIn(sev_trait, self._get_all_traits())

            self.assertMemEncryptionSlotsEqual(db_const.MAX_INT)


class LibvirtReportSevTraitsTests(LibvirtReportTraitsTestBase):
    STUB_INIT_HOST = False

    @test.patch_exists(SEV_KERNEL_PARAM_FILE, True)
    @test.patch_open(SEV_KERNEL_PARAM_FILE, "1\n")
    @mock.patch.object(
        fakelibvirt.virConnect, '_domain_capability_features',
        new=fakelibvirt.virConnect._domain_capability_features_with_SEV)
    def setUp(self):
        super(LibvirtReportSevTraitsTests, self).setUp()
        self.flags(num_memory_encrypted_guests=16, group='libvirt')
        self.start_compute()

    def test_sev_trait_on_off(self):
        """Test that the compute service reports the SEV trait in the list of
        global traits, and immediately registers it on the compute
        host resource provider in the placement API, due to the SEV
        capability being (mocked as) present.

        Then test that if the SEV capability disappears (again via
        mocking), after a restart of the compute service, the trait
        gets removed from the compute host.

        Also test that on both occasions, the inventory of the
        MEM_ENCRYPTION_CONTEXT resource class on the compute host
        corresponds to the absence or presence of the SEV capability.
        """
        self.assertTrue(self.compute.driver._host.supports_amd_sev)

        sev_trait = ost.HW_CPU_X86_AMD_SEV

        global_traits = self._get_all_traits()
        self.assertIn(sev_trait, global_traits)

        traits = self._get_provider_traits(self.host_uuid)
        self.assertIn(sev_trait, traits)

        self.assertMemEncryptionSlotsEqual(16)

        # Now simulate the host losing SEV functionality.  Here we
        # simulate a kernel downgrade or reconfiguration which causes
        # the kvm-amd kernel module's "sev" parameter to become
        # unavailable, however it could also happen via a libvirt
        # downgrade, for instance.
        with self.patch_exists(SEV_KERNEL_PARAM_FILE, False) as mock_exists:
            # Retrigger the detection code.  In the real world this
            # would be a restart of the compute service.
            self.compute.driver._host._domain_caps = None
            self.compute.driver._host._set_amd_sev_support()
            self.assertFalse(self.compute.driver._host.supports_amd_sev)

            mock_exists.assert_has_calls([mock.call(SEV_KERNEL_PARAM_FILE)])

            # However it won't disappear in the provider tree and get synced
            # back to placement until we force a reinventory:
            self.compute.manager.reset()
            # reset cached traits so they are recalculated.
            self.compute.driver._static_traits = None
            self._run_periodics()

            traits = self._get_provider_traits(self.host_uuid)
            self.assertNotIn(sev_trait, traits)

            # Sanity check that we've still got the trait globally.
            self.assertIn(sev_trait, self._get_all_traits())

            self.assertMemEncryptionSlotsEqual(0)

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

import fixtures

from nova import conf
from nova.tests.functional import integrated_helpers
from nova.tests.unit.virt.libvirt import fakelibvirt

CONF = conf.CONF


class LibvirtReportTraitsTests(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'libvirt.LibvirtDriver'

    def setUp(self):
        super(LibvirtReportTraitsTests, self).setUp()
        self.useFixture(fakelibvirt.FakeLibvirtFixture(stub_os_vif=False))
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.init_host'))
        self.assertEqual([], self._get_all_providers())
        self.compute = self._start_compute(CONF.host)
        nodename = self.compute.manager._get_nodename(None)
        self.host_uuid = self._get_provider_uuid_by_host(nodename)

    def test_report_cpu_traits(self):
        # Test CPU traits reported on initial node startup, these specific
        # trait values are coming from fakelibvirt's baselineCPU result.
        self.assertItemsEqual(['HW_CPU_X86_VMX', 'HW_CPU_X86_AESNI'],
                              self._get_provider_traits(self.host_uuid))

        self._create_trait('CUSTOM_TRAITS')
        new_traits = ['CUSTOM_TRAITS', 'HW_CPU_X86_AVX']
        self._set_provider_traits(self.host_uuid, new_traits)
        self._run_periodics()
        # HW_CPU_X86_AVX is filtered out because nova-compute owns CPU traits
        # and it's not in the baseline for the host.
        self.assertItemsEqual(
            ['HW_CPU_X86_VMX', 'HW_CPU_X86_AESNI', 'CUSTOM_TRAITS'],
            self._get_provider_traits(self.host_uuid)
        )

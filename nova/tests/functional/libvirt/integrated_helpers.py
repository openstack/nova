#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import fixtures

from nova import conf
from nova.tests.functional import integrated_helpers
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = conf.CONF


class LibvirtProviderUsageBaseTestCase(
        integrated_helpers.ProviderUsageBaseTestCase):
    """Base test class for functional tests that check provider
    allocations and usage using the libvirt driver.
    """
    compute_driver = 'libvirt.LibvirtDriver'

    STUB_INIT_HOST = True

    def setUp(self):
        super(LibvirtProviderUsageBaseTestCase, self).setUp()
        self.useFixture(fakelibvirt.FakeLibvirtFixture(stub_os_vif=False))
        if self.STUB_INIT_HOST:
            self.useFixture(
                fixtures.MockPatch(
                    'nova.virt.libvirt.driver.LibvirtDriver.init_host'))
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.spawn'))

    def start_compute(self):
        self.compute = self._start_compute(CONF.host)
        nodename = self.compute.manager._get_nodename(None)
        self.host_uuid = self._get_provider_uuid_by_host(nodename)

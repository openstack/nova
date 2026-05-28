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

"""Regression test for bug 2154495.

https://bugs.launchpad.net/nova/+bug/2154495
"""

from unittest import mock

from nova.compute import manager
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base as libvirt_base


class VTPMStartupValidationMixin:
    """Regression test mixin for bug 2154495.

    The vTPM startup validation was added to catch hosts that used to support
    vTPM but are no longer configured correctly. Whether the check should
    inspect instance flavor and image metadata depends on whether the driver is
    vTPM-capable or can never support vTPM.
    """

    microversion = 'latest'
    ADMIN_API = True
    compute_host = 'compute1'

    def _start_compute_for_vtpm_test(self, hostname):
        raise NotImplementedError

    def _restart_compute_for_vtpm_test(self, compute):
        raise NotImplementedError

    def _test_compute_restart_vtpm_validation(
        self, expected_supports_vtpm, expected_call_count,
    ):
        self.compute = self._start_compute_for_vtpm_test(self.compute_host)
        self._create_server(networks='none')

        self.assertEqual(
            expected_supports_vtpm,
            self.compute.manager.driver.capabilities.get(
                'supports_vtpm', False))

        with mock.patch.object(
            manager.hardware, 'get_vtpm_constraint',
            wraps=manager.hardware.get_vtpm_constraint,
        ) as mock_get_vtpm_constraint:
            self.compute = self._restart_compute_for_vtpm_test(self.compute)

        self.assertEqual(
            expected_call_count, mock_get_vtpm_constraint.call_count)


class FakeDriverVTPMStartupValidationTest(
    VTPMStartupValidationMixin,
    integrated_helpers.ProviderUsageBaseTestCase,
):
    compute_driver = 'fake.SmallFakeDriver'

    def test_incapable_driver_skips_vtpm_config_inspection(self):
        self._test_compute_restart_vtpm_validation(
            expected_supports_vtpm=False, expected_call_count=0)

    def _start_compute_for_vtpm_test(self, hostname):
        return self._start_compute(hostname)

    def _restart_compute_for_vtpm_test(self, compute):
        return self.restart_compute_service(compute)


class LibvirtVTPMStartupValidationTest(
    VTPMStartupValidationMixin,
    libvirt_base.ServersTestBase,
):
    def setUp(self):
        # The fake libvirt test environment does not need the host-level
        # swtpm user and binary validation.
        _p = mock.patch(
            'nova.virt.libvirt.driver.LibvirtDriver._check_vtpm_support')
        _p.start()
        self.addCleanup(_p.stop)
        super().setUp()

    def test_vtpm_enabled_skips_vtpm_config_inspection(self):
        self.flags(swtpm_enabled=True, group='libvirt')
        self._test_compute_restart_vtpm_validation(
            expected_supports_vtpm=True, expected_call_count=0)

    def test_vtpm_disabled_inspects_vtpm_config(self):
        self.flags(swtpm_enabled=False, group='libvirt')
        self._test_compute_restart_vtpm_validation(
            expected_supports_vtpm=False, expected_call_count=1)

    def _start_compute_for_vtpm_test(self, hostname):
        self.start_compute(
            hostname=hostname,
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        return self.computes[hostname]

    def _restart_compute_for_vtpm_test(self, compute):
        return self.restart_compute_service(compute.host)

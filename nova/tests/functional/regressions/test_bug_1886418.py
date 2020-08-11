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

from nova.tests.functional import integrated_helpers


class TestServices(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super(TestServices, self).setUp()
        self.compute_rp_uuid = self.admin_api.api_get(
            'os-hypervisors?hypervisor_hostname_pattern=fake-mini'
        ).body['hypervisors'][0]['id']
        self.compute_service_id = self.admin_api.get_services(
            host='compute', binary='nova-compute')[0]['id']

    def _get_traits_on_compute(self):
        return self.placement.get(
            '/resource_providers/%s/traits' % self.compute_rp_uuid,
            version='1.6'
        ).body['traits']

    def _disable_compute(self):
        self.admin_api.put_service(
            self.compute_service_id, {'status': 'disabled'})

    def _enable_compute(self):
        self.admin_api.put_service(
            self.compute_service_id, {'status': 'enabled'})

    def _has_disabled_trait(self):
        return "COMPUTE_STATUS_DISABLED" in self._get_traits_on_compute()

    def test_compute_disable_after_server_create(self):
        # Check that COMPUTE_STATUS_DISABLED is not on the compute
        self.assertFalse(self._has_disabled_trait())

        self._disable_compute()
        # Check that COMPUTE_STATUS_DISABLED is now on the compute
        self.assertTrue(self._has_disabled_trait())

        self._enable_compute()
        # Check that COMPUTE_STATUS_DISABLED is not on the compute
        self.assertFalse(self._has_disabled_trait())

        # Create a server.
        self._create_server(networks=[])

        self._disable_compute()

        # Check that COMPUTE_STATUS_DISABLED is now on the compute.
        self.assertTrue(self._has_disabled_trait())

        # This would be the expected behavior
        #
        # self.assertTrue(self._has_disabled_trait())
        #
        # Alternatively the test could wait for the periodic to run or trigger
        # it manually.

        # This passes now but not because enabling works but because the
        # above fault caused that COMPUTE_STATUS_DISABLED is not on the compute
        # RP in the first place.
        self._enable_compute()
        # Check that COMPUTE_STATUS_DISABLED is removed from the compute
        self.assertFalse(self._has_disabled_trait())
        self.assertNotIn(
            'An error occurred while updating COMPUTE_STATUS_DISABLED trait '
            'on compute node resource provider',
            self.stdlog.logger.output,
            "This is probably bug 1886418.")

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


class TestEvacuateDeleteServerRestartOriginalCompute(
        integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TestEvacuateDeleteServerRestartOriginalCompute, self).setUp()
        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_evacuate_delete_server_restart_original_compute(self):
        """Regression test for bug 1794996 where a server is successfully
        evacuated from a down host and then deleted. Then the source compute
        host is brought back online and attempts to cleanup the guest from
        the hypervisor and allocations for the evacuated (and now deleted)
        instance. Before the bug is fixed, the original compute fails to start
        because lazy-loading the instance.flavor on the deleted instance,
        which is needed to cleanup allocations from the source host, raises
        InstanceNotFound. After the bug is fixed, the original source host
        compute service starts up.
        """
        source_hostname = self.compute1.host
        dest_hostname = self.compute2.host

        server = self._boot_and_check_allocations(
            self.flavor1, source_hostname)

        source_compute_id = self.admin_api.get_services(
            host=source_hostname, binary='nova-compute')[0]['id']

        self.compute1.stop()
        # force it down to avoid waiting for the service group to time out
        self.admin_api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # evacuate the server
        post = {'evacuate': {}}
        self.api.post_server_action(
            server['id'], post)
        expected_params = {'OS-EXT-SRV-ATTR:host': dest_hostname,
                           'status': 'ACTIVE'}
        server = self._wait_for_server_parameter(server, expected_params)

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        self.assertFlavorMatchesUsage(source_rp_uuid, self.flavor1)
        self.assertFlavorMatchesUsage(dest_rp_uuid, self.flavor1)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(2, len(allocations))
        self._check_allocation_during_evacuate(
            self.flavor1, server['id'], source_rp_uuid, dest_rp_uuid)

        # Delete the evacuated server. The allocations should be gone from
        # both the original evacuated-from host and the evacuated-to host.
        self._delete_and_check_allocations(server)

        # restart the source compute
        self.compute1 = self.restart_compute_service(self.compute1)

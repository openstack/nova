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

from oslo_log import log as logging

from nova.tests.functional import integrated_helpers

LOG = logging.getLogger(__name__)


class TestEvacuateDeleteServerRestartOriginalCompute(
        integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TestEvacuateDeleteServerRestartOriginalCompute, self).setUp()
        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    # NOTE(mriedem): This is here for backports and should be removed later
    # on master (Stein).
    def assertFlavorMatchesAllocation(self, flavor, allocation):
        self.assertEqual(flavor['vcpus'], allocation['VCPU'])
        self.assertEqual(flavor['ram'], allocation['MEMORY_MB'])
        self.assertEqual(flavor['disk'], allocation['DISK_GB'])

    # NOTE(mriedem): This is here for backports and should be removed later
    # on master (Stein).
    def _boot_and_check_allocations(self, flavor, source_hostname):
        """Boot an instance and check that the resource allocation is correct
        After booting an instance on the given host with a given flavor it
        asserts that both the providers usages and resource allocations match
        with the resources requested in the flavor. It also asserts that
        running the periodic update_available_resource call does not change the
        resource state.
        :param flavor: the flavor the instance will be booted with
        :param source_hostname: the name of the host the instance will be
                                booted on
        :return: the API representation of the booted instance
        """
        server_req = self._build_minimal_create_server_request(
            self.api, 'some-server', flavor_id=flavor['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        server_req['availability_zone'] = 'nova:%s' % source_hostname
        LOG.info('booting on %s', source_hostname)
        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(
            self.admin_api, created_server, 'ACTIVE')

        # Verify that our source host is what the server ended up on
        self.assertEqual(source_hostname, server['OS-EXT-SRV-ATTR:host'])

        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)

        # Before we run periodics, make sure that we have allocations/usages
        # only on the source host
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(flavor, source_usages)

        # Check that the other providers has no usage
        for rp_uuid in [self._get_provider_uuid_by_host(hostname)
                        for hostname in self.computes.keys()
                        if hostname != source_hostname]:
            usages = self._get_provider_usages(rp_uuid)
            self.assertEqual({'VCPU': 0,
                              'MEMORY_MB': 0,
                              'DISK_GB': 0}, usages)

        # Check that the server only allocates resource from the host it is
        # booted on
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations),
                         'No allocation for the server on the host it '
                         'is booted on')
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(flavor, allocation)

        self._run_periodics()

        # After running the periodics but before we start any other operation,
        # we should have exactly the same allocation/usage information as
        # before running the periodics

        # Check usages on the selected host after boot
        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(flavor, source_usages)

        # Check that the server only allocates resource from the host it is
        # booted on
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(1, len(allocations),
                         'No allocation for the server on the host it '
                         'is booted on')
        allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(flavor, allocation)

        # Check that the other providers has no usage
        for rp_uuid in [self._get_provider_uuid_by_host(hostname)
                        for hostname in self.computes.keys()
                        if hostname != source_hostname]:
            usages = self._get_provider_usages(rp_uuid)
            self.assertEqual({'VCPU': 0,
                              'MEMORY_MB': 0,
                              'DISK_GB': 0}, usages)

        return server

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
        server = self._wait_for_server_parameter(self.api, server,
                                                 expected_params)

        # Expect to have allocation and usages on both computes as the
        # source compute is still down
        source_rp_uuid = self._get_provider_uuid_by_host(source_hostname)
        dest_rp_uuid = self._get_provider_uuid_by_host(dest_hostname)

        source_usages = self._get_provider_usages(source_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, source_usages)

        dest_usages = self._get_provider_usages(dest_rp_uuid)
        self.assertFlavorMatchesAllocation(self.flavor1, dest_usages)

        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(2, len(allocations))
        source_allocation = allocations[source_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, source_allocation)
        dest_allocation = allocations[dest_rp_uuid]['resources']
        self.assertFlavorMatchesAllocation(self.flavor1, dest_allocation)

        # Delete the evacuated server. The allocations should be gone from
        # both the original evacuated-from host and the evacuated-to host.
        self._delete_and_check_allocations(server)

        # restart the source compute
        self.restart_compute_service(self.compute1)

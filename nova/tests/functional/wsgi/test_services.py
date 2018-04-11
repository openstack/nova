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

import six

from nova import context as nova_context
from nova import exception
from nova import objects
from nova import rc_fields
from nova.tests.functional.api import client as api_client
from nova.tests.functional import integrated_helpers


class TestServicesAPI(integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'fake.SmallFakeDriver'

    def test_compute_service_delete_ensure_related_cleanup(self):
        """Tests deleting a compute service and the related cleanup associated
        with that like the compute_nodes table entry, removing the host
        from any aggregates, the host mapping in the API DB and the associated
        resource provider in Placement.
        """
        compute = self._start_compute('host1')
        # Make sure our compute host is represented as expected.
        services = self.admin_api.get_services(binary='nova-compute')
        self.assertEqual(1, len(services))
        service = services[0]

        # Now create a host aggregate and add our host to it.
        aggregate = self.admin_api.post_aggregate(
            {'aggregate': {'name': 'agg1'}})
        self.admin_api.add_host_to_aggregate(aggregate['id'], service['host'])
        # Make sure the host is in the aggregate.
        aggregate = self.admin_api.api_get(
            '/os-aggregates/%s' % aggregate['id']).body['aggregate']
        self.assertEqual([service['host']], aggregate['hosts'])

        rp_uuid = self._get_provider_uuid_by_host(service['host'])

        # We'll know there is a host mapping implicitly if os-hypervisors
        # returned something in _get_provider_uuid_by_host, but let's also
        # make sure the host mapping is there like we expect.
        ctxt = nova_context.get_admin_context()
        objects.HostMapping.get_by_host(ctxt, service['host'])

        # Make sure there is a resource provider for that compute node based
        # on the uuid.
        resp = self.placement_api.get('/resource_providers/%s' % rp_uuid)
        self.assertEqual(200, resp.status)

        # Make sure the resource provider has inventory.
        inventories = self._get_provider_inventory(rp_uuid)
        # Expect a minimal set of inventory for the fake virt driver.
        for resource_class in [rc_fields.ResourceClass.VCPU,
                               rc_fields.ResourceClass.MEMORY_MB,
                               rc_fields.ResourceClass.DISK_GB]:
            self.assertIn(resource_class, inventories)

        # Now create a server so that the resource provider has some allocation
        # records.
        flavor = self.api.get_flavors()[0]
        server = self._boot_and_check_allocations(flavor, service['host'])

        # Now the fun part, delete the compute service and make sure related
        # resources are cleaned up, like the compute node, host mapping, and
        # resource provider. We have to first stop the compute service so
        # it doesn't recreate the compute node during the
        # update_available_resource periodic task.
        self.admin_api.put_service(service['id'], {'forced_down': True})
        compute.stop()
        # The first attempt should fail since there is an instance on the
        # compute host.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.admin_api.api_delete,
                               '/os-services/%s' % service['id'])
        self.assertIn('Unable to delete compute service that is hosting '
                      'instances.', six.text_type(ex))
        self.assertEqual(409, ex.response.status_code)

        # Now delete the instance and wait for it to be gone.
        self._delete_and_check_allocations(server)

        # Now we can delete the service.
        self.admin_api.api_delete('/os-services/%s' % service['id'])

        # Make sure the service is deleted.
        services = self.admin_api.get_services(binary='nova-compute')
        self.assertEqual(0, len(services))

        # Make sure the host was removed from the aggregate.
        aggregate = self.admin_api.api_get(
            '/os-aggregates/%s' % aggregate['id']).body['aggregate']
        self.assertEqual([], aggregate['hosts'])

        # Trying to get the hypervisor should result in a 404.
        self.admin_api.api_get(
            'os-hypervisors?hypervisor_hostname_pattern=%s' % service['host'],
            check_response_status=[404])

        # The host mapping should also be gone.
        self.assertRaises(exception.HostMappingNotFound,
                          objects.HostMapping.get_by_host,
                          ctxt, service['host'])

        # And finally, the resource provider should also be gone. The API
        # will perform a cascading delete of the resource provider inventory
        # and allocation information.
        resp = self.placement_api.get('/resource_providers/%s' % rp_uuid)
        self.assertEqual(404, resp.status)

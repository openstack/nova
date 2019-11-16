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

import os_resource_classes as orc
import os_traits
import six

from nova import context as nova_context
from nova import exception
from nova import objects
from nova.tests.functional.api import client as api_client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova import utils


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
        for resource_class in [orc.VCPU, orc.MEMORY_MB, orc.DISK_GB]:
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

    def test_evacuate_then_delete_compute_service(self):
        """Tests a scenario where a server is created on a host, the host
        goes down, the server is evacuated to another host, and then the
        source host compute service is deleted. After that the deleted
        compute service is restarted. Related placement resources are checked
        throughout.
        """
        # Create our source host that we will evacuate *from* later.
        host1 = self._start_compute('host1')
        # Create a server which will go on host1 since it is the only host.
        flavor = self.api.get_flavors()[0]
        server = self._boot_and_check_allocations(flavor, 'host1')
        # Get the compute service record for host1 so we can manage it.
        service = self.admin_api.get_services(
            binary='nova-compute', host='host1')[0]
        # Get the corresponding resource provider uuid for host1.
        rp_uuid = self._get_provider_uuid_by_host(service['host'])
        # Make sure there is a resource provider for that compute node based
        # on the uuid.
        resp = self.placement_api.get('/resource_providers/%s' % rp_uuid)
        self.assertEqual(200, resp.status)
        # Down the compute service for host1 so we can evacuate from it.
        self.admin_api.put_service(service['id'], {'forced_down': True})
        host1.stop()
        # Start another host and trigger the server evacuate to that host.
        self._start_compute('host2')
        self.admin_api.post_server_action(server['id'], {'evacuate': {}})
        # The host does not change until after the status is changed to ACTIVE
        # so wait for both parameters.
        self._wait_for_server_parameter(
            self.admin_api, server, {'status': 'ACTIVE',
                                     'OS-EXT-SRV-ATTR:host': 'host2'})
        # Delete the compute service for host1 and check the related
        # placement resources for that host.
        self.admin_api.api_delete('/os-services/%s' % service['id'])
        # Make sure the service is gone.
        services = self.admin_api.get_services(
            binary='nova-compute', host='host1')
        self.assertEqual(0, len(services), services)
        # FIXME(mriedem): This is bug 1829479 where the compute service is
        # deleted but the resource provider is not because there are still
        # allocations against the provider from the evacuated server.
        resp = self.placement_api.get('/resource_providers/%s' % rp_uuid)
        self.assertEqual(200, resp.status)
        self.assertFlavorMatchesUsage(rp_uuid, flavor)
        # Try to restart the host1 compute service to create a new resource
        # provider.
        self.restart_compute_service(host1)
        # FIXME(mriedem): This is bug 1817833 where restarting the now-deleted
        # compute service attempts to create a new resource provider with a
        # new uuid but the same name which results in a conflict. The service
        # does not die, however, because _update_available_resource_for_node
        # catches and logs but does not re-raise the error.
        log_output = self.stdlog.logger.output
        self.assertIn('Error updating resources for node host1.', log_output)
        self.assertIn('Failed to create resource provider host1', log_output)

    def test_migrate_confirm_after_deleted_source_compute(self):
        """Tests a scenario where a server is cold migrated and while in
        VERIFY_RESIZE status the admin attempts to delete the source compute
        and then the user tries to confirm the resize.
        """
        # Start a compute service and create a server there.
        self._start_compute('host1')
        host1_rp_uuid = self._get_provider_uuid_by_host('host1')
        flavor = self.api.get_flavors()[0]
        server = self._boot_and_check_allocations(flavor, 'host1')
        # Start a second compute service so we can cold migrate there.
        self._start_compute('host2')
        host2_rp_uuid = self._get_provider_uuid_by_host('host2')
        # Cold migrate the server to host2.
        self._migrate_and_check_allocations(
            server, flavor, host1_rp_uuid, host2_rp_uuid)
        # Delete the source compute service.
        service = self.admin_api.get_services(
            binary='nova-compute', host='host1')[0]
        # We expect the delete request to fail with a 409 error because of the
        # instance in VERIFY_RESIZE status even though that instance is marked
        # as being on host2 now.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.admin_api.api_delete,
                               '/os-services/%s' % service['id'])
        self.assertEqual(409, ex.response.status_code)
        self.assertIn('Unable to delete compute service that has in-progress '
                      'migrations', six.text_type(ex))
        self.assertIn('There are 1 in-progress migrations involving the host',
                      self.stdlog.logger.output)
        # The provider is still around because we did not delete the service.
        resp = self.placement_api.get('/resource_providers/%s' % host1_rp_uuid)
        self.assertEqual(200, resp.status)
        self.assertFlavorMatchesUsage(host1_rp_uuid, flavor)
        # Now try to confirm the migration.
        self._confirm_resize(server)
        # Delete the host1 service since the migration is confirmed and the
        # server is on host2.
        self.admin_api.api_delete('/os-services/%s' % service['id'])
        # The host1 resource provider should be gone.
        resp = self.placement_api.get('/resource_providers/%s' % host1_rp_uuid)
        self.assertEqual(404, resp.status)

    def test_resize_revert_after_deleted_source_compute(self):
        """Tests a scenario where a server is resized and while in
        VERIFY_RESIZE status the admin attempts to delete the source compute
        and then the user tries to revert the resize.
        """
        # Start a compute service and create a server there.
        self._start_compute('host1')
        host1_rp_uuid = self._get_provider_uuid_by_host('host1')
        flavors = self.api.get_flavors()
        flavor1 = flavors[0]
        flavor2 = flavors[1]
        server = self._boot_and_check_allocations(flavor1, 'host1')
        # Start a second compute service so we can resize there.
        self._start_compute('host2')
        host2_rp_uuid = self._get_provider_uuid_by_host('host2')
        # Resize the server to host2.
        self._resize_and_check_allocations(
            server, flavor1, flavor2, host1_rp_uuid, host2_rp_uuid)
        # Delete the source compute service.
        service = self.admin_api.get_services(
            binary='nova-compute', host='host1')[0]
        # We expect the delete request to fail with a 409 error because of the
        # instance in VERIFY_RESIZE status even though that instance is marked
        # as being on host2 now.
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.admin_api.api_delete,
                               '/os-services/%s' % service['id'])
        self.assertEqual(409, ex.response.status_code)
        self.assertIn('Unable to delete compute service that has in-progress '
                      'migrations', six.text_type(ex))
        self.assertIn('There are 1 in-progress migrations involving the host',
                      self.stdlog.logger.output)
        # The provider is still around because we did not delete the service.
        resp = self.placement_api.get('/resource_providers/%s' % host1_rp_uuid)
        self.assertEqual(200, resp.status)
        self.assertFlavorMatchesUsage(host1_rp_uuid, flavor1)
        # Now revert the resize.
        self._revert_resize(server)
        self.assertFlavorMatchesUsage(host1_rp_uuid, flavor1)
        zero_flavor = {'vcpus': 0, 'ram': 0, 'disk': 0, 'extra_specs': {}}
        self.assertFlavorMatchesUsage(host2_rp_uuid, zero_flavor)
        # Delete the host2 service since the migration is reverted and the
        # server is on host1 again.
        service2 = self.admin_api.get_services(
            binary='nova-compute', host='host2')[0]
        self.admin_api.api_delete('/os-services/%s' % service2['id'])
        # The host2 resource provider should be gone.
        resp = self.placement_api.get('/resource_providers/%s' % host2_rp_uuid)
        self.assertEqual(404, resp.status)


class ComputeStatusFilterTest(integrated_helpers.ProviderUsageBaseTestCase):
    """Tests the API, compute service and Placement interaction with the
    COMPUTE_STATUS_DISABLED trait when a compute service is enable/disabled.

    This version of the test uses the 2.latest microversion for testing the
    2.53+ behavior of the PUT /os-services/{service_id} API.
    """
    compute_driver = 'fake.SmallFakeDriver'

    def _update_service(self, service, disabled, forced_down=None):
        """Update the service using the 2.53 request schema.

        :param service: dict representing the service resource in the API
        :param disabled: True if the service should be disabled, False if the
            service should be enabled
        :param forced_down: Optionally change the forced_down value.
        """
        status = 'disabled' if disabled else 'enabled'
        req = {'status': status}
        if forced_down is not None:
            req['forced_down'] = forced_down
        self.admin_api.put_service(service['id'], req)

    def test_compute_status_filter(self):
        """Tests the compute_status_filter placement request filter"""
        # Start a compute service so a compute node and resource provider is
        # created.
        compute = self._start_compute('host1')
        # Get the UUID of the resource provider that was created.
        rp_uuid = self._get_provider_uuid_by_host('host1')
        # Get the service from the compute API.
        services = self.admin_api.get_services(binary='nova-compute',
                                               host='host1')
        self.assertEqual(1, len(services))
        service = services[0]

        # At this point, the service should be enabled and the
        # COMPUTE_STATUS_DISABLED trait should not be set on the
        # resource provider in placement.
        self.assertEqual('enabled', service['status'])
        rp_traits = self._get_provider_traits(rp_uuid)
        trait = os_traits.COMPUTE_STATUS_DISABLED
        self.assertNotIn(trait, rp_traits)

        # Now disable the compute service via the API.
        self._update_service(service, disabled=True)

        # The update to placement should be synchronous so check the provider
        # traits and COMPUTE_STATUS_DISABLED should be set.
        rp_traits = self._get_provider_traits(rp_uuid)
        self.assertIn(trait, rp_traits)

        # Try creating a server which should fail because nothing is available.
        networks = [{'port': self.neutron.port_1['id']}]
        server_req = self._build_minimal_create_server_request(
            self.api, 'test_compute_status_filter',
            image_uuid=fake_image.get_valid_image_id(), networks=networks)
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(self.api, server, 'ERROR')
        # There should be a NoValidHost fault recorded.
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])

        # Now enable the service and the trait should be gone.
        self._update_service(service, disabled=False)
        rp_traits = self._get_provider_traits(rp_uuid)
        self.assertNotIn(trait, rp_traits)

        # Try creating another server and it should be OK.
        server = self.api.post_server({'server': server_req})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Stop, force-down and disable the service so the API cannot call
        # the compute service to sync the trait.
        compute.stop()
        self._update_service(service, disabled=True, forced_down=True)
        # The API should have logged a message about the service being down.
        self.assertIn('Compute service on host host1 is down. The '
                      'COMPUTE_STATUS_DISABLED trait will be synchronized '
                      'when the service is restarted.',
                      self.stdlog.logger.output)
        # The trait should not be on the provider even though the node is
        # disabled.
        rp_traits = self._get_provider_traits(rp_uuid)
        self.assertNotIn(trait, rp_traits)
        # Restart the compute service which should sync and set the trait on
        # the provider in placement.
        self.restart_compute_service(compute)
        rp_traits = self._get_provider_traits(rp_uuid)
        self.assertIn(trait, rp_traits)


class ComputeStatusFilterTest211(ComputeStatusFilterTest):
    """Extends ComputeStatusFilterTest and uses the 2.11 API for the
    legacy os-services disable/enable/force-down API behavior
    """
    microversion = '2.11'

    def _update_service(self, service, disabled, forced_down=None):
        """Update the service using the 2.11 request schema.

        :param service: dict representing the service resource in the API
        :param disabled: True if the service should be disabled, False if the
            service should be enabled
        :param forced_down: Optionally change the forced_down value.
        """
        # Before 2.53 the service is uniquely identified by host and binary.
        body = {
            'host': service['host'],
            'binary': service['binary']
        }
        # Handle forced_down first if provided since the enable/disable
        # behavior in the API depends on it.
        if forced_down is not None:
            body['forced_down'] = forced_down
            self.admin_api.api_put('/os-services/force-down', body)

        if disabled:
            self.admin_api.api_put('/os-services/disable', body)
        else:
            self.admin_api.api_put('/os-services/enable', body)

    def _get_provider_uuid_by_host(self, host):
        # We have to temporarily mutate to 2.53 to get the hypervisor UUID.
        with utils.temporary_mutation(self.admin_api, microversion='2.53'):
            return super(ComputeStatusFilterTest211,
                         self)._get_provider_uuid_by_host(host)

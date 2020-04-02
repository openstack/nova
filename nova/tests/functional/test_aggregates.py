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

from oslo_utils.fixture import uuidsentinel as uuids

import nova.conf
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture
from nova.tests.unit import utils as test_utils
from nova import utils

CONF = nova.conf.CONF


class AggregatesTest(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'
    ADMIN_API = True

    def _add_hosts_to_aggregate(self):
        """List all compute services and add them all to an aggregate."""

        compute_services = [s for s in self.api.get_services()
                            if s['binary'] == 'nova-compute']
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        for service in compute_services:
            self.api.add_host_to_aggregate(agg['id'], service['host'])
        self._test_aggregate = agg
        return len(compute_services)

    def test_add_hosts(self):
        # Default case with one compute, mapped for us
        self.assertEqual(1, self._add_hosts_to_aggregate())

    def test_add_unmapped_host(self):
        """Ensure that hosts without mappings are still found and added"""

        # Add another compute, but nuke its HostMapping
        self.start_service('compute', host='compute2')
        self.host_mappings['compute2'].destroy()
        self.assertEqual(2, self._add_hosts_to_aggregate())


class AggregatesV281Test(AggregatesTest):
    api_major_version = 'v2.1'
    microversion = '2.81'

    def setUp(self):
        self.flags(compute_driver='fake.FakeDriverWithCaching')
        super(AggregatesV281Test, self).setUp()

    def test_cache_images_on_aggregate(self):
        self._add_hosts_to_aggregate()
        agg = self._test_aggregate
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e6'

        self.assertEqual(set(), self.compute.driver.cached_images)

        body = {'cache': [
            {'id': img},
        ]}
        self.api.api_post('/os-aggregates/%s/images' % agg['id'], body,
                          check_response_status=[202])

        self.assertEqual(set([img]), self.compute.driver.cached_images)

    def test_cache_images_on_aggregate_missing_image(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        # NOTE(danms): This image-id does not exist
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e0'
        body = {'cache': [
            {'id': img},
        ]}
        self.api.api_post('/os-aggregates/%s/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_on_missing_aggregate(self):
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        body = {'cache': [
            {'id': img},
        ]}
        self.api.api_post('/os-aggregates/123/images', body,
                          check_response_status=[404])

    def test_cache_images_with_duplicates(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        body = {'cache': [
            {'id': img},
            {'id': img},
        ]}
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_with_no_images(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        body = {'cache': []}
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_with_additional_in_image(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        body = {'cache': [
            {'id': img, 'power': '1.21 gigawatts'},
        ]}
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_with_missing_image_id(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        body = {'cache': [
            {'power': '1.21 gigawatts'},
        ]}
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_with_missing_cache(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        body = {}
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])

    def test_cache_images_with_additional_in_cache(self):
        agg = {'aggregate': {'name': 'test-aggregate'}}
        agg = self.api.post_aggregate(agg)
        img = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        body = {'cache': [{'id': img}],
                'power': '1.21 gigawatts',
        }
        self.api.api_post('/os-aggregates/%i/images' % agg['id'], body,
                          check_response_status=[400])


class AggregateRequestFiltersTest(
        integrated_helpers.ProviderUsageBaseTestCase):
    microversion = 'latest'
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super(AggregateRequestFiltersTest, self).setUp()

        self.aggregates = {}

        self._start_compute('host1')
        self._start_compute('host2')

        self.flavors = self.api.get_flavors()

        # Aggregate with only host1
        self._create_aggregate('only-host1')
        self._add_host_to_aggregate('only-host1', 'host1')

        # Aggregate with only host2
        self._create_aggregate('only-host2')
        self._add_host_to_aggregate('only-host2', 'host2')

        # Aggregate with neither host
        self._create_aggregate('no-hosts')

    def _create_aggregate(self, name):
        agg = self.admin_api.post_aggregate({'aggregate': {'name': name}})
        self.aggregates[name] = agg

    def _get_provider_uuid_by_host(self, host):
        """Return the compute node uuid for a named compute host."""
        # NOTE(gibi): the compute node id is the same as the compute node
        # provider uuid on that compute
        resp = self.admin_api.api_get(
            'os-hypervisors?hypervisor_hostname_pattern=%s' % host).body
        return resp['hypervisors'][0]['id']

    def _add_host_to_aggregate(self, agg, host):
        """Add a compute host to both nova and placement aggregates.

        :param agg: Name of the nova aggregate
        :param host: Name of the compute host
        """
        agg = self.aggregates[agg]
        self.admin_api.add_host_to_aggregate(agg['id'], host)

    def _boot_server(self, az=None, flavor_id=None, image_id=None,
                     end_status='ACTIVE'):
        flavor_id = flavor_id or self.flavors[0]['id']
        image_uuid = image_id or '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        server_req = self._build_server(
            image_uuid=image_uuid,
            flavor_id=flavor_id,
            networks='none', az=az)

        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(created_server, end_status)

        return server

    def _get_instance_host(self, server):
        srv = self.admin_api.get_server(server['id'])
        return srv['OS-EXT-SRV-ATTR:host']

    def _set_az_aggregate(self, agg, az):
        """Set the availability_zone of an aggregate

        :param agg: Name of the nova aggregate
        :param az: Availability zone name
        """
        agg = self.aggregates[agg]
        action = {
            'set_metadata': {
                'metadata': {
                    'availability_zone': az,
                }
            },
        }
        self.admin_api.post_aggregate_action(agg['id'], action)

    def _set_metadata(self, agg, metadata):
        """POST /os-aggregates/{aggregate_id}/action (set_metadata)

        :param agg: Name of the nova aggregate
        :param metadata: dict of aggregate metadata key/value pairs to add,
            update, or remove if value=None (note "availability_zone" cannot be
            nulled out once set).
        """
        agg = self.aggregates[agg]
        action = {
            'set_metadata': {
                'metadata': metadata
            },
        }
        self.admin_api.post_aggregate_action(agg['id'], action)

    def _grant_tenant_aggregate(self, agg, tenants):
        """Grant a set of tenants access to use an aggregate.

        :param agg: Name of the nova aggregate
        :param tenants: A list of all tenant ids that will be allowed access
        """
        agg = self.aggregates[agg]
        action = {
            'set_metadata': {
                'metadata': {
                    'filter_tenant_id%i' % i: tenant
                    for i, tenant in enumerate(tenants)
                }
            },
        }
        self.admin_api.post_aggregate_action(agg['id'], action)

    def _set_traits_on_aggregate(self, agg, traits):
        """Set traits to aggregate.

        :param agg: Name of the nova aggregate
        :param traits: List of traits to be assigned to the aggregate
        """
        action = {
            'set_metadata': {
                'metadata': {
                    'trait:' + trait: 'required'
                    for trait in traits
                }
            }
        }
        self.admin_api.post_aggregate_action(
            self.aggregates[agg]['id'], action)


class AggregatePostTest(AggregateRequestFiltersTest):

    def test_set_az_for_aggreate_no_instances(self):
        """Should be possible to update AZ for an empty aggregate.

        Check you can change the AZ name of an aggregate when it does
        not contain any servers.
        """
        self._set_az_aggregate('only-host1', 'fake-az')

    def test_rename_to_same_az(self):
        """AZ rename should pass successfully if AZ name is not changed"""
        az = 'fake-az'
        self._set_az_aggregate('only-host1', az)
        self._boot_server(az=az)
        self._set_az_aggregate('only-host1', az)

    def test_fail_set_az(self):
        """Check it is not possible to update a non-empty aggregate.

        Check you cannot change the AZ name of an aggregate when it
        contains any servers.
        """
        az = 'fake-az'
        self._set_az_aggregate('only-host1', az)
        server = self._boot_server(az=az)
        self.assertRaisesRegex(
            client.OpenStackApiException,
            'One or more hosts contain instances in this zone.',
            self._set_az_aggregate, 'only-host1', 'new' + az)

        # Configure for the SOFT_DELETED scenario.
        self.flags(reclaim_instance_interval=300)
        self.api.delete_server(server['id'])
        server = self._wait_for_state_change(server, 'SOFT_DELETED')
        self.assertRaisesRegex(
            client.OpenStackApiException,
            'One or more hosts contain instances in this zone.',
            self._set_az_aggregate, 'only-host1', 'new' + az)
        # Force delete the SOFT_DELETED server.
        self.api.api_post(
            '/servers/%s/action' % server['id'], {'forceDelete': None})
        # Wait for it to be deleted since forceDelete is asynchronous.
        self._wait_until_deleted(server)
        # Now we can rename the AZ since the server is gone.
        self._set_az_aggregate('only-host1', 'new' + az)

    def test_cannot_delete_az(self):
        az = 'fake-az'
        # Assign the AZ to the aggregate.
        self._set_az_aggregate('only-host1', az)
        # Set some metadata on the aggregate; note the "availability_zone"
        # metadata key is not specified.
        self._set_metadata('only-host1', {'foo': 'bar'})
        # Verify the AZ was retained.
        agg = self.admin_api.api_get(
            '/os-aggregates/%s' %
            self.aggregates['only-host1']['id']).body['aggregate']
        self.assertEqual(az, agg['availability_zone'])


# NOTE: this test case has the same test methods as AggregatePostTest
# but for the AZ update it uses PUT /os-aggregates/{aggregate_id} method
class AggregatePutTest(AggregatePostTest):

    def _set_az_aggregate(self, agg, az):
        """Set the availability_zone of an aggregate via PUT

        :param agg: Name of the nova aggregate
        :param az: Availability zone name
        """
        agg = self.aggregates[agg]
        body = {
            'aggregate': {
                'availability_zone': az,
            },
        }
        self.admin_api.put_aggregate(agg['id'], body)


class TenantAggregateFilterTest(AggregateRequestFiltersTest):
    def setUp(self):
        super(TenantAggregateFilterTest, self).setUp()

        # Default to enabling the filter and making it mandatory
        self.flags(limit_tenants_to_placement_aggregate=True,
                   group='scheduler')
        self.flags(placement_aggregate_required_for_tenants=True,
                   group='scheduler')

    def test_tenant_id_required_fails_if_no_aggregate(self):
        # Without granting our tenant permission to an aggregate, instance
        # creates should fail since aggregates are required
        self._boot_server(end_status='ERROR')

    def test_tenant_id_not_required_succeeds_if_no_aggregate(self):
        self.flags(placement_aggregate_required_for_tenants=False,
                   group='scheduler')
        # Without granting our tenant permission to an aggregate, instance
        # creates should still succeed since aggregates are not required
        self._boot_server(end_status='ACTIVE')

    def test_filter_honors_tenant_id(self):
        tenant = self.api.project_id

        # Grant our tenant access to the aggregate with only host1 in it
        # and boot some servers. They should all stack up on host1.
        self._grant_tenant_aggregate('only-host1',
                                     ['foo', tenant, 'bar'])
        server1 = self._boot_server(end_status='ACTIVE')
        server2 = self._boot_server(end_status='ACTIVE')

        # Grant our tenant access to the aggregate with only host2 in it
        # and boot some servers. They should all stack up on host2.
        self._grant_tenant_aggregate('only-host1',
                                     ['foo', 'bar'])
        self._grant_tenant_aggregate('only-host2',
                                     ['foo', tenant, 'bar'])
        server3 = self._boot_server(end_status='ACTIVE')
        server4 = self._boot_server(end_status='ACTIVE')

        # Make sure the servers landed on the hosts we had access to at
        # the time we booted them.
        hosts = [self._get_instance_host(s)
                 for s in (server1, server2, server3, server4)]
        expected_hosts = ['host1', 'host1', 'host2', 'host2']
        self.assertEqual(expected_hosts, hosts)

    def test_filter_with_empty_aggregate(self):
        tenant = self.api.project_id

        # Grant our tenant access to the aggregate with no hosts in it
        self._grant_tenant_aggregate('no-hosts',
                                     ['foo', tenant, 'bar'])
        self._boot_server(end_status='ERROR')

    def test_filter_with_multiple_aggregates_for_tenant(self):
        tenant = self.api.project_id

        # Grant our tenant access to the aggregate with no hosts in it,
        # and one with a host.
        self._grant_tenant_aggregate('no-hosts',
                                     ['foo', tenant, 'bar'])
        self._grant_tenant_aggregate('only-host2',
                                     ['foo', tenant, 'bar'])

        # Boot several servers and make sure they all land on the
        # only host we have access to.
        for i in range(0, 4):
            server = self._boot_server(end_status='ACTIVE')
            self.assertEqual('host2', self._get_instance_host(server))


class AvailabilityZoneFilterTest(AggregateRequestFiltersTest):
    def setUp(self):
        # Default to enabling the filter
        self.flags(query_placement_for_availability_zone=True,
                   group='scheduler')

        # Use custom weigher to make sure that we have a predictable
        # scheduling sort order.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        # NOTE(danms): Do this before calling setUp() so that
        # the scheduler service that is started sees the new value
        filters = CONF.filter_scheduler.enabled_filters
        filters.remove('AvailabilityZoneFilter')
        self.flags(enabled_filters=filters, group='filter_scheduler')

        super(AvailabilityZoneFilterTest, self).setUp()

    def test_filter_with_az(self):
        self._set_az_aggregate('only-host2', 'myaz')
        server1 = self._boot_server(az='myaz')
        server2 = self._boot_server(az='myaz')
        hosts = [self._get_instance_host(s) for s in (server1, server2)]
        self.assertEqual(['host2', 'host2'], hosts)


class IsolateAggregateFilterTest(AggregateRequestFiltersTest):
    def setUp(self):
        # Default to enabling the filter
        self.flags(enable_isolated_aggregate_filtering=True,
                   group='scheduler')

        # Use a custom weigher that would prefer host1 if the isolate
        # aggregate filter were not in place otherwise it's not deterministic
        # whether we're landing on host2 because of the filter or just by
        # chance.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        super(IsolateAggregateFilterTest, self).setUp()
        self.image_service = nova.tests.unit.image.fake.FakeImageService()
        # setting traits to flavors
        flavor_body = {'flavor': {'name': 'test_flavor',
                                  'ram': 512,
                                  'vcpus': 1,
                                  'disk': 1
                                  }}
        self.flavor_with_trait_dxva = self.api.post_flavor(flavor_body)
        self.admin_api.post_extra_spec(
            self.flavor_with_trait_dxva['id'],
            {'extra_specs': {'trait:HW_GPU_API_DXVA': 'required'}})
        flavor_body['flavor']['name'] = 'test_flavor1'
        self.flavor_with_trait_sgx = self.api.post_flavor(flavor_body)
        self.admin_api.post_extra_spec(
            self.flavor_with_trait_sgx['id'],
            {'extra_specs': {'trait:HW_CPU_X86_SGX': 'required'}})
        self.flavor_without_trait = self.flavors[0]

        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            images = self.api.get_images()
            self.image_id_without_trait = images[0]['id']

    def test_filter_with_no_valid_host(self):
        """Test 'isolate_aggregates' filter with no valid hosts.

        No required traits set in image/flavor, so all aggregates with
        required traits set should be ignored.
        """

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(
            rp_uuid1, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])
        self._set_traits_on_aggregate(
            'only-host1', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(
            rp_uuid2, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])
        self._set_traits_on_aggregate(
            'only-host2', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        server = self._boot_server(
            flavor_id=self.flavor_without_trait['id'],
            image_id=self.image_id_without_trait,
            end_status='ERROR')
        self.assertIsNone(self._get_instance_host(server))
        self.assertIn('No valid host', server['fault']['message'])

    def test_filter_without_trait(self):
        """Test 'isolate_aggregates' filter with valid hosts.

        No required traits set in image/flavor so instance should be booted on
        host from an aggregate with no required traits set.
        """

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(
            rp_uuid1, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])
        self._set_traits_on_aggregate(
            'only-host1', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        server = self._boot_server(
            flavor_id=self.flavor_without_trait['id'],
            image_id=self.image_id_without_trait)
        self.assertEqual('host2', self._get_instance_host(server))

    def test_filter_with_trait_on_flavor(self):
        """Test filter with matching required traits set only in one aggregate.

        Required trait (HW_GPU_API_DXVA) set in flavor so instance should be
        booted on host with matching required traits set on aggregates.
        """

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(rp_uuid2, ['HW_GPU_API_DXVA'])

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(
            rp_uuid1, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        self._set_traits_on_aggregate('only-host2', ['HW_GPU_API_DXVA'])
        self._set_traits_on_aggregate(
            'only-host1', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_dxva['id'],
            image_id=self.image_id_without_trait)

        self.assertEqual('host2', self._get_instance_host(server))

    def test_filter_with_common_trait_on_aggregates(self):
        """Test filter with common required traits set to aggregates.

        Required trait (HW_CPU_X86_SGX) set in flavor so instance should be
        booted on host with exact matching required traits set on aggregates.
        """

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(rp_uuid2, ['HW_CPU_X86_SGX'])

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(
            rp_uuid1, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        self._set_traits_on_aggregate('only-host2', ['HW_CPU_X86_SGX'])
        self._set_traits_on_aggregate(
            'only-host1', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_sgx['id'],
            image_id=self.image_id_without_trait)

        self.assertEqual('host2', self._get_instance_host(server))

    def test_filter_with_traits_on_image_and_flavor(self):
        """Test filter with common traits set to image/flavor and aggregates.

        Required trait (HW_CPU_X86_SGX) set in flavor and
        required trait (HW_CPU_X86_VMX) set in image, so instance should be
        booted on host with exact matching required traits set on aggregates.
        """

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(
            rp_uuid2, ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(rp_uuid1, ['HW_GPU_API_DXVA'])

        self._set_traits_on_aggregate('only-host1', ['HW_GPU_API_DXVA'])
        self._set_traits_on_aggregate(
            'only-host2', ['HW_CPU_X86_VMX', 'HW_CPU_X86_SGX'])

        # Creating a new image and setting traits on it.
        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            self.ctxt = test_utils.get_test_admin_context()
            img_ref = self.image_service.create(self.ctxt, {'name': 'image10'})
            image_id_with_trait = img_ref['id']
            self.addCleanup(
                self.image_service.delete, self.ctxt, image_id_with_trait)
            self.api.api_put('/images/%s/metadata' % image_id_with_trait,
                             {'metadata': {
                                 'trait:HW_CPU_X86_VMX': 'required'}})
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_sgx['id'],
            image_id=image_id_with_trait)
        self.assertEqual('host2', self._get_instance_host(server))

    def test_filter_with_traits_image_flavor_subset_of_aggregates(self):
        """Test filter with image/flavor required traits subset of aggregates.

        Image and flavor has a nonempty set of required traits that's subset
        set of the traits on the aggregates.
        """

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(
            rp_uuid2, ['HW_CPU_X86_VMX', 'HW_GPU_API_DXVA', 'HW_CPU_X86_SGX'])

        self._set_traits_on_aggregate(
            'only-host2',
            ['HW_CPU_X86_VMX', 'HW_GPU_API_DXVA', 'HW_CPU_X86_SGX'])

        # Creating a new image and setting traits on it.
        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            self.ctxt = test_utils.get_test_admin_context()
            img_ref = self.image_service.create(self.ctxt, {'name': 'image10'})
            image_id_with_trait = img_ref['id']
            self.addCleanup(
                self.image_service.delete, self.ctxt, image_id_with_trait)
            self.api.api_put('/images/%s/metadata' % image_id_with_trait,
                             {'metadata': {
                                 'trait:HW_CPU_X86_VMX': 'required'}})
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_sgx['id'],
            image_id=image_id_with_trait,
            end_status='ERROR')

        self.assertIsNone(self._get_instance_host(server))
        self.assertIn('No valid host', server['fault']['message'])

    def test_filter_with_traits_image_flavor_disjoint_of_aggregates(self):
        """Test filter with image/flav required traits disjoint of aggregates.

        Image and flavor has a nonempty set of required traits that's disjoint
        set of the traits on the aggregates.
        """

        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(rp_uuid2, ['HW_CPU_X86_VMX'])

        rp_uuid1 = self._get_provider_uuid_by_host('host1')
        self._set_provider_traits(rp_uuid1, ['HW_GPU_API_DXVA'])

        self._set_traits_on_aggregate('only-host1', ['HW_GPU_API_DXVA'])
        self._set_traits_on_aggregate('only-host2', ['HW_CPU_X86_VMX'])

        # Creating a new image and setting traits on it.
        with nova.utils.temporary_mutation(self.api, microversion='2.35'):
            self.ctxt = test_utils.get_test_admin_context()
            img_ref = self.image_service.create(self.ctxt, {'name': 'image10'})
            image_id_with_trait = img_ref['id']
            self.addCleanup(
                self.image_service.delete, self.ctxt, image_id_with_trait)
            self.api.api_put('/images/%s/metadata' % image_id_with_trait,
                             {'metadata': {
                                 'trait:HW_CPU_X86_VMX': 'required'}})
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_sgx['id'],
            image_id=image_id_with_trait,
            end_status='ERROR')

        self.assertIsNone(self._get_instance_host(server))
        self.assertIn('No valid host', server['fault']['message'])


class IsolateAggregateFilterTestWithConcernFilters(IsolateAggregateFilterTest):
    def setUp(self):
        filters = CONF.filter_scheduler.enabled_filters

        # NOTE(shilpasd): To test `isolate_aggregates` request filter, along
        # with following filters which also filters hosts based on aggregate
        # metadata.
        if 'AggregateImagePropertiesIsolation' not in filters:
            filters.append('AggregateImagePropertiesIsolation')
        if 'AggregateInstanceExtraSpecsFilter' not in filters:
            filters.append('AggregateInstanceExtraSpecsFilter')
        self.flags(enabled_filters=filters, group='filter_scheduler')

        super(IsolateAggregateFilterTestWithConcernFilters, self).setUp()


class IsolateAggregateFilterTestWOConcernFilters(IsolateAggregateFilterTest):
    def setUp(self):
        filters = CONF.filter_scheduler.enabled_filters

        # NOTE(shilpasd): To test `isolate_aggregates` request filter, removed
        # following filters which also filters hosts based on aggregate
        # metadata.
        if 'AggregateImagePropertiesIsolation' in filters:
            filters.remove('AggregateImagePropertiesIsolation')
        if 'AggregateInstanceExtraSpecsFilter' in filters:
            filters.remove('AggregateInstanceExtraSpecsFilter')
        self.flags(enabled_filters=filters, group='filter_scheduler')

        super(IsolateAggregateFilterTestWOConcernFilters, self).setUp()


class TestAggregateFiltersTogether(AggregateRequestFiltersTest):
    def setUp(self):
        # Use a custom weigher that would prefer host1 if the forbidden
        # aggregate filter were not in place otherwise it's not deterministic
        # whether we're landing on host2 because of the filter or just by
        # chance.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())

        # NOTE(danms): Do this before calling setUp() so that
        # the scheduler service that is started sees the new value
        filters = CONF.filter_scheduler.enabled_filters
        filters.remove('AvailabilityZoneFilter')

        # NOTE(shilpasd): To test `isolate_aggregates` request filter, removed
        # following filters which also filters hosts based on aggregate
        # metadata.
        if 'AggregateImagePropertiesIsolation' in filters:
            filters.remove('AggregateImagePropertiesIsolation')
        if 'AggregateInstanceExtraSpecsFilter' in filters:
            filters.remove('AggregateInstanceExtraSpecsFilter')
        self.flags(enabled_filters=filters, group='filter_scheduler')

        super(TestAggregateFiltersTogether, self).setUp()

        # Default to enabling all filters
        self.flags(limit_tenants_to_placement_aggregate=True,
                   group='scheduler')
        self.flags(placement_aggregate_required_for_tenants=True,
                   group='scheduler')
        self.flags(query_placement_for_availability_zone=True,
                   group='scheduler')
        self.flags(enable_isolated_aggregate_filtering=True,
                   group='scheduler')
        # setting traits to flavors
        flavor_body = {'flavor': {'name': 'test_flavor',
                                  'ram': 512,
                                  'vcpus': 1,
                                  'disk': 1
                                  }}
        self.flavor_with_trait_dxva = self.api.post_flavor(flavor_body)
        self.admin_api.post_extra_spec(
            self.flavor_with_trait_dxva['id'],
            {'extra_specs': {'trait:HW_GPU_API_DXVA': 'required'}})

    def test_tenant_with_az_match(self):
        # Grant our tenant access to the aggregate with
        # host1
        self._grant_tenant_aggregate('only-host1',
                                     [self.api.project_id])
        # Set an az on only-host1
        self._set_az_aggregate('only-host1', 'myaz')

        # Boot the server into that az and make sure we land
        server = self._boot_server(az='myaz')
        self.assertEqual('host1', self._get_instance_host(server))

    def test_tenant_with_az_mismatch(self):
        # Grant our tenant access to the aggregate with
        # host1
        self._grant_tenant_aggregate('only-host1',
                                     [self.api.project_id])
        # Set an az on only-host2
        self._set_az_aggregate('only-host2', 'myaz')

        # Boot the server into that az and make sure we fail
        server = self._boot_server(az='myaz', end_status='ERROR')
        self.assertIsNone(self._get_instance_host(server))

    def test_tenant_with_az_and_traits_match(self):
        # Grant our tenant access to the aggregate with host2
        self._grant_tenant_aggregate('only-host2',
                                     [self.api.project_id])
        # Set an az on only-host2
        self._set_az_aggregate('only-host2', 'myaz')
        # Set trait on host2
        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(rp_uuid2, ['HW_GPU_API_DXVA'])
        # Set trait on aggregate only-host2
        self._set_traits_on_aggregate('only-host2', ['HW_GPU_API_DXVA'])
        # Boot the server into that az and make sure we land
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_dxva['id'], az='myaz')
        self.assertEqual('host2', self._get_instance_host(server))

    def test_tenant_with_az_and_traits_mismatch(self):
        # Grant our tenant access to the aggregate with host2
        self._grant_tenant_aggregate('only-host2',
                                     [self.api.project_id])
        # Set an az on only-host1
        self._set_az_aggregate('only-host2', 'myaz')
        # Set trait on host2
        rp_uuid2 = self._get_provider_uuid_by_host('host2')
        self._set_provider_traits(rp_uuid2, ['HW_CPU_X86_VMX'])
        # Set trait on aggregate only-host2
        self._set_traits_on_aggregate('only-host2', ['HW_CPU_X86_VMX'])
        # Boot the server into that az and make sure we fail
        server = self._boot_server(
            flavor_id=self.flavor_with_trait_dxva['id'],
            az='myaz',
            end_status='ERROR')
        self.assertIsNone(self._get_instance_host(server))
        self.assertIn('No valid host', server['fault']['message'])


class TestAggregateMultiTenancyIsolationFilter(
        test.TestCase, integrated_helpers.InstanceHelperMixin):

    def setUp(self):
        super(TestAggregateMultiTenancyIsolationFilter, self).setUp()
        # Stub out glance, placement and neutron.
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        # Start nova services.
        self.start_service('conductor')
        self.admin_api = self.useFixture(
            nova_fixtures.OSAPIFixture(api_version='v2.1')).admin_api
        self.api = self.useFixture(
            nova_fixtures.OSAPIFixture(api_version='v2.1',
                                       project_id=uuids.non_admin)).api
        # Add the AggregateMultiTenancyIsolation to the list of enabled
        # filters since it is not enabled by default.
        enabled_filters = CONF.filter_scheduler.enabled_filters
        enabled_filters.append('AggregateMultiTenancyIsolation')
        self.flags(enabled_filters=enabled_filters, group='filter_scheduler')
        self.start_service('scheduler')
        for host in ('host1', 'host2'):
            self.start_service('compute', host=host)

    def test_aggregate_multitenancy_isolation_filter(self):
        """Tests common scenarios with the AggregateMultiTenancyIsolation
        filter:

        * hosts in a tenant-isolated aggregate are only accepted for that
          tenant
        * hosts not in a tenant-isolated aggregate are acceptable for all
          tenants, including tenants with access to the isolated-tenant
          aggregate
        """
        # Create a tenant-isolated aggregate for the non-admin user.
        agg_id = self.admin_api.post_aggregate(
            {'aggregate': {'name': 'non_admin_agg'}})['id']
        meta_req = {'set_metadata': {
            'metadata': {'filter_tenant_id': uuids.non_admin}}}
        self.admin_api.api_post('/os-aggregates/%s/action' % agg_id, meta_req)
        # Add host2 to the aggregate; we'll restrict host2 to the non-admin
        # tenant.
        host_req = {'add_host': {'host': 'host2'}}
        self.admin_api.api_post('/os-aggregates/%s/action' % agg_id, host_req)
        # Stub out select_destinations to assert how many host candidates were
        # available per tenant-specific request.
        original_filtered_hosts = (
            nova.scheduler.host_manager.HostManager.get_filtered_hosts)

        def spy_get_filtered_hosts(*args, **kwargs):
            self.filtered_hosts = original_filtered_hosts(*args, **kwargs)
            return self.filtered_hosts
        self.stub_out(
            'nova.scheduler.host_manager.HostManager.get_filtered_hosts',
            spy_get_filtered_hosts)

        # Create a server for the admin - should only have one host candidate.
        server_req = {'server': self._build_server(networks='none')}
        with utils.temporary_mutation(self.admin_api, microversion='2.37'):
            server = self.admin_api.post_server(server_req)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Assert it's not on host2 which is isolated to the non-admin tenant.
        self.assertNotEqual('host2', server['OS-EXT-SRV-ATTR:host'])
        self.assertEqual(1, len(self.filtered_hosts))
        # Now create a server for the non-admin tenant to which host2 is
        # isolated via the aggregate, but the other compute host is a
        # candidate. We don't assert that the non-admin tenant server shows
        # up on host2 because the other host, which is not isolated to the
        # aggregate, is still a candidate.
        server_req = {'server': self._build_server(networks='none')}
        with utils.temporary_mutation(self.api, microversion='2.37'):
            server = self.api.post_server(server_req)
        self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(2, len(self.filtered_hosts))


class AggregateMultiTenancyIsolationColdMigrateTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):

    @staticmethod
    def _create_aggregate(admin_api, name):
        return admin_api.api_post(
            '/os-aggregates', {'aggregate': {'name': name}}).body['aggregate']

    @staticmethod
    def _add_host_to_aggregate(admin_api, aggregate, host):
        add_host_req_body = {
            "add_host": {
                "host": host
            }
        }
        admin_api.api_post(
            '/os-aggregates/%s/action' % aggregate['id'], add_host_req_body)

    @staticmethod
    def _isolate_aggregate(admin_api, aggregate, tenant_id):
        set_meta_req_body = {
            "set_metadata": {
                "metadata": {
                    "filter_tenant_id": tenant_id
                }
            }
        }
        admin_api.api_post(
            '/os-aggregates/%s/action' % aggregate['id'], set_meta_req_body)

    def setUp(self):
        super(AggregateMultiTenancyIsolationColdMigrateTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        # Intentionally keep these separate since we want to create the
        # server with the non-admin user in a different project.
        admin_api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1', project_id=uuids.admin_project))
        self.admin_api = admin_api_fixture.admin_api
        self.admin_api.microversion = 'latest'
        user_api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1', project_id=uuids.user_project))
        self.api = user_api_fixture.api
        self.api.microversion = 'latest'

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.start_service('conductor')
        # Enable the AggregateMultiTenancyIsolation filter before starting the
        # scheduler service.
        enabled_filters = CONF.filter_scheduler.enabled_filters
        if 'AggregateMultiTenancyIsolation' not in enabled_filters:
            enabled_filters.append('AggregateMultiTenancyIsolation')
            self.flags(
                enabled_filters=enabled_filters, group='filter_scheduler')
        # Add a custom weigher which will weigh host1, which will be in the
        # admin project aggregate, higher than the other hosts which are in
        # the non-admin project aggregate.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        self.start_service('scheduler')

        for host in ('host1', 'host2', 'host3'):
            self.start_service('compute', host=host)

        # Create an admin-only aggregate for the admin project. This is needed
        # because if host1 is not in an aggregate with the filter_tenant_id
        # metadata key, the filter will accept that host even for the non-admin
        # project.
        admin_aggregate = self._create_aggregate(
            self.admin_api, 'admin-aggregate')
        self._add_host_to_aggregate(self.admin_api, admin_aggregate, 'host1')

        # Restrict the admin project to the admin aggregate.
        self._isolate_aggregate(
            self.admin_api, admin_aggregate, uuids.admin_project)

        # Create the tenant aggregate for the non-admin project.
        tenant_aggregate = self._create_aggregate(
            self.admin_api, 'tenant-aggregate')

        # Add two compute hosts to the tenant aggregate. We exclude host1
        # since that is weighed higher due to HostNameWeigherFixture and we
        # want to ensure the scheduler properly filters out host1 before we
        # even get to weighing the selected hosts.
        for host in ('host2', 'host3'):
            self._add_host_to_aggregate(self.admin_api, tenant_aggregate, host)

        # Restrict the non-admin project to the tenant aggregate.
        self._isolate_aggregate(
            self.admin_api, tenant_aggregate, uuids.user_project)

    def test_cold_migrate_server(self):
        """Creates a server using the non-admin project, then cold migrates
        the server and asserts the server goes to the other host in the
        isolated host aggregate via the AggregateMultiTenancyIsolation filter.
        """
        img = nova.tests.unit.image.fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID
        server_req_body = self._build_server(
            image_uuid=img,
            networks='none')
        server = self.api.post_server({'server': server_req_body})
        server = self._wait_for_state_change(server, 'ACTIVE')
        # Ensure the server ended up in host2 or host3
        original_host = server['OS-EXT-SRV-ATTR:host']
        self.assertNotEqual('host1', original_host)
        # Now cold migrate the server and it should end up in the other host
        # in the same tenant-isolated aggregate.
        self.admin_api.api_post(
            '/servers/%s/action' % server['id'], {'migrate': None})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        # Ensure the server is on the other host in the same aggregate.
        expected_host = 'host3' if original_host == 'host2' else 'host2'
        self.assertEqual(expected_host, server['OS-EXT-SRV-ATTR:host'])

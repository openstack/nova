# Copyright 2011 Justin Santa Barbara
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

"""
Provides common functionality for integrated unit tests
"""

import collections
import random
import six
import string
import time

import os_traits
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import instance_actions
from nova.compute import utils as compute_utils
import nova.conf
from nova import context
from nova.db import api as db
import nova.image.glance
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.unit import cast_as_call
from nova.tests.unit import fake_notifier
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture
from nova import utils


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def generate_random_alphanumeric(length):
    """Creates a random alphanumeric string of specified length."""
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for _x in range(length))


def generate_random_numeric(length):
    """Creates a random numeric string of specified length."""
    return ''.join(random.choice(string.digits)
                   for _x in range(length))


def generate_new_element(items, prefix, numeric=False):
    """Creates a random string with prefix, that is not in 'items' list."""
    while True:
        if numeric:
            candidate = prefix + generate_random_numeric(8)
        else:
            candidate = prefix + generate_random_alphanumeric(8)
        if candidate not in items:
            return candidate
        LOG.debug("Random collision on %s", candidate)


class _IntegratedTestBase(test.TestCase):
    REQUIRES_LOCKING = True
    ADMIN_API = False
    # Override this in subclasses which use the NeutronFixture. New tests
    # should rely on Neutron since nova-network is deprecated. The default
    # value of False here is only temporary while we update the existing
    # functional tests to use Neutron.
    USE_NEUTRON = False

    def setUp(self):
        super(_IntegratedTestBase, self).setUp()

        # TODO(mriedem): Fix the functional tests to work with Neutron.
        self.flags(use_neutron=self.USE_NEUTRON)

        # NOTE(mikal): this is used to stub away privsep helpers
        def fake_noop(*args, **kwargs):
            return None
        self.stub_out('nova.privsep.linux_net.bind_ip', fake_noop)

        self.fake_image_service =\
            nova.tests.unit.image.fake.stub_out_image_service(self)

        self.useFixture(cast_as_call.CastAsCall(self))
        placement = self.useFixture(func_fixtures.PlacementFixture())
        self.placement_api = placement.api

        self._setup_services()

        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

    def _setup_compute_service(self):
        return self.start_service('compute')

    def _setup_scheduler_service(self):
        return self.start_service('scheduler')

    def _setup_services(self):
        # NOTE(danms): Set the global MQ connection to that of our first cell
        # for any cells-ignorant code. Normally this is defaulted in the tests
        # which will result in us not doing the right thing.
        if 'cell1' in self.cell_mappings:
            self.flags(transport_url=self.cell_mappings['cell1'].transport_url)
        self.conductor = self.start_service('conductor')

        if self.USE_NEUTRON:
            self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        else:
            self.network = self.start_service('network',
                                              manager=CONF.network_manager)
        self.scheduler = self._setup_scheduler_service()

        self.compute = self._setup_compute_service()
        self.api_fixture = self.useFixture(
            nova_fixtures.OSAPIFixture(self.api_major_version))

        # if the class needs to run as admin, make the api endpoint
        # the admin, otherwise it's safer to run as non admin user.
        if self.ADMIN_API:
            self.api = self.api_fixture.admin_api
        else:
            self.api = self.api_fixture.api

        if hasattr(self, 'microversion'):
            self.api.microversion = self.microversion

    def get_unused_server_name(self):
        servers = self.api.get_servers()
        server_names = [server['name'] for server in servers]
        return generate_new_element(server_names, 'server')

    def get_unused_flavor_name_id(self):
        flavors = self.api.get_flavors()
        flavor_names = list()
        flavor_ids = list()
        [(flavor_names.append(flavor['name']),
         flavor_ids.append(flavor['id']))
         for flavor in flavors]
        return (generate_new_element(flavor_names, 'flavor'),
                int(generate_new_element(flavor_ids, '', True)))

    def get_invalid_image(self):
        return uuids.fake

    def _build_minimal_create_server_request(self, image_uuid=None):
        server = {}

        # NOTE(takashin): In API version 2.36, image APIs were deprecated.
        # In API version 2.36 or greater, self.api.get_images() returns
        # a 404 error. In that case, 'image_uuid' should be specified.
        server[self._image_ref_parameter] = (image_uuid or
                                             self.api.get_images()[0]['id'])

        # Set a valid flavorId
        flavor = self.api.get_flavors()[0]
        LOG.debug("Using flavor: %s", flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server

    def _create_flavor_body(self, name, ram, vcpus, disk, ephemeral, id, swap,
                            rxtx_factor, is_public):
        return {
            "flavor": {
                "name": name,
                "ram": ram,
                "vcpus": vcpus,
                "disk": disk,
                "OS-FLV-EXT-DATA:ephemeral": ephemeral,
                "id": id,
                "swap": swap,
                "rxtx_factor": rxtx_factor,
                "os-flavor-access:is_public": is_public,
            }
        }

    def _create_flavor(self, memory_mb=2048, vcpu=2, disk=10, ephemeral=10,
                       swap=0, rxtx_factor=1.0, is_public=True,
                       extra_spec=None):
        flv_name, flv_id = self.get_unused_flavor_name_id()
        body = self._create_flavor_body(flv_name, memory_mb, vcpu, disk,
                                        ephemeral, flv_id, swap, rxtx_factor,
                                        is_public)
        self.api_fixture.admin_api.post_flavor(body)
        if extra_spec is not None:
            spec = {"extra_specs": extra_spec}
            self.api_fixture.admin_api.post_extra_spec(flv_id, spec)
        return flv_id

    def _build_server(self, flavor_id, image=None):
        server = {}
        if image is None:
            # TODO(stephenfin): We need to stop relying on this API
            with utils.temporary_mutation(self.api, microversion='2.35'):
                image = self.api.get_images()[0]
            LOG.debug("Image: %s", image)

            # We now have a valid imageId
            server[self._image_ref_parameter] = image['id']
        else:
            server[self._image_ref_parameter] = image

        # Set a valid flavorId
        flavor = self.api.get_flavor(flavor_id)
        LOG.debug("Using flavor: %s", flavor)
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])

        # Set a valid server name
        server_name = self.get_unused_server_name()
        server['name'] = server_name
        return server

    def _check_api_endpoint(self, endpoint, expected_middleware):
        app = self.api_fixture.app().get((None, '/v2'))

        while getattr(app, 'application', False):
            for middleware in expected_middleware:
                if isinstance(app.application, middleware):
                    expected_middleware.remove(middleware)
                    break
            app = app.application

        self.assertEqual([],
                         expected_middleware,
                         ("The expected wsgi middlewares %s are not "
                          "existed") % expected_middleware)


class InstanceHelperMixin(object):
    def _wait_for_server_parameter(self, admin_api, server, expected_params,
                                   max_retries=10):
        retry_count = 0
        while True:
            server = admin_api.get_server(server['id'])
            if all([server[attr] == expected_params[attr]
                    for attr in expected_params]):
                break
            retry_count += 1
            if retry_count == max_retries:
                self.fail('Wait for state change failed, '
                          'expected_params=%s, server=%s' % (
                              expected_params, server))
            time.sleep(0.5)

        return server

    def _wait_for_state_change(self, admin_api, server, expected_status,
                               max_retries=10):
        return self._wait_for_server_parameter(
            admin_api, server, {'status': expected_status}, max_retries)

    def _build_minimal_create_server_request(self, api, name, image_uuid=None,
                                             flavor_id=None, networks=None,
                                             az=None, host=None):
        server = {}

        # We now have a valid imageId
        server['imageRef'] = image_uuid or api.get_images()[0]['id']

        if not flavor_id:
            # Set a valid flavorId
            flavor_id = api.get_flavors()[1]['id']
        server['flavorRef'] = ('http://fake.server/%s' % flavor_id)
        server['name'] = name
        if networks is not None:
            server['networks'] = networks
        if az is not None:
            server['availability_zone'] = az
        # This requires at least microversion 2.74 to work
        if host is not None:
            server['host'] = host
        return server

    def _wait_until_deleted(self, server):
        initially_in_error = server.get('status') == 'ERROR'
        try:
            for i in range(40):
                server = self.api.get_server(server['id'])
                if not initially_in_error and server['status'] == 'ERROR':
                    self.fail('Server went to error state instead of'
                              'disappearing.')
                time.sleep(0.5)

            self.fail('Server failed to delete.')
        except api_client.OpenStackApiNotFoundException:
            return

    def _wait_for_action_fail_completion(
            self, server, expected_action, event_name, api=None):
        """Polls instance action events for the given instance, action and
        action event name until it finds the action event with an error
        result.
        """
        if api is None:
            api = self.api
        return self._wait_for_instance_action_event(
            api, server, expected_action, event_name, event_result='error')

    def _wait_for_instance_action_event(
            self, api, server, action_name, event_name, event_result):
        """Polls the instance action events for the given instance, action,
        event, and event result until it finds the event.
        """
        actions = []
        events = []
        for attempt in range(10):
            actions = api.get_instance_actions(server['id'])
            # The API returns the newest event first
            for action in actions:
                if action['action'] == action_name:
                    events = (
                        api.api_get(
                            '/servers/%s/os-instance-actions/%s' %
                            (server['id'], action['request_id'])
                        ).body['instanceAction']['events'])
                    # Look for the action event being in error state.
                    for event in events:
                        result = event['result']
                        if (event['event'] == event_name and
                                result is not None and
                                result.lower() == event_result.lower()):
                            return event
            # We didn't find the completion event yet, so wait a bit.
            time.sleep(0.5)

        self.fail(
            'Timed out waiting for %s instance action event. Current instance '
            'actions: %s. Events in the last matching action: %s'
            % (event_name, actions, events))

    def _wait_for_migration_status(self, server, expected_statuses):
        """Waits for a migration record with the given statuses to be found
        for the given server, else the test fails. The migration record, if
        found, is returned.
        """
        api = getattr(self, 'admin_api', None)
        if api is None:
            api = self.api

        statuses = [status.lower() for status in expected_statuses]
        for attempt in range(10):
            migrations = api.api_get('/os-migrations').body['migrations']
            for migration in migrations:
                if (migration['instance_uuid'] == server['id'] and
                        migration['status'].lower() in statuses):
                    return migration
            time.sleep(0.5)
        self.fail('Timed out waiting for migration with status "%s" for '
                  'instance: %s' % (expected_statuses, server['id']))

    def _wait_for_log(self, log_line):
        for i in range(10):
            if log_line in self.stdlog.logger.output:
                return
            time.sleep(0.5)

        self.fail('The line "%(log_line)s" did not appear in the log')


class ProviderUsageBaseTestCase(test.TestCase, InstanceHelperMixin):
    """Base test class for functional tests that check provider usage
    and consumer allocations in Placement during various operations.

    Subclasses must define a **compute_driver** attribute for the virt driver
    to use.

    This class sets up standard fixtures and controller services but does not
    start any compute services, that is left to the subclass.
    """

    microversion = 'latest'

    # These must match the capabilities in
    # nova.virt.libvirt.driver.LibvirtDriver.capabilities
    expected_libvirt_driver_capability_traits = set([
        six.u(trait) for trait in [
            os_traits.COMPUTE_DEVICE_TAGGING,
            os_traits.COMPUTE_NET_ATTACH_INTERFACE,
            os_traits.COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG,
            os_traits.COMPUTE_VOLUME_ATTACH_WITH_TAG,
            os_traits.COMPUTE_VOLUME_EXTEND,
            os_traits.COMPUTE_TRUSTED_CERTS,
            os_traits.COMPUTE_IMAGE_TYPE_AKI,
            os_traits.COMPUTE_IMAGE_TYPE_AMI,
            os_traits.COMPUTE_IMAGE_TYPE_ARI,
            os_traits.COMPUTE_IMAGE_TYPE_ISO,
            os_traits.COMPUTE_IMAGE_TYPE_QCOW2,
            os_traits.COMPUTE_IMAGE_TYPE_RAW,
        ]
    ])

    # These must match the capabilities in
    # nova.virt.fake.FakeDriver.capabilities
    expected_fake_driver_capability_traits = set([
        six.u(trait) for trait in [
            os_traits.COMPUTE_IMAGE_TYPE_RAW,
            os_traits.COMPUTE_NET_ATTACH_INTERFACE,
            os_traits.COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG,
            os_traits.COMPUTE_VOLUME_ATTACH_WITH_TAG,
            os_traits.COMPUTE_VOLUME_EXTEND,
            os_traits.COMPUTE_VOLUME_MULTI_ATTACH,
            os_traits.COMPUTE_TRUSTED_CERTS,
        ]
    ])

    def setUp(self):
        self.flags(compute_driver=self.compute_driver)
        super(ProviderUsageBaseTestCase, self).setUp()

        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())
        self.neutron = self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.AllServicesCurrent())

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        placement = self.useFixture(func_fixtures.PlacementFixture())
        self.placement_api = placement.api
        self.api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.admin_api = self.api_fixture.admin_api
        self.admin_api.microversion = self.microversion
        self.api = self.admin_api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.start_service('conductor')
        self.scheduler_service = self.start_service('scheduler')

        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.computes = {}

    def _start_compute(self, host, cell_name=None):
        """Start a nova compute service on the given host

        :param host: the name of the host that will be associated to the
                     compute service.
        :param cell_name: optional name of the cell in which to start the
                          compute service (defaults to cell1)
        :return: the nova compute service object
        """
        compute = self.start_service('compute', host=host, cell=cell_name)
        self.computes[host] = compute
        return compute

    def _get_provider_uuid_by_host(self, host):
        # NOTE(gibi): the compute node id is the same as the compute node
        # provider uuid on that compute
        resp = self.admin_api.api_get(
            'os-hypervisors?hypervisor_hostname_pattern=%s' % host).body
        return resp['hypervisors'][0]['id']

    def _get_provider_usages(self, provider_uuid):
        return self.placement_api.get(
            '/resource_providers/%s/usages' % provider_uuid).body['usages']

    def _get_allocations_by_server_uuid(self, server_uuid):
        return self.placement_api.get(
            '/allocations/%s' % server_uuid).body['allocations']

    def _get_allocations_by_provider_uuid(self, rp_uuid):
        return self.placement_api.get(
            '/resource_providers/%s/allocations' % rp_uuid).body['allocations']

    def _get_all_providers(self):
        return self.placement_api.get(
            '/resource_providers', version='1.14').body['resource_providers']

    def _create_trait(self, trait):
        return self.placement_api.put('/traits/%s' % trait, {}, version='1.6')

    def _delete_trait(self, trait):
        return self.placement_api.delete('/traits/%s' % trait, version='1.6')

    def _get_provider_traits(self, provider_uuid):
        return self.placement_api.get(
            '/resource_providers/%s/traits' % provider_uuid,
            version='1.6').body['traits']

    def _set_provider_traits(self, rp_uuid, traits):
        """This will overwrite any existing traits.

        :param rp_uuid: UUID of the resource provider to update
        :param traits: list of trait strings to set on the provider
        :returns: APIResponse object with the results
        """
        provider = self.placement_api.get(
            '/resource_providers/%s' % rp_uuid).body
        put_traits_req = {
            'resource_provider_generation': provider['generation'],
            'traits': traits
        }
        return self.placement_api.put(
            '/resource_providers/%s/traits' % rp_uuid,
            put_traits_req, version='1.6')

    def _get_all_resource_classes(self):
        dicts = self.placement_api.get(
            '/resource_classes', version='1.2').body['resource_classes']
        return [d['name'] for d in dicts]

    def _get_all_traits(self):
        return self.placement_api.get('/traits', version='1.6').body['traits']

    def _get_provider_inventory(self, rp_uuid):
        return self.placement_api.get(
            '/resource_providers/%s/inventories' % rp_uuid).body['inventories']

    def _get_provider_aggregates(self, rp_uuid):
        return self.placement_api.get(
            '/resource_providers/%s/aggregates' % rp_uuid,
            version='1.1').body['aggregates']

    def _post_resource_provider(self, rp_name):
        return self.placement_api.post(
            url='/resource_providers',
            version='1.20', body={'name': rp_name}).body

    def _set_inventory(self, rp_uuid, inv_body):
        """This will set the inventory for a given resource provider.

        :param rp_uuid: UUID of the resource provider to update
        :param inv_body: inventory to set on the provider
        :returns: APIResponse object with the results
        """
        return self.placement_api.post(
            url= ('/resource_providers/%s/inventories' % rp_uuid),
            version='1.15', body=inv_body).body

    def _update_inventory(self, rp_uuid, inv_body):
        """This will update the inventory for a given resource provider.

        :param rp_uuid: UUID of the resource provider to update
        :param inv_body: inventory to set on the provider
        :returns: APIResponse object with the results
        """
        return self.placement_api.put(
            url= ('/resource_providers/%s/inventories' % rp_uuid),
            body=inv_body).body

    def _get_resource_provider_by_uuid(self, rp_uuid):
        return self.placement_api.get(
            '/resource_providers/%s' % rp_uuid, version='1.15').body

    def _set_aggregate(self, rp_uuid, agg_id):
        provider = self.placement_api.get(
            '/resource_providers/%s' % rp_uuid).body
        post_agg_req = {"aggregates": [agg_id],
                        "resource_provider_generation": provider['generation']}
        return self.placement_api.put(
            '/resource_providers/%s/aggregates' % rp_uuid, version='1.19',
            body=post_agg_req).body

    def _get_all_rp_uuids_in_a_tree(self, in_tree_rp_uuid):
        rps = self.placement_api.get(
            '/resource_providers?in_tree=%s' % in_tree_rp_uuid,
            version='1.20').body['resource_providers']
        return [rp['uuid'] for rp in rps]

    def assertRequestMatchesUsage(self, requested_resources, root_rp_uuid):
        # It matches the usages of the whole tree against the request
        rp_uuids = self._get_all_rp_uuids_in_a_tree(root_rp_uuid)
        # NOTE(gibi): flattening the placement usages means we cannot
        # verify the structure here. However I don't see any way to define this
        # function for nested and non-nested trees in a generic way.
        total_usage = collections.defaultdict(int)
        for rp in rp_uuids:
            usage = self._get_provider_usages(rp)
            for rc, amount in usage.items():
                total_usage[rc] += amount
        # Cannot simply do an assertEqual(expected, actual) as usages always
        # contain every RC even if the usage is 0 and the flavor could also
        # contain explicit 0 request for some resources.
        # So if the flavor contains an explicit 0 resource request (e.g. in
        # case of ironic resources:VCPU=0) then this code needs to assert that
        # such resource has 0 usage in the tree. In the other hand if the usage
        # contains 0 value for some resources that the flavor does not request
        # then that is totally fine.
        for rc, value in requested_resources.items():
            self.assertIn(
                rc, total_usage,
                'The requested resource class not found in the total_usage of '
                'the RP tree')
            self.assertEqual(
                value,
                total_usage[rc],
                'The requested resource amount does not match with the total '
                'resource usage of the RP tree')
        for rc, value in total_usage.items():
            if value != 0:
                self.assertEqual(
                    requested_resources[rc],
                    value,
                    'The requested resource amount does not match with the '
                    'total resource usage of the RP tree')

    def assertFlavorMatchesUsage(self, root_rp_uuid, *flavors):
        resources = collections.defaultdict(int)
        for flavor in flavors:
            res = self._resources_from_flavor(flavor)
            for rc, value in res.items():
                resources[rc] += value
        self.assertRequestMatchesUsage(resources, root_rp_uuid)

    def _resources_from_flavor(self, flavor):
        resources = collections.defaultdict(int)
        resources['VCPU'] = flavor['vcpus']
        resources['MEMORY_MB'] = flavor['ram']
        resources['DISK_GB'] = flavor['disk']
        for key, value in flavor['extra_specs'].items():
            if key.startswith('resources'):
                resources[key.split(':')[1]] += value
        return resources

    def assertFlavorMatchesAllocation(self, flavor, consumer_uuid,
                                      root_rp_uuid):
        # NOTE(gibi): This function does not handle sharing RPs today.
        expected_rps = self._get_all_rp_uuids_in_a_tree(root_rp_uuid)
        allocations = self._get_allocations_by_server_uuid(consumer_uuid)
        # NOTE(gibi): flattening the placement allocation means we cannot
        # verify the structure here. However I don't see any way to define this
        # function for nested and non-nested trees in a generic way.
        total_allocation = collections.defaultdict(int)
        for rp, alloc in allocations.items():
            self.assertIn(rp, expected_rps, 'Unexpected, out of tree RP in the'
                                            ' allocation')
            for rc, value in alloc['resources'].items():
                total_allocation[rc] += value

        self.assertEqual(
            self._resources_from_flavor(flavor),
            total_allocation,
            'The resources requested in the flavor does not match with total '
            'allocation in the RP tree')

    def get_migration_uuid_for_instance(self, instance_uuid):
        # NOTE(danms): This is too much introspection for a test like this, but
        # we can't see the migration uuid from the API, so we just encapsulate
        # the peek behind the curtains here to keep it out of the tests.
        # TODO(danms): Get the migration uuid from the API once it is exposed
        ctxt = context.get_admin_context()
        migrations = db.migration_get_all_by_filters(
            ctxt, {'instance_uuid': instance_uuid})
        self.assertEqual(1, len(migrations),
                         'Test expected a single migration, '
                         'but found %i' % len(migrations))
        return migrations[0].uuid

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
        self.assertFlavorMatchesUsage(source_rp_uuid, flavor)

        # Check that the other providers has no usage
        for rp_uuid in [self._get_provider_uuid_by_host(hostname)
                        for hostname in self.computes.keys()
                        if hostname != source_hostname]:
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, rp_uuid)

        # Check that the server only allocates resource from the host it is
        # booted on
        self.assertFlavorMatchesAllocation(flavor, server['id'],
                                           source_rp_uuid)
        self._run_periodics()

        # After running the periodics but before we start any other operation,
        # we should have exactly the same allocation/usage information as
        # before running the periodics

        # Check usages on the selected host after boot
        self.assertFlavorMatchesUsage(source_rp_uuid, flavor)

        # Check that the server only allocates resource from the host it is
        # booted on
        self.assertFlavorMatchesAllocation(flavor, server['id'],
                                           source_rp_uuid)

        # Check that the other providers has no usage
        for rp_uuid in [self._get_provider_uuid_by_host(hostname)
                        for hostname in self.computes.keys()
                        if hostname != source_hostname]:
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, rp_uuid)
        return server

    def _delete_and_check_allocations(self, server):
        """Delete the instance and asserts that the allocations are cleaned

        If the server was moved (resized or live migrated), also checks that
        migration-based allocations are also cleaned up.

        :param server: The API representation of the instance to be deleted
        """

        # First check to see if there is a related migration record so we can
        # assert its allocations (if any) are not leaked.
        with utils.temporary_mutation(self.admin_api, microversion='2.59'):
            migrations = self.admin_api.api_get(
                '/os-migrations?instance_uuid=%s' %
                server['id']).body['migrations']
        if migrations:
            # If there is more than one migration, they are sorted by
            # created_at in descending order so we'll get the last one
            # which is probably what we'd always want anyway.
            migration_uuid = migrations[0]['uuid']
        else:
            migration_uuid = None

        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        # NOTE(gibi): The resource allocation is deleted after the instance is
        # destroyed in the db so wait_until_deleted might return before the
        # the resource are deleted in placement. So we need to wait for the
        # instance.delete.end notification as that is emitted after the
        # resources are freed.

        fake_notifier.wait_for_versioned_notifications('instance.delete.end')

        for rp_uuid in [self._get_provider_uuid_by_host(hostname)
                        for hostname in self.computes.keys()]:
            self.assertRequestMatchesUsage({'VCPU': 0,
                                            'MEMORY_MB': 0,
                                            'DISK_GB': 0}, rp_uuid)

        # and no allocations for the deleted server
        allocations = self._get_allocations_by_server_uuid(server['id'])
        self.assertEqual(0, len(allocations))

        if migration_uuid:
            # and no allocations for the delete migration
            allocations = self._get_allocations_by_server_uuid(migration_uuid)
            self.assertEqual(0, len(allocations))

    def _run_periodics(self):
        """Run the update_available_resource task on every compute manager

        This runs periodics on the computes in an undefined order; some child
        class redefined this function to force a specific order.
        """

        ctx = context.get_admin_context()
        for host, compute in self.computes.items():
            LOG.info('Running periodic for compute (%s)', host)
            # Make sure the context is targeted to the proper cell database
            # for multi-cell tests.
            with context.target_cell(
                    ctx, self.host_mappings[host].cell_mapping) as cctxt:
                compute.manager.update_available_resource(cctxt)
        LOG.info('Finished with periodics')

    def _move_and_check_allocations(self, server, request, old_flavor,
                                    new_flavor, source_rp_uuid, dest_rp_uuid):
        self.api.post_server_action(server['id'], request)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        def _check_allocation():
            self.assertFlavorMatchesUsage(source_rp_uuid, old_flavor)
            self.assertFlavorMatchesUsage(dest_rp_uuid, new_flavor)

            # The instance should own the new_flavor allocation against the
            # destination host created by the scheduler
            self.assertFlavorMatchesAllocation(new_flavor, server['id'],
                                               dest_rp_uuid)

            # The migration should own the old_flavor allocation against the
            # source host created by conductor
            migration_uuid = self.get_migration_uuid_for_instance(server['id'])
            self.assertFlavorMatchesAllocation(old_flavor, migration_uuid,
                                               source_rp_uuid)

        # OK, so the move operation has run, but we have not yet confirmed or
        # reverted the move operation. Before we run periodics, make sure
        # that we have allocations/usages on BOTH the source and the
        # destination hosts.
        _check_allocation()
        self._run_periodics()
        _check_allocation()

        # Make sure the RequestSpec.flavor matches the new_flavor.
        ctxt = context.get_admin_context()
        reqspec = objects.RequestSpec.get_by_instance_uuid(ctxt, server['id'])
        self.assertEqual(new_flavor['id'], reqspec.flavor.flavorid)

    def _migrate_and_check_allocations(self, server, flavor, source_rp_uuid,
                                       dest_rp_uuid):
        request = {
            'migrate': None
        }
        self._move_and_check_allocations(
            server, request=request, old_flavor=flavor, new_flavor=flavor,
            source_rp_uuid=source_rp_uuid, dest_rp_uuid=dest_rp_uuid)

    def _resize_and_check_allocations(self, server, old_flavor, new_flavor,
                                      source_rp_uuid, dest_rp_uuid):
        request = {
            'resize': {
                'flavorRef': new_flavor['id']
            }
        }
        self._move_and_check_allocations(
            server, request=request, old_flavor=old_flavor,
            new_flavor=new_flavor, source_rp_uuid=source_rp_uuid,
            dest_rp_uuid=dest_rp_uuid)

    def _resize_to_same_host_and_check_allocations(self, server, old_flavor,
                                                   new_flavor, rp_uuid):
        # Resize the server to the same host and check usages in VERIFY_RESIZE
        # state
        self.flags(allow_resize_to_same_host=True)
        resize_req = {
            'resize': {
                'flavorRef': new_flavor['id']
            }
        }
        self.api.post_server_action(server['id'], resize_req)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        self.assertFlavorMatchesUsage(rp_uuid, old_flavor, new_flavor)

        # The instance should hold a new_flavor allocation
        self.assertFlavorMatchesAllocation(new_flavor, server['id'],
                                           rp_uuid)

        # The migration should hold an old_flavor allocation
        migration_uuid = self.get_migration_uuid_for_instance(server['id'])
        self.assertFlavorMatchesAllocation(old_flavor, migration_uuid,
                                           rp_uuid)

        # We've resized to the same host and have doubled allocations for both
        # the old and new flavor on the same host. Run the periodic on the
        # compute to see if it tramples on what the scheduler did.
        self._run_periodics()

        # In terms of usage, it's still double on the host because the instance
        # and the migration each hold an allocation for the new and old
        # flavors respectively.
        self.assertFlavorMatchesUsage(rp_uuid, old_flavor, new_flavor)

        # The instance should hold a new_flavor allocation
        self.assertFlavorMatchesAllocation(new_flavor, server['id'],
                                           rp_uuid)

        # The migration should hold an old_flavor allocation
        self.assertFlavorMatchesAllocation(old_flavor, migration_uuid,
                                           rp_uuid)

    def _check_allocation_during_evacuate(
            self, flavor, server_uuid, source_root_rp_uuid, dest_root_rp_uuid):

        allocations = self._get_allocations_by_server_uuid(server_uuid)
        self.assertEqual(2, len(allocations))
        self.assertFlavorMatchesUsage(source_root_rp_uuid, flavor)
        self.assertFlavorMatchesUsage(dest_root_rp_uuid, flavor)

    def assert_hypervisor_usage(self, compute_node_uuid, flavor,
                                volume_backed):
        """Asserts the given hypervisor's resource usage matches the
        given flavor (assumes a single instance on the hypervisor).

        :param compute_node_uuid: UUID of the ComputeNode to check.
        :param flavor: "flavor" entry dict from from GET /flavors/{flavor_id}
        :param volume_backed: True if the flavor is used with a volume-backed
            server, False otherwise.
        """
        # GET /os-hypervisors/{uuid} requires at least 2.53
        with utils.temporary_mutation(self.admin_api, microversion='2.53'):
            hypervisor = self.admin_api.api_get(
                '/os-hypervisors/%s' % compute_node_uuid).body['hypervisor']
        if volume_backed:
            expected_disk_usage = 0
        else:
            expected_disk_usage = flavor['disk']
        # Account for reserved_host_disk_mb.
        expected_disk_usage += compute_utils.convert_mb_to_ceil_gb(
            CONF.reserved_host_disk_mb)
        self.assertEqual(expected_disk_usage, hypervisor['local_gb_used'])
        # Account for reserved_host_memory_mb.
        expected_ram_usage = CONF.reserved_host_memory_mb + flavor['ram']
        self.assertEqual(expected_ram_usage, hypervisor['memory_mb_used'])
        # Account for reserved_host_cpus.
        expected_vcpu_usage = CONF.reserved_host_cpus + flavor['vcpus']
        self.assertEqual(expected_vcpu_usage, hypervisor['vcpus_used'])

    def _confirm_resize(self, server):
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        self._wait_for_instance_action_event(
            self.api, server, instance_actions.CONFIRM_RESIZE,
            'compute_confirm_resize', 'success')
        return server

    def _revert_resize(self, server):
        self.api.post_server_action(server['id'], {'revertResize': None})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        self._wait_for_migration_status(server, ['reverted'])
        # Note that the migration status is changed to "reverted" in the
        # dest host revert_resize method but the allocations are cleaned up
        # in the source host finish_revert_resize method so we need to wait
        # for the finish_revert_resize method to complete.
        fake_notifier.wait_for_versioned_notifications(
            'instance.resize_revert.end')
        return server

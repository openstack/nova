# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture
from nova.virt import fake


class TestEvacuationWithSourceReturningDuringRebuild(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Assert the behaviour of evacuating instances when the src returns early.

    This test asserts that evacuating instances end up in an ACTIVE state on
    the destination even when the source host comes back online during an
    evacuation while the migration record is in a pre-migrating state.
    """

    def setUp(self):
        super(TestEvacuationWithSourceReturningDuringRebuild, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())

        # The NeutronFixture is needed to stub out validate_networks in API.
        self.useFixture(nova_fixtures.NeutronFixture(self))

        # This stubs out the network allocation in compute.
        fake_network.set_stub_network_methods(self)

        # We need the computes reporting into placement for the filter
        # scheduler to pick a host.
        self.useFixture(nova_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        # 2.11 is needed for force_down
        # 2.14 is needed for evacuate without onSharedStorage flag
        self.api.microversion = '2.14'

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        # Start two computes
        self.computes = {}

        fake.set_nodes(['host1'])
        self.addCleanup(fake.restore_nodes)
        self.computes['host1'] = self.start_service('compute', host='host1')

        fake.set_nodes(['host2'])
        self.addCleanup(fake.restore_nodes)
        self.computes['host2'] = self.start_service('compute', host='host2')

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

        self.addCleanup(fake_notifier.reset)

        # Stub out rebuild with a slower method allowing the src compute to be
        # restarted once the migration hits pre-migrating after claiming
        # resources on the dest.
        manager_class = nova.compute.manager.ComputeManager
        original_rebuild = manager_class._do_rebuild_instance

        def start_src_rebuild(self_, context, instance, *args, **kwargs):
            server = self.api.get_server(instance.uuid)
            # Start the src compute once the migration is pre-migrating.
            self._wait_for_migration_status(server, ['pre-migrating'])
            self.computes.get(self.source_compute).start()
            original_rebuild(self_, context, instance, *args, **kwargs)

        self.stub_out('nova.compute.manager.ComputeManager.'
                      '_do_rebuild_instance', start_src_rebuild)

    def test_evacuation_with_source_compute_returning_during_rebuild(self):

        # Launch an instance
        server_request = {'name': 'server',
                          'imageRef': self.image_id,
                          'flavorRef': self.flavor_id}
        server_response = self.api.post_server({'server': server_request})
        server = self._wait_for_state_change(self.api, server_response,
                                             'ACTIVE')

        # Record where the instance is running before forcing the service down
        self.source_compute = server['OS-EXT-SRV-ATTR:host']
        self.computes.get(self.source_compute).stop()
        self.api.force_down_service(self.source_compute, 'nova-compute', True)

        # Start evacuating the instance from the source_host
        self.api.post_server_action(server['id'], {'evacuate': {}})

        # Wait for the instance to go into an ACTIVE state
        self._wait_for_state_change(self.api, server, 'ACTIVE')
        server = self.api.get_server(server['id'])
        host = server['OS-EXT-SRV-ATTR:host']
        migrations = self.api.get_migrations()

        # Assert that we have a single `done` migration record after the evac
        self.assertEqual(1, len(migrations))
        self.assertEqual('done', migrations[0]['status'])

        # Assert that the instance is now on the dest
        self.assertNotEqual(self.source_compute, host)

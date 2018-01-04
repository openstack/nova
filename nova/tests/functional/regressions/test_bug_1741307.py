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
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture
from nova.virt import fake


class TestResizeWithCachingScheduler(test.TestCase,
                                     integrated_helpers.InstanceHelperMixin):
    """Regression tests for bug #1741307

    The CachingScheduler does not use Placement to make claims (allocations)
    against compute nodes during scheduling like the FilterScheduler does.
    During a cold migrate / resize, the FilterScheduler will "double up" the
    instance allocations so the instance has resource allocations made against
    both the source node and the chosen destination node. Conductor will then
    attempt to "swap" the source node allocation to the migration record. If
    using the CachingScheduler, there are no allocations for the instance on
    the source node and conductor fails. Note that if the compute running the
    instance was running Ocata code or older, then the compute itself would
    create the allocations in Placement via the ResourceTracker, but once all
    computes are upgraded to Pike or newer, the compute no longer creates
    allocations in Placement because it assumes the scheduler is doing that,
    which is not the case with the CachingScheduler.

    This is a regression test to show the failure before it's fixed and then
    can be used to confirm the fix.
    """

    microversion = 'latest'

    def setUp(self):
        super(TestResizeWithCachingScheduler, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api
        self.api.microversion = self.microversion

        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.start_service('conductor')
        # Configure the CachingScheduler.
        self.flags(driver='caching_scheduler', group='scheduler')
        self.start_service('scheduler')

        # Create two compute nodes/services.
        for host in ('host1', 'host2'):
            fake.set_nodes([host])
            self.addCleanup(fake.restore_nodes)
            self.start_service('compute', host=host)

        flavors = self.api.get_flavors()
        self.old_flavor = flavors[0]
        self.new_flavor = flavors[1]

    def test_resize(self):
        # Create our server without networking just to keep things simple.
        server_req = self._build_minimal_create_server_request(
            self.api, 'test-resize', flavor_id=self.old_flavor['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')

        original_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host1' if original_host == 'host2' else 'host2'

        # Issue the resize request.
        post = {
            'resize': {
                'flavorRef': self.new_flavor['id']
            }
        }
        self.api.post_server_action(server['id'], post)

        # Poll the server until the resize is done.
        server = self._wait_for_state_change(
            self.api, server, 'VERIFY_RESIZE')
        # Assert that the server was migrated to the other host.
        self.assertEqual(target_host, server['OS-EXT-SRV-ATTR:host'])
        # Confirm the resize.
        post = {'confirmResize': None}
        self.api.post_server_action(server['id'], post,
                                    check_response_status=[204])

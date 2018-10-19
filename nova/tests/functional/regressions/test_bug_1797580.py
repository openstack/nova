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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture
from nova.virt import fake


class ColdMigrateTargetHostThenLiveMigrateTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1797580 introduced in Queens.

    Microversion 2.56 allows cold migrating to a specified target host. The
    compute API sets the requested destination on the request spec with the
    specified target host and then conductor sends that request spec to the
    scheduler to validate the host. Conductor later persists the changes to
    the request spec because it's the resize flow and the flavor could change
    (even though in this case it won't since it's a cold migrate). After
    confirming the resize, if the server is live migrated it will fail during
    scheduling because of the persisted RequestSpec.requested_destination
    from the cold migration, and you can't live migrate to the same host on
    which the instance is currently running.

    This test reproduces the regression and will validate the fix.
    """

    def setUp(self):
        super(ColdMigrateTargetHostThenLiveMigrateTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        # The admin API is used to get the server details to verify the
        # host on which the server was built and cold/live migrate it.
        self.admin_api = api_fixture.admin_api
        self.api = api_fixture.api
        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.admin_api.microversion = 'latest'
        self.api.microversion = 'latest'

        image_fake.stub_out_image_service(self)
        self.addCleanup(image_fake.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        for host in ('host1', 'host2'):
            fake.set_nodes([host])
            self.addCleanup(fake.restore_nodes)
            self.start_service('compute', host=host)

    def test_cold_migrate_target_host_then_live_migrate(self):
        # Create a server, it doesn't matter on which host it builds.
        server = self._build_minimal_create_server_request(
            self.api, 'test_cold_migrate_target_host_then_live_migrate',
            image_uuid=image_fake.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
            networks='none')
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        original_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host1' if original_host == 'host2' else 'host2'

        # Cold migrate the server to the specific target host.
        migrate_req = {'migrate': {'host': target_host}}
        self.admin_api.post_server_action(server['id'], migrate_req)
        server = self._wait_for_state_change(
            self.admin_api, server, 'VERIFY_RESIZE')

        # Confirm the resize so the server stays on the target host.
        confim_req = {'confirmResize': None}
        self.admin_api.post_server_action(server['id'], confim_req)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        # Attempt to live migrate the server but don't specify a host so the
        # scheduler has to pick one.
        live_migrate_req = {
            'os-migrateLive': {'host': None, 'block_migration': 'auto'}}
        self.admin_api.post_server_action(server['id'], live_migrate_req)
        server = self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # The live migration should have been successful and the server is now
        # back on the original host.
        self.assertEqual(original_host, server['OS-EXT-SRV-ATTR:host'])

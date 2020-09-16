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

import time

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
from nova.tests.unit import policy_fixture


class TestLiveMigrateOneOfConcurrentlyCreatedInstances(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression tests for bug #1718455

    When creating multiple instances at the same time, the RequestSpec record
    is persisting the number of concurrent instances.
    When moving one of those instances, the scheduler should not include
    num_instances > 1 in the request spec.
    It was partially fixed by bug #1708961 but we forgot to amend
    some place in the scheduler so that the right number of hosts was returned
    to the scheduler method calling both the Placement API and filters/weighers
    but we were verifying that returned size of hosts against a wrong number,
    which is the number of instances created concurrently.

    That test will create 2 concurrent instances and verify that when
    live-migrating one of them, we end up with a correct move operation.
    """

    microversion = 'latest'

    def setUp(self):
        super(TestLiveMigrateOneOfConcurrentlyCreatedInstances, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api
        self.api.microversion = self.microversion

        self.start_service('conductor')
        self.start_service('scheduler')

        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

        fake_network.set_stub_network_methods(self)

    def _boot_servers(self, num_servers=1):
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        server_req.update({'min_count': str(num_servers),
                           'return_reservation_id': 'True'})
        response = self.api.post_server({'server': server_req})
        reservation_id = response['reservation_id']
        # lookup servers created by the multi-create request.
        servers = self.api.get_servers(detail=True,
                search_opts={'reservation_id': reservation_id})
        for idx, server in enumerate(servers):
            servers[idx] = self._wait_for_state_change(server,
                                                       'ACTIVE')
        return servers

    def _wait_for_migration_status(self, server, expected_status):
        """Waits for a migration record with the given status to be found
        for the given server, else the test fails. The migration record, if
        found, is returned.
        """
        for attempt in range(10):
            migrations = self.api.get_migrations()
            for migration in migrations:
                if (migration['instance_uuid'] == server['id'] and
                        migration['status'].lower() ==
                        expected_status.lower()):
                    return migration
            time.sleep(0.5)
        self.fail('Timed out waiting for migration with status "%s" for '
                  'instance: %s. Current instance migrations: %s' %
                  (expected_status, server['id'], migrations))

    def test_live_migrate_one_multi_created_instance(self):
        # Boot two servers in a multi-create request
        servers = self._boot_servers(num_servers=2)

        # Take the first instance and verify which host the instance is there
        server = servers[0]
        original_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host1' if original_host == 'host2' else 'host2'

        # Initiate live migration for that instance by targeting the other host
        post = {'os-migrateLive': {'block_migration': 'auto',
                                   'host': target_host}}

        # NOTE(sbauza): Since API version 2.34, live-migration pre-checks are
        # now done asynchronously so even if we hit a NoValidHost exception by
        # the conductor, the API call will always succeed with a HTTP202
        # response code. In order to verify whether the migration succeeded,
        # we need to lookup the migrations API.
        self.api.post_server_action(server['id'], post)

        # Poll the migration until it is done.
        migration = self._wait_for_migration_status(server, 'completed')

        self.assertEqual('live-migration', migration['migration_type'])
        self.assertEqual(original_host, migration['source_compute'])

        # Verify that the migration succeeded as the instance is now on the
        # destination node.
        server = self.api.get_server(server['id'])
        self.assertEqual(target_host, server['OS-EXT-SRV-ATTR:host'])

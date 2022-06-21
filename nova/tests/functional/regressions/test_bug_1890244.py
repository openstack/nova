# Copyright 2017 Ericsson
#
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

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class IgnoreDeletedServerGroupsTest(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Regression test for bug 1890244

    If instance are created as member of server groups it
    should be possibel to evacuate them if the server groups are
    deleted prior to the host failure.
    """

    def setUp(self):
        super().setUp()
        # Stub out external dependencies.
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        # Start nova controller services.
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        self.start_service('conductor')
        # Use a custom weigher to make sure that we have a predictable
        # scheduling sort order.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        self.start_service('scheduler')
        # Start two computes, one where the server will be created and another
        # where we'll evacuate it to.
        self.src = self._start_compute('host1')
        self.dest = self._start_compute('host2')
        self.notifier = self.useFixture(
            nova_fixtures.NotificationFixture(self)
        )

    def test_evacuate_after_group_delete(self):
        # Create an anti-affinity group for the server.
        body = {
            'server_group': {
                'name': 'test-group',
                'policies': ['anti-affinity']
            }
        }
        group_id = self.api.api_post(
            '/os-server-groups', body).body['server_group']['id']

        # Create a server in the group which should land on host1 due to our
        # custom weigher.
        body = {'server': self._build_server()}
        body['os:scheduler_hints'] = {'group': group_id}
        server = self.api.post_server(body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        # Down the source compute to enable the evacuation
        self.api.microversion = '2.11'     # Cap for the force-down call.
        self.api.force_down_service('host1', 'nova-compute', True)
        self.api.microversion = 'latest'
        self.src.stop()

        # assert the server currently has a server group
        reqspec = objects.RequestSpec.get_by_instance_uuid(
            context.get_admin_context(), server['id'])
        self.assertIsNotNone(reqspec.instance_group)
        self.assertIn('group', reqspec.scheduler_hints)
        # then delete it so that we need to clean it up on evac
        self.api.api_delete(f'/os-server-groups/{group_id}')

        # Initiate evacuation
        server = self._evacuate_server(
            server, expected_host='host2', expected_migration_status='done'
        )
        reqspec = objects.RequestSpec.get_by_instance_uuid(
            context.get_admin_context(), server['id'])
        self.assertIsNone(reqspec.instance_group)
        self.assertNotIn('group', reqspec.scheduler_hints)

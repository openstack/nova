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
from unittest import mock

from nova import context
from nova.objects import compute_node
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class UnshelveUpdateAvailableResourcesPeriodicRace(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    def setUp(self):
        super(UnshelveUpdateAvailableResourcesPeriodicRace, self).setUp()

        placement = func_fixtures.PlacementFixture()
        self.useFixture(placement)
        self.placement = placement.api
        self.neutron = nova_fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.useFixture(nova_fixtures.GlanceFixture(self))
        # Start nova services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.api.microversion = 'latest'
        self.notifier = self.useFixture(
            nova_fixtures.NotificationFixture(self))

        self.start_service('conductor')
        self.start_service('scheduler')

    def test_unshelve_spawning_update_available_resources(self):
        compute = self._start_compute('compute1')

        server = self._create_server(
            networks=[{'port': self.neutron.port_1['id']}])

        node = compute_node.ComputeNode.get_by_nodename(
            context.get_admin_context(), 'compute1')
        self.assertEqual(1, node.vcpus_used)

        # with default config shelve means immediate offload as well
        req = {
            'shelve': {}
        }
        self.api.post_server_action(server['id'], req)
        self._wait_for_server_parameter(
            server, {'status': 'SHELVED_OFFLOADED',
                     'OS-EXT-SRV-ATTR:host': None})

        node = compute_node.ComputeNode.get_by_nodename(
            context.get_admin_context(), 'compute1')
        self.assertEqual(0, node.vcpus_used)

        def fake_spawn(*args, **kwargs):
            self._run_periodics()

        with mock.patch.object(
                compute.driver, 'spawn', side_effect=fake_spawn):
            req = {'unshelve': None}
            self.api.post_server_action(server['id'], req)
            self.notifier.wait_for_versioned_notifications(
                'instance.unshelve.start')
            self._wait_for_server_parameter(
                server,
                {
                    'status': 'ACTIVE',
                    'OS-EXT-STS:task_state': None,
                    'OS-EXT-SRV-ATTR:host': 'compute1',
                })

        node = compute_node.ComputeNode.get_by_nodename(
            context.get_admin_context(), 'compute1')
        # After the fix, the instance should have resources claimed
        self.assertEqual(1, node.vcpus_used)

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

from nova.compute import instance_actions
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture
from nova import utils


class TestInstanceActionBuryInCell0(test.TestCase,
                                    integrated_helpers.InstanceHelperMixin):
    """Regression test for bug 1852458 where the "create" instance action
    event was not being created for instances buried in cell0 starting in
    Ocata.
    """
    def setUp(self):
        super(TestInstanceActionBuryInCell0, self).setUp()
        # Setup common fixtures.
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        policy = self.useFixture(policy_fixture.RealPolicyFixture())
        # Allow non-admins to see instance action events.
        policy.set_rules({
            'os_compute_api:os-instance-actions:events': 'rule:admin_or_owner'
        }, overwrite=False)
        # Setup controller services.
        self.start_service('conductor')
        self.start_service('scheduler')
        self.api = self.useFixture(
            nova_fixtures.OSAPIFixture(api_version='v2.1')).api

    def test_bury_in_cell0_instance_create_action(self):
        """Tests creating a server which will fail scheduling because there is
        no compute service and result in the instance being created (buried)
        in cell0.
        """
        server = self._build_server(networks='none')
        # Use microversion 2.37 to create a server without any networking.
        with utils.temporary_mutation(self.api, microversion='2.37'):
            server = self.api.post_server({'server': server})
        # The server should go to ERROR status and have a NoValidHost fault.
        server = self._wait_for_state_change(server, 'ERROR')
        self.assertIn('fault', server)
        self.assertIn('No valid host', server['fault']['message'])
        self.assertEqual('', server['hostId'])
        # Assert the "create" instance action exists and is failed.
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual(1, len(actions), actions)
        action = actions[0]
        self.assertEqual(instance_actions.CREATE, action['action'])
        self.assertEqual('Error', action['message'])
        # Get the events. There should be one with an Error result.
        action = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' %
            (server['id'], action['request_id'])).body['instanceAction']
        events = action['events']
        self.assertEqual(1, len(events), events)
        event = events[0]
        self.assertEqual('conductor_schedule_and_build_instances',
                         event['event'])
        self.assertEqual('Error', event['result'])
        # Normally non-admins cannot see the event traceback but we enabled
        # that via policy in setUp so assert something was recorded.
        self.assertIn('select_destinations', event['traceback'])

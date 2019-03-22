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

from nova.compute import instance_actions
from nova.compute import power_state
from nova.compute import vm_states
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class ServerExternalEventsTestV276(
        integrated_helpers.ProviderUsageBaseTestCase):
    microversion = '2.76'
    compute_driver = 'fake.PowerUpdateFakeDriver'

    def setUp(self):
        super(ServerExternalEventsTestV276, self).setUp()
        self.compute = self.start_service('compute', host='compute')

        flavors = self.api.get_flavors()
        server_req = self._build_minimal_create_server_request(
            self.api, "some-server", flavor_id=flavors[0]["id"],
            image_uuid="155d900f-4e14-4e4c-a73d-069cbf4541e6",
            networks='none')
        created_server = self.api.post_server({'server': server_req})
        self.server = self._wait_for_state_change(
            self.api, created_server, 'ACTIVE')
        self.power_off = {'name': 'power-update',
                          'tag': 'POWER_OFF',
                          'server_uuid': self.server["id"]}
        self.power_on = {'name': 'power-update',
                         'tag': 'POWER_ON',
                         'server_uuid': self.server["id"]}

    def test_server_power_update(self):
        # This test checks the functionality of handling the "power-update"
        # external events.
        self.assertEqual(
            power_state.RUNNING, self.server['OS-EXT-STS:power_state'])
        self.api.create_server_external_events(events=[self.power_off])
        expected_params = {'OS-EXT-STS:task_state': None,
                           'OS-EXT-STS:vm_state': vm_states.STOPPED,
                           'OS-EXT-STS:power_state': power_state.SHUTDOWN}
        server = self._wait_for_server_parameter(self.api, self.server,
                                                 expected_params)
        msg = ' with target power state POWER_OFF.'
        self.assertIn(msg, self.stdlog.logger.output)
        # Test if this is logged in the instance action list.
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual(2, len(actions))
        acts = {action['action']: action for action in actions}
        self.assertEqual(['create', 'stop'], sorted(acts))
        stop_action = acts[instance_actions.STOP]
        detail = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' % (
                server['id'], stop_action['request_id'])
        ).body['instanceAction']
        events_by_name = {event['event']: event for event in detail['events']}
        self.assertEqual(1, len(detail['events']), detail)
        self.assertIn('compute_power_update', events_by_name)
        self.assertEqual('Success', detail['events'][0]['result'])
        # Test if notifications were emitted.
        fake_notifier.wait_for_versioned_notifications(
            'instance.power_off.start')
        fake_notifier.wait_for_versioned_notifications(
            'instance.power_off.end')

        # Checking POWER_ON
        self.api.create_server_external_events(events=[self.power_on])
        expected_params = {'OS-EXT-STS:task_state': None,
                           'OS-EXT-STS:vm_state': vm_states.ACTIVE,
                           'OS-EXT-STS:power_state': power_state.RUNNING}
        server = self._wait_for_server_parameter(self.api, self.server,
                                                 expected_params)
        msg = ' with target power state POWER_ON.'
        self.assertIn(msg, self.stdlog.logger.output)
        # Test if this is logged in the instance action list.
        actions = self.api.get_instance_actions(server['id'])
        self.assertEqual(3, len(actions))
        acts = {action['action']: action for action in actions}
        self.assertEqual(['create', 'start', 'stop'], sorted(acts))
        start_action = acts[instance_actions.START]
        detail = self.api.api_get(
            '/servers/%s/os-instance-actions/%s' % (
                server['id'], start_action['request_id'])
        ).body['instanceAction']
        events_by_name = {event['event']: event for event in detail['events']}
        self.assertEqual(1, len(detail['events']), detail)
        self.assertIn('compute_power_update', events_by_name)
        self.assertEqual('Success', detail['events'][0]['result'])
        # Test if notifications were emitted.
        fake_notifier.wait_for_versioned_notifications(
            'instance.power_on.start')
        fake_notifier.wait_for_versioned_notifications(
            'instance.power_on.end')

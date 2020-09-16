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

import time

from oslo_log import log as logging

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier
from nova.tests.unit import policy_fixture


LOG = logging.getLogger(__name__)


class FailedEvacuateStateTests(test.TestCase,
                               integrated_helpers.InstanceHelperMixin):
    """Regression Tests for bug #1713783

    When evacuation fails with NoValidHost, the migration status remains
    'accepted' instead of 'error'. This causes problem in case the compute
    service starts up again and looks for migrations with status 'accepted',
    as it then removes the local instances for those migrations even though
    the instance never actually migrated to another host.
    """

    microversion = 'latest'

    def setUp(self):
        super(FailedEvacuateStateTests, self).setUp()

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

        self.hostname = 'host1'
        self.compute1 = self.start_service('compute', host=self.hostname)
        fake_network.set_stub_network_methods(self)

    def _wait_for_notification_event_type(self, event_type, max_retries=10):
        retry_counter = 0
        while True:
            if len(fake_notifier.NOTIFICATIONS) > 0:
                for notification in fake_notifier.NOTIFICATIONS:
                    if notification.event_type == event_type:
                        return
            if retry_counter == max_retries:
                self.fail('Wait for notification event type (%s) failed'
                          % event_type)
            retry_counter += 1
            time.sleep(0.5)

    def _boot_a_server(self):
        server_req = self._build_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        LOG.info('booting on %s', self.hostname)
        created_server = self.api.post_server({'server': server_req})
        return self._wait_for_state_change(created_server, 'ACTIVE')

    def test_evacuate_no_valid_host(self):
        # Boot a server
        server = self._boot_a_server()

        # Force source compute down
        compute_id = self.api.get_services(
            host=self.hostname, binary='nova-compute')[0]['id']
        self.api.put_service(compute_id, {'forced_down': 'true'})

        fake_notifier.stub_notifier(self)
        fake_notifier.reset()

        # Initiate evacuation
        post = {'evacuate': {}}
        self.api.post_server_action(server['id'], post)

        self._wait_for_notification_event_type('compute_task.rebuild_server')

        server = self._wait_for_state_change(server, 'ERROR')
        self.assertEqual(self.hostname, server['OS-EXT-SRV-ATTR:host'])

        # Check migrations
        migrations = self.api.get_migrations()
        self.assertEqual(1, len(migrations))
        self.assertEqual('evacuation', migrations[0]['migration_type'])
        self.assertEqual(server['id'], migrations[0]['instance_uuid'])
        self.assertEqual(self.hostname, migrations[0]['source_compute'])
        self.assertEqual('error', migrations[0]['status'])

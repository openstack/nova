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
import mock

import nova
from nova.tests.functional import integrated_helpers


class UpdateResourceMigrationRaceTest(
    integrated_helpers.ProviderUsageBaseTestCase):

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(UpdateResourceMigrationRaceTest, self).setUp()
        self._start_compute(host="host1")
        self._start_compute(host="host2")

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]

    def test_update_dest_between_mig_start_and_claim(self):
        """Validate update_available_resource when an instance exists that has
        started migrating but not yet been claimed on the destination.
        """

        server = self._boot_and_check_allocations(
            self.flavor1, 'host1')

        orig_prep = nova.compute.manager.ComputeManager.pre_live_migration

        def fake_pre(*args, **kwargs):
            # Trigger update_available_resource on the destination (this runs
            # it on the source as well, but that's okay).
            self._run_periodics()
            return orig_prep(*args, **kwargs)

        with mock.patch(
                'nova.compute.manager.ComputeManager.pre_live_migration',
                new=fake_pre):
            # Migrate the server.
            self.api.post_server_action(
                server['id'],
                {'os-migrateLive': {'host': None, 'block_migration': 'auto'}})

            self._wait_for_server_parameter(server, {
                 'OS-EXT-STS:task_state': None,
                 'status': 'ACTIVE'})

            # NOTE(efried): This was bug 1849165 where
            #  _populate_assigned_resources raised a TypeError because it tried
            #  to access the instance's migration_context before that existed.
            self.assertNotIn(
                "TypeError: argument of type 'NoneType' is not iterable",
                self.stdlog.logger.output)

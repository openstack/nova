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
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network
from nova.tests.unit import policy_fixture

CELL1_NAME = 'cell1'
CELL2_NAME = 'cell2'


class MultiCellSchedulerTestCase(test.TestCase,
                                 integrated_helpers.InstanceHelperMixin):

    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(MultiCellSchedulerTestCase, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.AllServicesCurrent())
        self.useFixture(func_fixtures.PlacementFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        fake_network.set_stub_network_methods(self)

        self.flags(allow_resize_to_same_host=False)
        self.flags(enabled_filters=['AllHostsFilter'],
                   group='filter_scheduler')
        self.start_service('conductor')
        self.start_service('scheduler')

    def _test_create_and_migrate(self, expected_status, az=None):
        server = self._create_server(az=az)

        return self.admin_api.api_post(
            '/servers/%s/action' % server['id'],
            {'migrate': None},
            check_response_status=[expected_status]), server

    def test_migrate_between_cells(self):
        """Verify that migrating between cells is not allowed.

        Right now, we can't migrate between cells. So, create two computes
        in different cells and make sure that migration fails with NoValidHost.
        """
        # Hosts in different cells
        self.start_service('compute', host='compute1', cell_name=CELL1_NAME)
        self.start_service('compute', host='compute2', cell_name=CELL2_NAME)

        _, server = self._test_create_and_migrate(expected_status=202)
        # The instance action should have failed with details.
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')

    def test_migrate_within_cell(self):
        """Verify that migrating within cells is allowed.

        Create two computes in the same cell and validate that the same
        migration is allowed.
        """
        # Hosts in the same cell
        self.start_service('compute', host='compute1', cell_name=CELL1_NAME)
        self.start_service('compute', host='compute2', cell_name=CELL1_NAME)
        # Create another host just so it looks like we have hosts in
        # both cells
        self.start_service('compute', host='compute3', cell_name=CELL2_NAME)

        # Force the server onto compute1 in cell1 so we do not accidentally
        # land on compute3 in cell2 and fail to migrate.
        _, server = self._test_create_and_migrate(expected_status=202,
                                      az='nova:compute1')
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

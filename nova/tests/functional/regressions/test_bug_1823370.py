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

from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class MultiCellEvacuateTestCase(integrated_helpers._IntegratedTestBase):
    """Recreate test for bug 1823370 which was introduced in Pike.

    When evacuating a server, the request to the scheduler should be restricted
    to the cell in which the instance is already running since cross-cell
    evacuate is not supported, at least not yet. This test creates two cells
    with two compute hosts in one cell and another compute host in the other
    cell. A server is created in the cell with two hosts and then evacuated
    which should land it on the other host in that cell, not the other cell
    with only one host. The scheduling behavior is controlled via the custom
    HostNameWeigher.
    """
    # Set variables used in the parent class.
    NUMBER_OF_CELLS = 2
    REQUIRES_LOCKING = False
    ADMIN_API = True
    api_major_version = 'v2.1'
    microversion = '2.11'  # Need at least 2.11 for the force-down API

    def setUp(self):
        # Register a custom weigher for predictable scheduling results.
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super(MultiCellEvacuateTestCase, self).setUp()

    def _setup_compute_service(self):
        """Start three compute services, two in cell1 and one in cell2.

        host1: cell1 (highest weight)
        host2: cell2 (medium weight)
        host3: cell1 (lowest weight)
        """
        host_to_cell = {'host1': 'cell1', 'host2': 'cell2', 'host3': 'cell1'}
        for host, cell in host_to_cell.items():
            self._start_compute(host, cell_name=cell)

    def test_evacuate_multi_cell(self):
        # Create a server which should land on host1 since it has the highest
        # weight.
        server = self._build_server()
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        # Disable the host on which the server is now running.
        self.computes['host1'].stop()
        self.api.force_down_service('host1', 'nova-compute', forced_down=True)

        # Now evacuate the server which should send it to host3 since it is
        # in the same cell as host1, even though host2 in cell2 is weighed
        # higher than host3.
        req = {'evacuate': {'onSharedStorage': False}}
        self.api.post_server_action(server['id'], req)
        self._wait_for_migration_status(server, ['done'])
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host3', server['OS-EXT-SRV-ATTR:host'])

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

from nova import context as nova_context
from nova import objects
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_crypto


class TestCrossCellResizeKeypairLoss(
    integrated_helpers.ProviderUsageBaseTestCase,
):
    """Regression test for bug 2108974.

    When an instance is resized across cells (cross-cell resize), the keypairs
    stored in the instance_extra table are not copied to the destination cell.
    After confirming the resize, the keypairs field in the destination cell's
    instance_extra table is NULL, effectively losing the server's keypair data.
    """

    NUMBER_OF_CELLS = 2
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        self.useFixture(nova_fixtures.HostNameWeigherFixture())
        super().setUp()

        # Enable cross-cell resize policy for admin.
        self.policy.set_rules({
            servers_policies.CROSS_CELL_RESIZE:
                base_policies.RULE_ADMIN_API},
            overwrite=False)

        self.flags(rpc_response_timeout=10)
        self.flags(long_rpc_timeout=60)

        # Set up 2 compute services in different cells.
        self.host_to_cell_mappings = {
            'host1': 'cell1', 'host2': 'cell2'}

        for host in self.host_to_cell_mappings:
            cell_name = self.host_to_cell_mappings[host]
            self._start_compute(host, cell_name=cell_name)
            agg_id = self._create_aggregate(
                cell_name, availability_zone=cell_name)
            body = {'add_host': {'host': host}}
            self.admin_api.post_aggregate_action(agg_id, body)

    def test_keypair_lost_after_cross_cell_resize_confirm(self):
        """Verify that keypairs are preserved after a cross-cell resize.

        Steps:
        1. Create a keypair
        2. Create a server with that keypair (lands on host1/cell1)
        3. Verify keypair is accessible via the instance object
        4. Resize to a different flavor (triggers cross-cell to host2/cell2)
        5. Confirm the resize
        6. Verify keypair is still accessible in the destination cell

        The bug causes step 6 to fail: keypairs is NULL in the destination
        cell's instance_extra table.
        """
        # Create a keypair.
        pub_key = fake_crypto.get_ssh_public_key()
        keypair_req = {
            'keypair': {
                'name': 'test-key',
                'type': 'ssh',
                'public_key': pub_key,
            },
        }
        keypair = self.api.post_keypair(keypair_req)

        # Create a server with the keypair.
        flavors = self.api.get_flavors()
        server = self._build_server(
            flavor_id=flavors[0]['id'], networks='none')
        server['key_name'] = 'test-key'
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Server should land on host1 in cell1.
        self.assertEqual('host1', server['OS-EXT-SRV-ATTR:host'])

        # Verify keypair is stored in the source cell.
        ctxt = nova_context.get_admin_context()
        source_cell = self.cell_mappings['cell1']
        with nova_context.target_cell(ctxt, source_cell) as cctxt:
            instance = objects.Instance.get_by_uuid(
                cctxt, server['id'], expected_attrs=['keypairs'])
            self.assertEqual(1, len(instance.keypairs))
            self.assertEqual(
                keypair['public_key'], instance.keypairs[0].public_key)

        # Resize to a different flavor. Since we only have 2 hosts, each
        # in a different cell, and the source host is excluded from
        # scheduling during resize, the server is forced to move to
        # host2 in cell2, triggering a cross-cell resize.
        new_flavor = flavors[1]
        body = {'resize': {'flavorRef': new_flavor['id']}}
        self.api.post_server_action(server['id'], body)
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])

        # Confirm the resize.
        self.api.post_server_action(server['id'], {'confirmResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')

        # Verify keypair is still accessible in the destination cell.
        target_cell = self.cell_mappings['cell2']
        with nova_context.target_cell(ctxt, target_cell) as cctxt:
            instance = objects.Instance.get_by_uuid(
                cctxt, server['id'], expected_attrs=['keypairs'])
            self.assertEqual(1, len(instance.keypairs))
            self.assertEqual(
                keypair['public_key'],
                instance.keypairs[0].public_key)

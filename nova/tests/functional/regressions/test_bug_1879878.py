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

import ddt
import mock

from nova.compute import resource_tracker as rt
from nova import context as nova_context
from nova import objects
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova import test
from nova.tests.functional import integrated_helpers
from nova.virt import fake as fake_driver


@ddt.ddt
class TestSameCell(integrated_helpers._IntegratedTestBase):
    """Reproducer for bug #1879878 (same-cell).

    Demonstrate the possibility of races caused by running the resource
    tracker's periodic task between marking a migration as confirmed or
    reverted and dropping the claim for that migration on the source or
    destination host, respectively.
    """

    # cold migration is an admin-only operation by default
    ADMIN_API = True
    compute_driver = 'fake.MediumFakeDriver'
    microversion = 'latest'

    def setUp(self):
        self.flags(compute_driver=self.compute_driver)
        super().setUp()
        self.ctxt = nova_context.get_admin_context()

    def _setup_compute_service(self):
        # Start two computes so we can migrate between them.
        self._start_compute('host1')
        self._start_compute('host2')

    def _create_server(self):
        """Creates and return a server along with a source host and target
        host.
        """
        server = super()._create_server(networks='none')
        self.addCleanup(self._delete_server, server)
        source_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host2' if source_host == 'host1' else 'host1'
        return server, source_host, target_host

    def assertUsage(self, hostname, usage):
        """Assert VCPU usage for the given host."""
        cn = objects.ComputeNode.get_by_nodename(self.ctxt, hostname)
        # we could test anything, but vcpu is easy to grok
        self.assertEqual(cn.vcpus_used, usage)

    @ddt.data(True, False)
    def test_migrate_confirm(self, drop_race):
        server, src_host, dst_host = self._create_server()

        # only one instance created, so usage on its host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        orig_drop_claim = rt.ResourceTracker.drop_move_claim_at_source

        def fake_drop_move_claim(*args, **kwargs):
            # run periodics after marking the migration confirmed, simulating a
            # race between the doing this and actually dropping the claim

            # check the usage, which should show usage on both hosts
            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            if drop_race:
                self._run_periodics()

            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            return orig_drop_claim(*args, **kwargs)

        self.stub_out(
            'nova.compute.resource_tracker.ResourceTracker.'
            'drop_move_claim_at_source',
            fake_drop_move_claim,
        )

        # TODO(stephenfin): Use a helper
        self.api.post_server_action(server['id'], {'migrate': None})
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # migration isn't complete so we should have usage on both hosts
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 1)

        self._confirm_resize(server)

        # migration is now confirmed so we should once again only have usage on
        # one host
        self.assertUsage(src_host, 0)
        self.assertUsage(dst_host, 1)

        # running periodics shouldn't change things
        self._run_periodics()

        self.assertUsage(src_host, 0)
        self.assertUsage(dst_host, 1)

    @ddt.data(True, False)
    def test_migrate_revert(self, drop_race):
        server, src_host, dst_host = self._create_server()

        # only one instance created, so usage on its host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        orig_drop_claim = rt.ResourceTracker.drop_move_claim_at_dest

        def fake_drop_move_claim(*args, **kwargs):
            # run periodics after marking the migration reverted, simulating a
            # race between the doing this and actually dropping the claim

            # check the usage, which should show usage on both hosts
            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            if drop_race:
                self._run_periodics()

            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            return orig_drop_claim(*args, **kwargs)

        self.stub_out(
            'nova.compute.resource_tracker.ResourceTracker.'
            'drop_move_claim_at_dest',
            fake_drop_move_claim,
        )

        # TODO(stephenfin): Use a helper
        self.api.post_server_action(server['id'], {'migrate': None})
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # migration isn't complete so we should have usage on both hosts
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 1)

        self._revert_resize(server)

        # migration is now reverted so we should once again only have usage on
        # one host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        # running periodics shouldn't change things
        self._run_periodics()

        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)


# TODO(stephenfin): This should inherit from _IntegratedTestBase
@ddt.ddt
class TestCrossCell(integrated_helpers.ProviderUsageBaseTestCase):
    """Reproducer for bug #1879878 (cross-cell).

    Demonstrate the possibility of races caused by running the resource
    tracker's periodic task between marking a migration as confirmed or
    reverted and dropping the claim for that migration on the source or
    destination host, respectively.
    """

    # cold migration is an admin-only operation by default
    ADMIN_API = True
    NUMBER_OF_CELLS = 2
    compute_driver = 'fake.MediumFakeDriver'

    def setUp(self):
        super().setUp()

        # adjust the polling interval and timeout for long RPC calls to
        # something smaller and saner
        self.flags(rpc_response_timeout=1, long_rpc_timeout=60)

        # enable cross-cell resize policy since it defaults to not allow anyone
        # to perform that type of operation. For these tests we'll just allow
        # admins to perform cross-cell resize.
        self.policy.set_rules(
            {servers_policies.CROSS_CELL_RESIZE: base_policies.RULE_ADMIN_API},
            overwrite=False)

        # start two compute services in two different cells so we can migrate
        # between them.
        self.cell_to_aggregate = {}
        self.host_to_cell_mappings = {
            'host1': 'cell1', 'host2': 'cell2',
        }
        for host_name, cell_name in self.host_to_cell_mappings.items():
            self._start_compute(host_name, cell_name=cell_name)
            # create an aggregate where the AZ name is the cell name.
            agg_id = self._create_aggregate(
                cell_name, availability_zone=cell_name)
            # add the host to the aggregate.
            self.admin_api.post_aggregate_action(
                agg_id, {'add_host': {'host': host_name}})
            self.cell_to_aggregate[cell_name] = agg_id

        self.ctxt = nova_context.get_admin_context()

    def _create_server(self):
        """Creates and return a server along with a source host and target
        host.
        """
        server = super()._create_server(networks='none')
        self.addCleanup(self._delete_server, server)
        source_host = server['OS-EXT-SRV-ATTR:host']
        target_host = 'host2' if source_host == 'host1' else 'host1'
        return server, source_host, target_host

    def assertUsage(self, hostname, usage):
        """Assert VCPU usage for the given host."""
        target_cell_name = self.host_to_cell_mappings[hostname]
        target_cell = self.cell_mappings[target_cell_name]
        with nova_context.target_cell(self.ctxt, target_cell) as cctxt:
            cn = objects.ComputeNode.get_by_nodename(cctxt, hostname)
            # we could test anything, but vcpu is easy to grok
            self.assertEqual(cn.vcpus_used, usage)

    @ddt.data(True, False)
    def test_migrate_confirm(self, drop_race):
        server, src_host, dst_host = self._create_server()

        # only one instance created, so usage on its host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        orig_drop_claim = rt.ResourceTracker.drop_move_claim
        orig_cleanup = fake_driver.FakeDriver.cleanup

        def fake_drop_move_claim(*args, **kwargs):
            # run periodics after marking the migration confirmed, simulating a
            # race between the doing this and actually dropping the claim

            # check the usage, which should show usage on both hosts
            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            if drop_race:
                self._run_periodics()

                self.assertUsage(src_host, 1)
                self.assertUsage(dst_host, 1)

            return orig_drop_claim(*args, **kwargs)

        def fake_cleanup(_self, _context, _instance, *args, **kwargs):
            self.assertIsNotNone(_instance.old_flavor)
            self.assertIsNotNone(_instance.new_flavor)
            return orig_cleanup(_self, _context, _instance, *args, **kwargs)

        # TODO(stephenfin): Use a helper
        self.api.post_server_action(server['id'], {'migrate': None})
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # migration isn't complete so we should have usage on both hosts
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 1)

        with test.nested(
            mock.patch(
                'nova.compute.resource_tracker.ResourceTracker'
                '.drop_move_claim',
                new=fake_drop_move_claim),
            mock.patch('nova.virt.fake.FakeDriver.cleanup', new=fake_cleanup),
        ):
            self._confirm_resize(server, cross_cell=True)

        # migration is now confirmed so we should once again only have usage on
        # one host
        self.assertUsage(src_host, 0)
        self.assertUsage(dst_host, 1)

        # running periodics shouldn't change things
        self._run_periodics()

        self.assertUsage(src_host, 0)
        self.assertUsage(dst_host, 1)

    @ddt.data(True, False)
    def test_migrate_revert(self, drop_race):
        server, src_host, dst_host = self._create_server()

        # only one instance created, so usage on its host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        orig_drop_claim = rt.ResourceTracker.drop_move_claim
        orig_finish_revert = fake_driver.FakeDriver.finish_revert_migration

        def fake_drop_move_claim(*args, **kwargs):
            # run periodics after marking the migration reverted, simulating a
            # race between the doing this and actually dropping the claim

            # check the usage, which should show usage on both hosts
            self.assertUsage(src_host, 1)
            self.assertUsage(dst_host, 1)

            if drop_race:
                self._run_periodics()

                self.assertUsage(src_host, 1)
                self.assertUsage(dst_host, 1)

            return orig_drop_claim(*args, **kwargs)

        def fake_finish_revert_migration(_self, _context, _instance, *a, **kw):
            self.assertIsNotNone(_instance.old_flavor)
            self.assertIsNotNone(_instance.new_flavor)
            return orig_finish_revert(_self, _context, _instance, *a, **kw)

        # TODO(stephenfin): Use a helper
        self.api.post_server_action(server['id'], {'migrate': None})
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # migration isn't complete so we should have usage on both hosts
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 1)

        with test.nested(
            mock.patch(
                'nova.compute.resource_tracker.ResourceTracker'
                '.drop_move_claim',
                new=fake_drop_move_claim),
            mock.patch(
                'nova.virt.fake.FakeDriver.finish_revert_migration',
                new=fake_finish_revert_migration),
        ):
            self._revert_resize(server)

        # migration is now reverted so we should once again only have usage on
        # one host
        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

        # running periodics shouldn't change things
        self._run_periodics()

        self.assertUsage(src_host, 1)
        self.assertUsage(dst_host, 0)

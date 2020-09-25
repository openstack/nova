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

from nova.compute import resource_tracker as rt
from nova import context as nova_context
from nova import objects
from nova.tests.functional import integrated_helpers


@ddt.ddt
class TestColdMigrationUsage(integrated_helpers._IntegratedTestBase):
    """Reproducer for bug #1879878.

    Demonstrate the possibility of races caused by running the resource
    tracker's periodic task between marking a migration as confirmed or
    reverted and dropping the claim for that migration on the source or
    destination host, respectively.
    """

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

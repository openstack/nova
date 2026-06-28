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

"""Regression test for bug #2153425.

https://bugs.launchpad.net/nova/+bug/2153425
"""

import fixtures

from nova import context
from nova import objects
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class NUMALiveMigrationCPUAllocationTests(
    base.LibvirtMigrationMixin,
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression for allocation_ratio check during NUMA live migration.

    At the point where `_call_livem_checks_on_host()` is called within
    `LiveMigrationTask._find_destination()`, `self.limits` is still `None`, so
    `limits` is not passed to subsequent processing. Consequently, the CPU
    limit check in `nova/virt/hardware.py` does not take effect.
    """

    microversion = 'latest'
    ADMIN_API = True
    ADDITIONAL_FILTERS = ['NUMATopologyFilter']

    def setUp(self):
        super().setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.compute.manager.ComputeManager.'
            '_live_migration_cleanup_flags',
            lambda *args, **kwargs: (True, True)))

    def get_host(self, server_id):
        server = self.api.get_server(server_id)
        return server['OS-EXT-SRV-ATTR:host']

    def _get_host_numa_usage(self, hostname):
        ctxt = context.get_admin_context()
        cn = objects.ComputeNode.get_by_nodename(ctxt, hostname)
        topology = objects.NUMATopology.obj_from_db_obj(cn.numa_topology)
        return [(cell.id, cell.cpu_usage) for cell in topology.cells]

    def test_live_migration_cpu_limit_per_cell(self):
        """Ensure that CPU usage per cell does not exceed the limit after live
        migration

        """
        self.flags(initial_cpu_allocation_ratio=1.5)
        # The `packing_host_numa_cells_allocation_strategy`
        # is set to True to pack instances into a single cell
        self.flags(
            packing_host_numa_cells_allocation_strategy=True,
            group='compute')

        host_info = fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                         cpu_cores=2, cpu_threads=1)

        self.start_compute(
            hostname='src',
            host_info=host_info)
        self.start_compute(
            hostname='dest',
            host_info=host_info)

        self.src = self.computes['src']
        self.dest = self.computes['dest']

        extra_spec = {'hw:numa_nodes': '1', 'hw:mem_page_size': 'small'}
        flavor = self._create_flavor(
            vcpu=2, memory_mb=512, extra_spec=extra_spec)

        # Boot 1 instance on dest. Cell 0: cpu_usage=2 (out of limit 3).
        self._create_server(
            flavor_id=flavor,
            az='nova',
            host='dest',
            networks='none')

        dest_usage = self._get_host_numa_usage('dest')
        self.assertEqual([(0, 2), (1, 0)], dest_usage)

        # Boot the server to migrate on src.
        self.server = self._create_server(
            flavor_id=flavor, az='nova', host='src', networks='none')
        self.assertEqual('src', self.get_host(self.server['id']))

        # The live migration should select Cell 1, not Cell 0
        # because selecting Cell 0 would exceed the limit of 3 (cpu_usage=4)
        self._live_migrate(self.server, 'completed', host='dest')
        self.assertEqual('dest', self.get_host(self.server['id']))

        # Verify that the instance has landed on Cell 1
        dest_usage = self._get_host_numa_usage('dest')
        self.assertEqual([(0, 2), (1, 2)], dest_usage)

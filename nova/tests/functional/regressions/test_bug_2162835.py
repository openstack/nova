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

import threading

import fixtures

from nova import context as nova_context
from nova import objects
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import base


class TestEvacuatePinnedCpusPeriodicRace(base.ServersTestBase):
    """Regression test for bug 2162835.

    When multiple VMs with dedicated CPU pinning are evacuated to the same
    destination host, the ResourceTracker's ``_update_available_resource``
    periodic task can execute between ``_update_instance_after_spawn``
    (which clears ``task_state``) and ``finish_evacuation`` (which updates
    ``instance.host``).

    During this window the periodic task:
    1. Resets ``pinned_cpus`` from the virt driver (always empty).
    2. Skips the evacuating instance in ``_update_usage_from_instances``
       because ``instance.host`` still points to the source.
    3. Skips the migration in ``_update_usage_from_migrations`` because
       ``task_state=None`` fails the ``_instance_in_resize_state`` check.

    This causes ``cn.numa_topology.pinned_cpus`` to be reset to an empty
    set. The next ``rebuild_claim`` for another VM then sees all CPUs as
    free and assigns pCPUs that are already in use, leading to duplicate
    pCPU assignments.
    """

    ADMIN_API = True
    CAST_AS_CALL = False
    microversion = 'latest'

    def setUp(self):
        super().setUp()
        self.flags(cpu_dedicated_set='0-3', group='compute')

        host_info = fakelibvirt.HostInfo(
            cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1)

        self.start_compute(hostname='host1', host_info=host_info)
        self.start_compute(hostname='host2', host_info=host_info)

    def _get_instance_host_cpus(self, server_id):
        """Return the set of host pCPUs pinned to an instance."""
        ctxt = nova_context.get_admin_context()
        topo = objects.InstanceNUMATopology.get_by_instance_uuid(
            ctxt, server_id)
        return set(topo.cells[0].cpu_pinning_raw.values())

    def _get_host_pinned_cpus(self, hostname):
        """Return the set of pCPUs tracked as pinned on a compute node."""
        ctxt = nova_context.get_admin_context()
        cn = objects.ComputeNode.get_by_nodename(ctxt, hostname)
        numa_topology = objects.NUMATopology.obj_from_db_obj(
            cn.numa_topology)
        return numa_topology.cells[0].pinned_cpus

    def test_evacuate_pinned_cpus_race_with_periodic(self):
        """Verify that the periodic task corrupts pinned_cpus during
        evacuate, causing duplicate pCPU assignments across VMs.
        """
        flavor_id = self._create_flavor(
            vcpu=2, extra_spec={'hw:cpu_policy': 'dedicated'})

        server_a = self._create_server(
            flavor_id=flavor_id, host='host1', networks='none')
        server_b = self._create_server(
            flavor_id=flavor_id, host='host1', networks='none')

        # All 4 dedicated CPUs on host1 should be consumed
        self.assertEqual(4, len(self._get_host_pinned_cpus('host1')))

        # --- Stop host1 and force it down to allow evacuation ---
        self.computes['host1'].stop()
        service = self.admin_api.get_services(
            host='host1', binary='nova-compute')[0]
        self.admin_api.put_service(service['id'], {'forced_down': 'true'})

        # --- Set up synchronization for the race window ---
        # Two threading.Events coordinate the test thread with the
        # compute thread running the evacuation:
        # - entered: signals that finish_evacuation has been called,
        #   meaning _update_instance_after_spawn has already cleared
        #   task_state but instance.host has not been updated yet.
        # - proceed: the test signals finish_evacuation to continue
        #   after the periodic has run.
        entered = threading.Event()
        self.addCleanup(entered.set)
        proceed = threading.Event()
        self.addCleanup(proceed.set)

        rt = self.computes['host2'].manager.rt
        original_finish = rt.finish_evacuation

        def blocking_finish(instance, node, migration):
            entered.set()
            proceed.wait()
            return original_finish(instance, node, migration)

        self.useFixture(fixtures.MockPatchObject(
            rt, 'finish_evacuation', side_effect=blocking_finish))

        # 1) Trigger server_a evacuation (non-blocking, CAST_AS_CALL=False)
        self.api.post_server_action(server_a['id'], {'evacuate': {}})

        # 2) Wait until the evacuation reaches finish_evacuation,
        #    i.e. _update_instance_after_spawn has already run and
        #    task_state is cleared.
        self.assertTrue(
            entered.wait(timeout=60),
            "Timed out waiting for finish_evacuation to be entered")

        # 3) Run the periodic task from the test thread. This resets
        #    host2's pinned_cpus because:
        #    - instance.host still = host1 (not counted)
        #    - migration is skipped (task_state=None)
        self._run_periodics()

        # 4) Allow finish_evacuation to proceed
        proceed.set()

        # 5) Wait for the first evacuation to complete
        self._wait_for_migration_status(server_a, ['done'])
        server_a = self._wait_for_server_parameter(
            server_a, {
                'OS-EXT-SRV-ATTR:host': 'host2',
                'status': 'SHUTOFF',
            })

        # Evacuate server_b normally (blocking_finish passes through).
        # rebuild_claim sees pinned_cpus={} and assigns the same pCPUs.
        self.api.post_server_action(server_b['id'], {'evacuate': {}})
        self._wait_for_migration_status(server_b, ['done'])
        server_b = self._wait_for_server_parameter(
            server_b, {
                'OS-EXT-SRV-ATTR:host': 'host2',
                'status': 'SHUTOFF',
            })

        cpus_a = self._get_instance_host_cpus(server_a['id'])
        cpus_b = self._get_instance_host_cpus(server_b['id'])

        # TODO(bug #2162835): Due to the race condition in the
        # ResourceTracker, the periodic task resets pinned_cpus
        # during evacuate. This causes server_b to be assigned the
        # same pCPUs as server_a. Once the bug is fixed, the CPU
        # sets should be disjoint (no overlap) and host2 should
        # track all 4 CPUs as pinned:
        #   self.assertFalse(cpus_a & cpus_b)
        #   self.assertEqual(4, len(self._get_host_pinned_cpus('host2')))
        self.assertTrue(
            cpus_a & cpus_b,
            f"Expected overlapping pCPUs but got disjoint sets: "
            f"server_a={cpus_a}, server_b={cpus_b}")

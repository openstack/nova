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
        """Verify that the periodic task does not corrupt pinned_cpus
        during evacuate, even when it runs in the race window between
        _update_instance_after_spawn and finish_evacuation.
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
        #   meaning _update_instance_after_spawn has already run
        #   (task_state=REBUILDING) but instance.host has not been
        #   updated yet.
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
        #    i.e. _update_instance_after_spawn has already run
        #    (task_state=REBUILDING) but instance.host is still source.
        self.assertTrue(
            entered.wait(timeout=60),
            "Timed out waiting for finish_evacuation to be entered")

        # 3) Run the periodic task from the test thread. Without the
        #    fix, this would reset host2's pinned_cpus because the
        #    evacuating instance is not counted (host=source) and the
        #    migration is skipped. With the fix, _instance_is_evacuating
        #    ensures the migration resources are still tracked.
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

        self.assertFalse(
            cpus_a & cpus_b,
            f"Expected disjoint pCPUs but got overlap: "
            f"server_a={cpus_a}, server_b={cpus_b}")
        self.assertEqual(4, len(self._get_host_pinned_cpus('host2')))


class TestEvacuateTaskStateRace(base.ServersTestBase):
    """Send reboot requests between evacuation's spawn and host update.

    These tests recreates the following scenario:
    1. server created on host 'source'
    2. host 'source' is stopped
    3. server evacuation requested and let it just before finish_evacuation
       on the destination. At this point the task_state is REBUILDING and
       the instance.host is still pointing to the 'source' host.
    4. sends a reboot request to the server that is now rejected properly
       and does not interfere with the ongoing evacuation.
    """

    ADMIN_API = True
    CAST_AS_CALL = False
    REQUIRES_LOCKING = False
    microversion = "latest"

    def setUp(self):
        super().setUp()
        self.start_compute("source")
        self.start_compute("dest")

    def _create_evac_and_stop_before_finish(self):
        server = self._create_server(host="source", networks="none")

        entered = threading.Event()
        self.addCleanup(entered.set)
        proceed = threading.Event()
        self.addCleanup(proceed.set)
        finished = threading.Event()
        self.addCleanup(finished.set)
        manager = self.computes["dest"].manager
        original_finish = manager.rt.finish_evacuation
        original_rebuild = manager.rebuild_instance

        def pause_finish(*args, **kwargs):
            entered.set()
            if not proceed.wait(timeout=60):
                raise RuntimeError("Timed out waiting to finish evacuation")
            return original_finish(*args, **kwargs)

        def track_rebuild(*args, **kwargs):
            try:
                return original_rebuild(*args, **kwargs)
            finally:
                finished.set()

        self.useFixture(
            fixtures.MockPatchObject(
                manager.rt, "finish_evacuation", side_effect=pause_finish
            )
        )
        self.useFixture(
            fixtures.MockPatchObject(
                manager, "rebuild_instance", side_effect=track_rebuild
            )
        )

        self.computes["source"].stop()
        service = self.admin_api.get_services(
            host="source", binary="nova-compute")[0]
        self.admin_api.put_service_force_down(service["id"], True)

        self.api.post_server_action(
            server["id"], {"evacuate": {"host": "dest"}})
        self.assertTrue(
            entered.wait(timeout=60),
            "Evacuation did not reach finish_evacuation"
        )

        # A domain already exists on dest, but API actions still use
        # source until finish_evacuation updates the database.
        self.assertIn(server["id"], manager.driver.list_instance_uuids())
        paused_server = self.api.get_server(server["id"])
        self.assertEqual("source", paused_server["OS-EXT-SRV-ATTR:host"])

        return server, proceed, finished

    def test_reboot_during_evacuation(self):
        server, proceed, finished = self._create_evac_and_stop_before_finish()

        # The API now rejects the reboot properly
        self.api.api_post(
            "/servers/%s/action" % server["id"],
            {"reboot": {"type": "HARD"}},
            check_response_status=[409],
        )

        server = self.api.get_server(server["id"])
        self._wait_for_server_parameter(
            server,
            {
                "OS-EXT-SRV-ATTR:host": "source",
                "OS-EXT-STS:task_state": "rebuilding",
                "status": "REBUILD",
            })
        self._wait_for_migration_status(server, ["pre-migrating"])

        # This allows the evacuation to finish and the reboot is not
        # interfering with it
        proceed.set()
        finished.wait(timeout=60)
        self.assertTrue(finished.is_set(), "Evacuation did not finish")
        self._wait_for_migration_status(server, ["done"])
        self._wait_for_server_parameter(
            server,
            {
                "OS-EXT-SRV-ATTR:host": "dest",
                "OS-EXT-STS:task_state": None,
                "status": "SHUTOFF",
            })

    def test_reboot_during_evacuation_to_active(self):
        # With microversion older than 2.95 the evacuation moves the VM to
        # ACTIVE state on the destination host instead of SHUTOFF.
        self.api.microversion = "2.94"
        server, proceed, finished = self._create_evac_and_stop_before_finish()

        # The API now rejects the reboot properly
        self.api.api_post(
            "/servers/%s/action" % server["id"],
            {"reboot": {"type": "HARD"}},
            check_response_status=[409],
        )

        server = self.api.get_server(server["id"])
        self._wait_for_server_parameter(
            server,
            {
                "OS-EXT-SRV-ATTR:host": "source",
                "OS-EXT-STS:task_state": "rebuilding",
                "status": "REBUILD",
            })
        self._wait_for_migration_status(server, ["pre-migrating"])

        # This allows the evacuation to finish and the reboot is not
        # interfering with it
        proceed.set()
        finished.wait(timeout=60)
        self.assertTrue(finished.is_set(), "Evacuation did not finish")
        self._wait_for_migration_status(server, ["done"])
        self._wait_for_server_parameter(
            server,
            {
                "OS-EXT-SRV-ATTR:host": "dest",
                "OS-EXT-STS:task_state": None,
                "status": "ACTIVE",
            })

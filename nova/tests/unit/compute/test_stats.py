# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
#
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

"""Tests for compute node stats."""
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import stats
from nova.compute import task_states
from nova.compute import vm_states
from nova import test
from nova.tests.unit import fake_instance


class StatsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(StatsTestCase, self).setUp()
        self.stats = stats.Stats()

    def _fake_object(self, updates):
        return fake_instance.fake_instance_obj(None, **updates)

    def _create_instance(self, values=None):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 1,
            "uuid": uuids.stats_linux_instance_1,
        }
        if values:
            instance.update(values)
        return self._fake_object(instance)

    def test_os_type_count(self):
        os_type = "Linux"
        self.assertEqual(0, self.stats.num_os_type(os_type))
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_Vax")
        self.assertEqual(2, self.stats.num_os_type(os_type))
        self.stats["num_os_type_" + os_type] -= 1
        self.assertEqual(1, self.stats.num_os_type(os_type))

    def test_update_project_count(self):
        proj_id = "1234"

        def _get():
            return self.stats.num_instances_for_project(proj_id)

        self.assertEqual(0, _get())
        self.stats._increment("num_proj_" + proj_id)
        self.assertEqual(1, _get())
        self.stats["num_proj_" + proj_id] -= 1
        self.assertEqual(0, _get())

    def test_instance_count(self):
        self.assertEqual(0, self.stats.num_instances)
        for i in range(5):
            self.stats._increment("num_instances")
        self.stats["num_instances"] -= 1
        self.assertEqual(4, self.stats.num_instances)

    def test_add_stats_for_instance(self):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 3,
            "uuid": uuids.stats_linux_instance_1,
        }
        self.stats.update_stats_for_instance(self._fake_object(instance))

        instance = {
            "os_type": "FreeBSD",
            "project_id": "1234",
            "task_state": task_states.SCHEDULING,
            "vm_state": None,
            "vcpus": 1,
            "uuid": uuids.stats_freebsd_instance,
        }
        self.stats.update_stats_for_instance(self._fake_object(instance))

        instance = {
            "os_type": "Linux",
            "project_id": "2345",
            "task_state": task_states.SCHEDULING,
            "vm_state": vm_states.BUILDING,
            "vcpus": 2,
            "uuid": uuids.stats_linux_instance_2,
        }

        self.stats.update_stats_for_instance(self._fake_object(instance))

        instance = {
            "os_type": "Linux",
            "project_id": "2345",
            "task_state": task_states.RESCUING,
            "vm_state": vm_states.ACTIVE,
            "vcpus": 2,
            "uuid": uuids.stats_linux_instance_3,
        }

        self.stats.update_stats_for_instance(self._fake_object(instance))

        instance = {
            "os_type": "Linux",
            "project_id": "2345",
            "task_state": task_states.UNSHELVING,
            "vm_state": vm_states.ACTIVE,
            "vcpus": 2,
            "uuid": uuids.stats_linux_instance_4,
        }

        self.stats.update_stats_for_instance(self._fake_object(instance))

        self.assertEqual(4, self.stats.num_os_type("Linux"))
        self.assertEqual(1, self.stats.num_os_type("FreeBSD"))

        self.assertEqual(2, self.stats.num_instances_for_project("1234"))
        self.assertEqual(3, self.stats.num_instances_for_project("2345"))

        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(2, self.stats["num_task_" + task_states.SCHEDULING])
        self.assertEqual(1, self.stats["num_task_" + task_states.UNSHELVING])
        self.assertEqual(1, self.stats["num_task_" + task_states.RESCUING])

        self.assertEqual(1, self.stats["num_vm_None"])
        self.assertEqual(2, self.stats["num_vm_" + vm_states.BUILDING])

    def test_calculate_workload(self):
        self.stats._increment("num_task_None")
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.assertEqual(2, self.stats.calculate_workload())

    def test_update_stats_for_instance_no_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        self.stats.update_stats_for_instance(instance)  # no change
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_vm_" + vm_states.BUILDING])

    def test_update_stats_for_instance_vm_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        instance["vm_state"] = vm_states.PAUSED
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project(1234))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(0, self.stats["num_vm_%s" % vm_states.BUILDING])
        self.assertEqual(1, self.stats["num_vm_%s" % vm_states.PAUSED])

    def test_update_stats_for_instance_task_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        instance["task_state"] = task_states.REBUILDING
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(0, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_task_%s" % task_states.REBUILDING])

    def test_update_stats_for_instance_deleted(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))

        instance["vm_state"] = vm_states.DELETED
        self.stats.update_stats_for_instance(instance)

        self.assertEqual(0, self.stats.num_instances)
        self.assertEqual(0, self.stats.num_instances_for_project("1234"))
        self.assertEqual(0, self.stats.num_os_type("Linux"))
        self.assertEqual(0, self.stats["num_vm_" + vm_states.BUILDING])

    def test_update_stats_for_instance_offloaded(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))

        instance["vm_state"] = vm_states.SHELVED_OFFLOADED
        self.stats.update_stats_for_instance(instance)

        self.assertEqual(0, self.stats.num_instances)
        self.assertEqual(0, self.stats.num_instances_for_project("1234"))
        self.assertEqual(0, self.stats.num_os_type("Linux"))
        self.assertEqual(0, self.stats["num_vm_" + vm_states.BUILDING])

    def test_update_stats_for_instance_being_unshelved(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))

        instance["vm_state"] = vm_states.SHELVED_OFFLOADED
        instance["task_state"] = task_states.SPAWNING
        self.stats.update_stats_for_instance(instance)

        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project(1234))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(1, self.stats["num_vm_%s" %
                                       vm_states.SHELVED_OFFLOADED])
        self.assertEqual(1, self.stats["num_task_%s" % task_states.SPAWNING])

    def test_io_workload(self):
        vms = [vm_states.ACTIVE, vm_states.BUILDING, vm_states.PAUSED]
        tasks = [task_states.RESIZE_MIGRATING, task_states.REBUILDING,
                 task_states.RESIZE_PREP, task_states.IMAGE_SNAPSHOT,
                 task_states.IMAGE_BACKUP, task_states.RESCUING,
                 task_states.UNSHELVING, task_states.SHELVING]

        for state in vms:
            self.stats._increment("num_vm_" + state)
        for state in tasks:
            self.stats._increment("num_task_" + state)

        self.assertEqual(8, self.stats.io_workload)

    def test_io_workload_saved_to_stats(self):
        values = {'task_state': task_states.RESIZE_MIGRATING}
        instance = self._create_instance(values)
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(2, self.stats["io_workload"])

    def test_clear(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        self.assertNotEqual(0, len(self.stats))
        self.assertEqual(1, len(self.stats.states))
        self.stats.clear()

        self.assertEqual(0, len(self.stats))
        self.assertEqual(0, len(self.stats.states))

    def test_build_failed_succeded(self):
        self.assertEqual('not-set', self.stats.get('failed_builds', 'not-set'))
        self.stats.build_failed()
        self.assertEqual(1, self.stats['failed_builds'])
        self.stats.build_failed()
        self.assertEqual(2, self.stats['failed_builds'])
        self.stats.build_succeeded()
        self.assertEqual(0, self.stats['failed_builds'])
        self.stats.build_succeeded()
        self.assertEqual(0, self.stats['failed_builds'])

    def test_build_succeeded_first(self):
        self.assertEqual('not-set', self.stats.get('failed_builds', 'not-set'))
        self.stats.build_succeeded()
        self.assertEqual(0, self.stats['failed_builds'])

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
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

"""Tests for compute node stats"""

from nova.compute import stats
from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import exception
from nova import test


class StatsTestCase(test.TestCase):
    def setUp(self):
        super(StatsTestCase, self).setUp()
        self.stats = stats.Stats()

    def _create_instance(self, values=None):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 1,
        }
        if values:
            instance.update(values)
        return instance

    def testOsTypeCount(self):
        os_type = "Linux"
        self.assertEqual(0, self.stats.num_os_type(os_type))
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_Vax")
        self.assertEqual(2, self.stats.num_os_type(os_type))
        self.stats["num_os_type_" + os_type] -= 1
        self.assertEqual(1, self.stats.num_os_type(os_type))

    def testUpdateProjectCount(self):
        proj_id = "1234"

        def _get():
            return self.stats.num_instances_for_project(proj_id)

        self.assertEqual(0, _get())
        self.stats._increment("num_proj_" + proj_id)
        self.assertEqual(1, _get())
        self.stats["num_proj_" + proj_id] -= 1
        self.assertEqual(0, _get())

    def testInstanceCount(self):
        self.assertEqual(0, self.stats.num_instances)
        for i in range(5):
            self.stats._increment("num_instances")
        self.stats["num_instances"] -= 1
        self.assertEqual(4, self.stats.num_instances)

    def testAddStatsForInstance(self):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 3,
        }
        self.stats.add_stats_for_instance(instance)

        instance = {
            "os_type": "FreeBSD",
            "project_id": "1234",
            "task_state": task_states.SCHEDULING,
            "vm_state": None,
            "vcpus": 1,
        }
        self.stats.add_stats_for_instance(instance)

        instance = {
            "os_type": "Linux",
            "project_id": "2345",
            "task_state": task_states.SCHEDULING,
            "vm_state": vm_states.BUILDING,
            "vcpus": 2,
        }
        self.stats.add_stats_for_instance(instance)

        self.assertEqual(2, self.stats.num_os_type("Linux"))
        self.assertEqual(1, self.stats.num_os_type("FreeBSD"))

        self.assertEquals(2, self.stats.num_instances_for_project("1234"))
        self.assertEquals(1, self.stats.num_instances_for_project("2345"))

        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(2, self.stats["num_task_" + task_states.SCHEDULING])

        self.assertEqual(1, self.stats["num_vm_None"])
        self.assertEqual(2, self.stats["num_vm_" + vm_states.BUILDING])

        self.assertEqual(6, self.stats.num_vcpus_used)

    def testCalculateWorkload(self):
        self.stats._increment("num_task_None")
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.assertEqual(2, self.stats.calculate_workload())

    def testUpdateStatsForInstanceNoChange(self):
        old = self._create_instance()
        self.stats.add_stats_for_instance(old)

        self.stats.update_stats_for_instance(old, old)  # no change
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_vm_" + vm_states.BUILDING])

    def testUpdateStatsForInstanceVmChange(self):
        old = self._create_instance()
        self.stats.add_stats_for_instance(old)

        new = self._create_instance({"vm_state": vm_states.PAUSED})
        self.stats.update_stats_for_instance(old, new)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project(1234))
        self.assertEqual(1, self.stats.num_os_type("Linux"))
        self.assertEqual(0, self.stats.num_vm_state(vm_states.BUILDING))
        self.assertEqual(1, self.stats.num_vm_state(vm_states.PAUSED))

    def testUpdateStatsForInstanceVmChange(self):
        old = self._create_instance()
        self.stats.add_stats_for_instance(old)

        new = self._create_instance({"task_state": task_states.REBUILDING})
        self.stats.update_stats_for_instance(old, new)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(0, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_task_" + task_states.REBUILDING])

    def testUpdateStatsForInstanceDeleted(self):
        old = self._create_instance()
        self.stats.add_stats_for_instance(old)
        self.assertEqual(1, self.stats["num_proj_1234"])

        new = self._create_instance({"vm_state": vm_states.DELETED})
        self.stats.update_stats_for_instance(old, new)

        self.assertEqual(0, self.stats.num_instances)
        self.assertEqual(0, self.stats.num_instances_for_project("1234"))
        self.assertEqual(0, self.stats.num_os_type("Linux"))
        self.assertEqual(0, self.stats["num_vm_" + vm_states.BUILDING])
        self.assertEqual(0, self.stats.num_vcpus_used)

    def testIoWorkload(self):
        vms = [vm_states.ACTIVE, vm_states.BUILDING, vm_states.PAUSED]
        tasks = [task_states.RESIZE_MIGRATING, task_states.REBUILDING,
                      task_states.RESIZE_PREP, task_states.IMAGE_SNAPSHOT,
                      task_states.IMAGE_BACKUP, task_states.RESCUING]

        for state in vms:
            self.stats._increment("num_vm_" + state)
        for state in tasks:
            self.stats._increment("num_task_" + state)

        self.assertEqual(6, self.stats.calculate_io_workload())

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

from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class Stats(dict):
    """Handler for updates to compute node workload stats."""

    def add_stats_for_instance(self, instance):
        self._increment("num_task_%s" % instance['task_state'])

        self._increment("num_vm_%s" % instance['vm_state'])
        self._increment("num_instances")

        os_type = instance['os_type']
        self._increment("num_os_type_%s" % os_type)

        proj_id = instance['project_id']
        self._increment("num_proj_%s" % proj_id)

        x = self.get("num_vcpus_used", 0)
        self["num_vcpus_used"] = x + instance["vcpus"]

    def calculate_io_workload(self):
        """Calculate an I/O based load by counting I/O heavy operations"""

        def _get(state, state_type):
            key = "num_%s_%s" % (state_type, state)
            return self.get(key, 0)

        num_builds = _get(vm_states.BUILDING, "vm")
        num_migrations = _get(task_states.RESIZE_MIGRATING, "task")
        num_rebuilds = _get(task_states.REBUILDING, "task")
        num_resizes = _get(task_states.RESIZE_PREP, "task")
        num_snapshots = _get(task_states.IMAGE_SNAPSHOT, "task")
        num_backups = _get(task_states.IMAGE_BACKUP, "task")

        return (num_builds + num_rebuilds + num_resizes + num_migrations +
                num_snapshots + num_backups)

    def calculate_workload(self):
        """Calculate current load of the compute host based on
        task states.
        """
        current_workload = 0
        for k in self:
            if k.startswith("num_task") and not k.endswith("None"):
                current_workload += self[k]
        return current_workload

    @property
    def num_instances(self):
        return self.get("num_instances", 0)

    def num_instances_for_project(self, project_id):
        key = "num_proj_%s" % project_id
        return self.get(key, 0)

    def num_os_type(self, os_type):
        key = "num_os_type_%s" % os_type
        return self.get(key, 0)

    @property
    def num_vcpus_used(self):
        return self.get("num_vcpus_used", 0)

    def update_stats_for_instance(self, old_instance, instance):
        """Update stats after an instance is changed."""

        old_vm_state = old_instance['vm_state']
        new_vm_state = instance['vm_state']

        if old_vm_state != new_vm_state:
            self._decrement("num_vm_%s" % old_vm_state)
            self._increment("num_vm_%s" % new_vm_state)

        if new_vm_state == vm_states.DELETED:
            self._decrement("num_instances")

            self._decrement("num_os_type_%s" % old_instance['os_type'])

            self._decrement("num_proj_%s" % old_instance["project_id"])

            x = self.get("num_vcpus_used", 0)
            self["num_vcpus_used"] = x - old_instance['vcpus']

        old_task_state = old_instance['task_state']
        new_task_state = instance['task_state']

        if old_task_state != new_task_state:
            self._decrement("num_task_%s" % old_task_state)
            self._increment("num_task_%s" % new_task_state)

    def _decrement(self, key):
        x = self.get(key, 0)
        self[key] = x - 1

    def _increment(self, key):
        x = self.get(key, 0)
        self[key] = x + 1

# Copyright 2010 OpenStack Foundation
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

"""Possible vm states for instances.

Compute instance vm states represent the state of an instance as it pertains to
a user or administrator.

vm_state describes a VM's current stable (not transition) state. That is, if
there is no ongoing compute API calls (running tasks), vm_state should reflect
what the customer expect the VM to be. When combined with task states
(task_states.py), a better picture can be formed regarding the instance's
health and progress.

See http://wiki.openstack.org/VMState
"""

from nova.compute import task_states
from nova.objects import fields


# VM is running
ACTIVE = fields.InstanceState.ACTIVE

# VM only exists in DB
BUILDING = fields.InstanceState.BUILDING

PAUSED = fields.InstanceState.PAUSED

# VM is suspended to disk.
SUSPENDED = fields.InstanceState.SUSPENDED

# VM is powered off, the disk image is still there.
STOPPED = fields.InstanceState.STOPPED

# A rescue image is running with the original VM image attached
RESCUED = fields.InstanceState.RESCUED

# a VM with the new size is active. The user is expected to manually confirm
# or revert.
RESIZED = fields.InstanceState.RESIZED

# VM is marked as deleted but the disk images are still available to restore.
SOFT_DELETED = fields.InstanceState.SOFT_DELETED

# VM is permanently deleted.
DELETED = fields.InstanceState.DELETED

ERROR = fields.InstanceState.ERROR

# VM is powered off, resources still on hypervisor
SHELVED = fields.InstanceState.SHELVED

# VM and associated resources are not on hypervisor
SHELVED_OFFLOADED = fields.InstanceState.SHELVED_OFFLOADED

# states we can soft reboot from
ALLOW_SOFT_REBOOT = [ACTIVE]

# states we allow hard reboot from
ALLOW_HARD_REBOOT = ALLOW_SOFT_REBOOT + [STOPPED, PAUSED, SUSPENDED, ERROR]

# states we allow to trigger crash dump
ALLOW_TRIGGER_CRASH_DUMP = [ACTIVE, PAUSED, RESCUED, RESIZED, ERROR]


def allow_resource_removal(vm_state, task_state=None):
    """(vm_state, task_state) combinations we allow resources to be freed in"""

    return (
        vm_state == DELETED or
        vm_state == SHELVED_OFFLOADED and task_state != task_states.SPAWNING
    )

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

ACTIVE = 'active'  # VM is running
BUILDING = 'building'  # VM only exists in DB
PAUSED = 'paused'
SUSPENDED = 'suspended'  # VM is suspended to disk.
STOPPED = 'stopped'  # VM is powered off, the disk image is still there.
RESCUED = 'rescued'  # A rescue image is running with the original VM image
# attached.
RESIZED = 'resized'  # a VM with the new size is active. The user is expected
# to manually confirm or revert.

SOFT_DELETED = 'soft-delete'  # VM is marked as deleted but the disk images are
# still available to restore.
DELETED = 'deleted'  # VM is permanently deleted.

ERROR = 'error'

SHELVED = 'shelved'  # VM is powered off, resources still on hypervisor
SHELVED_OFFLOADED = 'shelved_offloaded'  # VM and associated resources are
# not on hypervisor

ALLOW_SOFT_REBOOT = [ACTIVE]  # states we can soft reboot from
ALLOW_HARD_REBOOT = ALLOW_SOFT_REBOOT + [STOPPED, PAUSED, SUSPENDED, ERROR]
# states we allow hard reboot from

ALLOW_TRIGGER_CRASH_DUMP = [ACTIVE, PAUSED, RESCUED, RESIZED, ERROR]
# states we allow to trigger crash dump

ALLOW_RESOURCE_REMOVAL = [DELETED, SHELVED_OFFLOADED]
# states we allow resources to be freed in

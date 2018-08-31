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

"""Possible task states for instances.

Compute instance task states represent what is happening to the instance at the
current moment. These tasks can be generic, such as 'spawning', or specific,
such as 'block_device_mapping'. These task states allow for a better view into
what an instance is doing and should be displayed to users/administrators as
necessary.

"""

from nova.objects import fields

# possible task states during create()
SCHEDULING = fields.InstanceTaskState.SCHEDULING
BLOCK_DEVICE_MAPPING = fields.InstanceTaskState.BLOCK_DEVICE_MAPPING
NETWORKING = fields.InstanceTaskState.NETWORKING
SPAWNING = fields.InstanceTaskState.SPAWNING

# possible task states during snapshot()
IMAGE_SNAPSHOT = fields.InstanceTaskState.IMAGE_SNAPSHOT
IMAGE_SNAPSHOT_PENDING = fields.InstanceTaskState.IMAGE_SNAPSHOT_PENDING
IMAGE_PENDING_UPLOAD = fields.InstanceTaskState.IMAGE_PENDING_UPLOAD
IMAGE_UPLOADING = fields.InstanceTaskState.IMAGE_UPLOADING

# possible task states during backup()
IMAGE_BACKUP = fields.InstanceTaskState.IMAGE_BACKUP

# possible task states during set_admin_password()
UPDATING_PASSWORD = fields.InstanceTaskState.UPDATING_PASSWORD

# possible task states during resize()
RESIZE_PREP = fields.InstanceTaskState.RESIZE_PREP
RESIZE_MIGRATING = fields.InstanceTaskState.RESIZE_MIGRATING
RESIZE_MIGRATED = fields.InstanceTaskState.RESIZE_MIGRATED
RESIZE_FINISH = fields.InstanceTaskState.RESIZE_FINISH

# possible task states during revert_resize()
RESIZE_REVERTING = fields.InstanceTaskState.RESIZE_REVERTING

# possible task states during confirm_resize()
RESIZE_CONFIRMING = fields.InstanceTaskState.RESIZE_CONFIRMING

# possible task states during reboot()
REBOOTING = fields.InstanceTaskState.REBOOTING
REBOOT_PENDING = fields.InstanceTaskState.REBOOT_PENDING
REBOOT_STARTED = fields.InstanceTaskState.REBOOT_STARTED
REBOOTING_HARD = fields.InstanceTaskState.REBOOTING_HARD
REBOOT_PENDING_HARD = fields.InstanceTaskState.REBOOT_PENDING_HARD
REBOOT_STARTED_HARD = fields.InstanceTaskState.REBOOT_STARTED_HARD

# possible task states during pause()
PAUSING = fields.InstanceTaskState.PAUSING

# possible task states during unpause()
UNPAUSING = fields.InstanceTaskState.UNPAUSING

# possible task states during suspend()
SUSPENDING = fields.InstanceTaskState.SUSPENDING

# possible task states during resume()
RESUMING = fields.InstanceTaskState.RESUMING

# possible task states during power_off()
POWERING_OFF = fields.InstanceTaskState.POWERING_OFF

# possible task states during power_on()
POWERING_ON = fields.InstanceTaskState.POWERING_ON

# possible task states during rescue()
RESCUING = fields.InstanceTaskState.RESCUING

# possible task states during unrescue()
UNRESCUING = fields.InstanceTaskState.UNRESCUING

# possible task states during rebuild()
REBUILDING = fields.InstanceTaskState.REBUILDING
REBUILD_BLOCK_DEVICE_MAPPING = \
    fields.InstanceTaskState.REBUILD_BLOCK_DEVICE_MAPPING
REBUILD_SPAWNING = fields.InstanceTaskState.REBUILD_SPAWNING

# possible task states during live_migrate()
MIGRATING = fields.InstanceTaskState.MIGRATING

# possible task states during delete()
DELETING = fields.InstanceTaskState.DELETING

# possible task states during soft_delete()
SOFT_DELETING = fields.InstanceTaskState.SOFT_DELETING

# possible task states during restore()
RESTORING = fields.InstanceTaskState.RESTORING

# possible task states during shelve()
SHELVING = fields.InstanceTaskState.SHELVING
SHELVING_IMAGE_PENDING_UPLOAD = \
    fields.InstanceTaskState.SHELVING_IMAGE_PENDING_UPLOAD
SHELVING_IMAGE_UPLOADING = fields.InstanceTaskState.SHELVING_IMAGE_UPLOADING

# possible task states during shelve_offload()
SHELVING_OFFLOADING = fields.InstanceTaskState.SHELVING_OFFLOADING

# possible task states during unshelve()
UNSHELVING = fields.InstanceTaskState.UNSHELVING

ALLOW_REBOOT = [None, REBOOTING, REBOOT_PENDING, REBOOT_STARTED, RESUMING,
                REBOOTING_HARD, UNPAUSING, PAUSING, SUSPENDING]

# These states indicate a reboot
soft_reboot_states = (REBOOTING, REBOOT_PENDING, REBOOT_STARTED)
hard_reboot_states = (REBOOTING_HARD, REBOOT_PENDING_HARD, REBOOT_STARTED_HARD)

# These states indicate a resize in progress
resizing_states = (RESIZE_PREP, RESIZE_MIGRATING, RESIZE_MIGRATED,
                   RESIZE_FINISH)

# These states indicate a rebuild
rebuild_states = (REBUILDING, REBUILD_BLOCK_DEVICE_MAPPING, REBUILD_SPAWNING)

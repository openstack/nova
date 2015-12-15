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

# possible task states during create()
SCHEDULING = 'scheduling'
BLOCK_DEVICE_MAPPING = 'block_device_mapping'
NETWORKING = 'networking'
SPAWNING = 'spawning'

# possible task states during snapshot()
IMAGE_SNAPSHOT = 'image_snapshot'
IMAGE_SNAPSHOT_PENDING = 'image_snapshot_pending'
IMAGE_PENDING_UPLOAD = 'image_pending_upload'
IMAGE_UPLOADING = 'image_uploading'

# possible task states during backup()
IMAGE_BACKUP = 'image_backup'

# possible task states during set_admin_password()
UPDATING_PASSWORD = 'updating_password'

# possible task states during resize()
RESIZE_PREP = 'resize_prep'
RESIZE_MIGRATING = 'resize_migrating'
RESIZE_MIGRATED = 'resize_migrated'
RESIZE_FINISH = 'resize_finish'

# possible task states during revert_resize()
RESIZE_REVERTING = 'resize_reverting'

# possible task states during confirm_resize()
RESIZE_CONFIRMING = 'resize_confirming'

# possible task states during reboot()
REBOOTING = 'rebooting'
REBOOT_PENDING = 'reboot_pending'
REBOOT_STARTED = 'reboot_started'
REBOOTING_HARD = 'rebooting_hard'
REBOOT_PENDING_HARD = 'reboot_pending_hard'
REBOOT_STARTED_HARD = 'reboot_started_hard'

# possible task states during pause()
PAUSING = 'pausing'

# possible task states during unpause()
UNPAUSING = 'unpausing'

# possible task states during suspend()
SUSPENDING = 'suspending'

# possible task states during resume()
RESUMING = 'resuming'

# possible task states during power_off()
POWERING_OFF = 'powering-off'

# possible task states during power_on()
POWERING_ON = 'powering-on'

# possible task states during rescue()
RESCUING = 'rescuing'

# possible task states during unrescue()
UNRESCUING = 'unrescuing'

# possible task states during rebuild()
REBUILDING = 'rebuilding'
REBUILD_BLOCK_DEVICE_MAPPING = "rebuild_block_device_mapping"
REBUILD_SPAWNING = 'rebuild_spawning'

# possible task states during live_migrate()
MIGRATING = "migrating"

# possible task states during delete()
DELETING = 'deleting'

# possible task states during soft_delete()
SOFT_DELETING = 'soft-deleting'

# possible task states during restore()
RESTORING = 'restoring'

# possible task states during shelve()
SHELVING = 'shelving'
SHELVING_IMAGE_PENDING_UPLOAD = 'shelving_image_pending_upload'
SHELVING_IMAGE_UPLOADING = 'shelving_image_uploading'

# possible task states during shelve_offload()
SHELVING_OFFLOADING = 'shelving_offloading'

# possible task states during unshelve()
UNSHELVING = 'unshelving'

ALLOW_REBOOT = [None, REBOOTING, REBOOT_PENDING, REBOOT_STARTED, RESUMING,
                REBOOTING_HARD, UNPAUSING, PAUSING, SUSPENDING]

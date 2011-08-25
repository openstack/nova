# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

SCHEDULING = 'scheduling'
BLOCK_DEVICE_MAPPING = 'block_device_mapping'
NETWORKING = 'networking'
SPAWNING = 'spawning'

IMAGE_SNAPSHOT = 'image_snapshot'
IMAGE_BACKUP = 'image_backup'

UPDATING_PASSWORD = 'updating_password'

RESIZE_PREP = 'resize_prep'
RESIZE_MIGRATING = 'resize_migrating'
RESIZE_MIGRATED = 'resize_migrated'
RESIZE_FINISH = 'resize_finish'
RESIZE_REVERTING = 'resize_reverting'
RESIZE_CONFIRMING = 'resize_confirming'
RESIZE_VERIFY = 'resize_verify'

REBUILDING = 'rebuilding'

REBOOTING = 'rebooting'
PAUSING = 'pausing'
UNPAUSING = 'unpausing'
SUSPENDING = 'suspending'
RESUMING = 'resuming'

RESCUING = 'rescuing'
UNRESCUING = 'unrescuing'

DELETING = 'deleting'
STOPPING = 'stopping'
STARTING = 'starting'

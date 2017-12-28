# Copyright 2013 OpenStack Foundation
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

"""Possible actions on an instance.

Actions should probably match a user intention at the API level.  Because they
can be user visible that should help to avoid confusion.  For that reason they
tend to maintain the casing sent to the API.

Maintaining a list of actions here should protect against inconsistencies when
they are used.

The naming style of instance actions should be snake_case, as it will
consistent with the API names. Do not modify the old ones because they have
been exposed to users.
"""

CREATE = 'create'
DELETE = 'delete'
EVACUATE = 'evacuate'
RESTORE = 'restore'
STOP = 'stop'
START = 'start'
REBOOT = 'reboot'
REBUILD = 'rebuild'
REVERT_RESIZE = 'revertResize'
CONFIRM_RESIZE = 'confirmResize'
RESIZE = 'resize'
MIGRATE = 'migrate'
PAUSE = 'pause'
UNPAUSE = 'unpause'
SUSPEND = 'suspend'
RESUME = 'resume'
RESCUE = 'rescue'
UNRESCUE = 'unrescue'
CHANGE_PASSWORD = 'changePassword'
SHELVE = 'shelve'
SHELVE_OFFLOAD = 'shelveOffload'
UNSHELVE = 'unshelve'
LIVE_MIGRATION = 'live-migration'
LIVE_MIGRATION_CANCEL = 'live_migration_cancel'
LIVE_MIGRATION_FORCE_COMPLETE = 'live_migration_force_complete'
TRIGGER_CRASH_DUMP = 'trigger_crash_dump'
# The extend_volume action is not like the traditional instance actions which
# are driven directly through the compute API. The extend_volume action is
# initiated by a Cinder volume extend (resize) action. Cinder will call the
# server external events API after the volume extend is performed so that Nova
# can perform any updates on the compute side. The instance actions framework
# is used for tracking this asynchronous operation so the user/admin can know
# when it is done in case they need/want to reboot the guest operating system.
EXTEND_VOLUME = 'extend_volume'
ATTACH_INTERFACE = 'attach_interface'
DETACH_INTERFACE = 'detach_interface'
ATTACH_VOLUME = 'attach_volume'
DETACH_VOLUME = 'detach_volume'
SWAP_VOLUME = 'swap_volume'
LOCK = 'lock'
UNLOCK = 'unlock'
BACKUP = 'createBackup'
CREATE_IMAGE = 'createImage'
